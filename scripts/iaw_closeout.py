#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_AUTHORITY_FILE,
    DEFAULT_DISQUALIFIER_FILE,
    DEFAULT_POLICY_FILE,
    DEFAULT_REVIEW_FILE,
    DEFAULT_SCORECARD_FILE,
    atomic_save_json,
    file_hash,
    gate_receipt_mirror_path,
    gate_receipt_lock_path,
    gate_receipts_root,
    gate_receipt_signature_policy,
    gate_receipt_state_path,
    git_lines,
    git_sha,
    load_authority,
    load_json,
    normalize_status,
    project_id,
    resolve_path,
    stable_json_hash,
    scorecard_targets,
    signed_payload,
    stable_sequence_hash,
    status_exit_code,
    validate_workspace_authority_lease,
    workspace_git_root,
    worktree_id,
)
from check_ai_slop import evaluate_ai_slop
from check_domain_mission_refresh import evaluate_domain_mission_refresh

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SUMMARY_PATH_NAME = "SUMMARY.md"
DESIGN_REVIEW_PATH_NAME = "DESIGN_REVIEW.md"
FORBIDDEN_WAIVER_REASON_CODES = {
    "generic_environment_issue",
    "not_enough_time",
    "agent_decided_unnecessary",
}
PROFILE_REQUIREMENTS = {
    "L1": ("WORKORDER.json", "EVIDENCE_MANIFEST.json"),
    "L2": (
        "WORKORDER.json",
        "PLAN.json",
        "TASK_TREE.json",
        "CONVENTION_LOCK.json",
        "EVIDENCE_MANIFEST.json",
        "COMMAND_LOG.jsonl",
        "WAIVERS.json",
        "REPEATED_VERIFY.json",
        "CLAIM_LEDGER.json",
        "SUMMARY_COVERAGE.json",
        "SLOP_LEDGER.json",
        "REPLAY.md",
    ),
    "L3": (
        "WORKORDER.json",
        "PLAN.json",
        "TASK_TREE.json",
        "CONVENTION_LOCK.json",
        "EVIDENCE_MANIFEST.json",
        "COMMAND_LOG.jsonl",
        "WAIVERS.json",
        "REPEATED_VERIFY.json",
        "CROSS_VERIFICATION.json",
        "CLAIM_LEDGER.json",
        "SUMMARY_COVERAGE.json",
        "SLOP_LEDGER.json",
        "REPLAY.md",
    ),
    "L4": (
        "WORKORDER.json",
        "PLAN.json",
        "TASK_TREE.json",
        "CONVENTION_LOCK.json",
        "EVIDENCE_MANIFEST.json",
        "COMMAND_LOG.jsonl",
        "WAIVERS.json",
        "REPEATED_VERIFY.json",
        "CROSS_VERIFICATION.json",
        "CLAIM_LEDGER.json",
        "SUMMARY_COVERAGE.json",
        "SLOP_LEDGER.json",
        "REPLAY.md",
    ),
}
IGNORED_WORKSPACE_CHANGED_FILES = {
    "reports/scorecard-authority-audit.json",
}


def _workspace_root(raw: str) -> Path:
    path = resolve_path(raw)
    if path is None:
        raise ValueError("workspace_root is required")
    return path.resolve()


def _run_root(workspace_root: Path, run_id: str) -> Path:
    return workspace_root / ".agent-runs" / run_id


def _artifact_paths(workspace_root: Path, run_id: str) -> dict[str, Path]:
    run_root = _run_root(workspace_root, run_id)
    return {
        "run_root": run_root,
        "workorder": run_root / "WORKORDER.json",
        "plan": run_root / "PLAN.json",
        "task_tree": run_root / "TASK_TREE.json",
        "convention_lock": run_root / "CONVENTION_LOCK.json",
        "manifest": run_root / "EVIDENCE_MANIFEST.json",
        "command_log": run_root / "COMMAND_LOG.jsonl",
        "waivers": run_root / "WAIVERS.json",
        "repeated_verify": run_root / "REPEATED_VERIFY.json",
        "cross_verification": run_root / "CROSS_VERIFICATION.json",
        "claim_ledger": run_root / "CLAIM_LEDGER.json",
        "summary_coverage": run_root / "SUMMARY_COVERAGE.json",
        "slop_ledger": run_root / "SLOP_LEDGER.json",
        "mission_frame": run_root / "MISSION_FRAME.json",
        "artifact_refresh_manifest": run_root / "ARTIFACT_REFRESH_MANIFEST.json",
        "mission_closeout": run_root / "MISSION_CLOSEOUT.json",
        "replay": run_root / "REPLAY.md",
        "receipt_mirror": gate_receipt_mirror_path(workspace_root, run_id),
        "summary": workspace_root / SUMMARY_PATH_NAME,
        "design_review": workspace_root / DESIGN_REVIEW_PATH_NAME,
    }


def _required_files(profile: str) -> tuple[str, ...]:
    return PROFILE_REQUIREMENTS.get(profile, ())


def _current_changed_files(workspace_root: Path) -> list[str]:
    changed = set(git_lines(workspace_root, "diff", "--name-only", "HEAD"))
    changed.update(git_lines(workspace_root, "ls-files", "--others", "--exclude-standard"))
    return sorted(
        item
        for item in changed
        if item.strip() and item.strip() not in IGNORED_WORKSPACE_CHANGED_FILES
    )


def _changed_file_content_hash(workspace_root: Path, changed_files: list[str]) -> str:
    entries: list[dict[str, Any]] = []
    for item in changed_files:
        relative_path = str(item).strip()
        if not relative_path:
            continue
        path = workspace_root / relative_path
        entry: dict[str, Any] = {"path": relative_path}
        if path.is_file():
            entry["sha256"] = file_hash(path)
        elif path.exists():
            entry["kind"] = "directory"
        else:
            entry["missing"] = True
        entries.append(entry)
    return stable_json_hash(entries)


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _required_policy_hashes(authority: dict[str, Any]) -> dict[str, str]:
    targets = scorecard_targets(authority).get("required_policy_hash_targets", [])
    paths = [Path(item).expanduser().resolve() for item in targets if str(item).strip()]
    if not paths:
        paths = [DEFAULT_AUTHORITY_FILE, DEFAULT_POLICY_FILE, DEFAULT_DISQUALIFIER_FILE]
    return {path.name: file_hash(path) for path in paths if path.exists()}


def _required_script_hashes(authority: dict[str, Any]) -> dict[str, str]:
    targets = scorecard_targets(authority).get("required_script_hash_targets", [])
    paths = [Path(item).expanduser().resolve() for item in targets if str(item).strip()]
    return {path.name: file_hash(path) for path in paths if path.exists()}


def _validate_profile_artifacts(paths: dict[str, Path], profile: str) -> list[str]:
    reasons: list[str] = []
    for filename in _required_files(profile):
        if not (paths["run_root"] / filename).exists():
            reasons.append(f"required run artifact is missing for {profile}: {filename}")
    if not paths["summary"].exists():
        reasons.append(f"workspace summary is missing: {paths['summary']}")
    if profile in {"L3", "L4"}:
        if not paths["design_review"].exists():
            reasons.append(f"design review is missing for {profile}: {paths['design_review']}")
        else:
            text = paths["design_review"].read_text(encoding="utf-8", errors="ignore").casefold()
            if "patch map" not in text and "policy update workorder:" not in text:
                reasons.append(f"design review patch map is missing for {profile}: {paths['design_review']}")
    return reasons


def _validate_manifest(
    *,
    authority: dict[str, Any],
    workspace_root: Path,
    run_id: str,
    paths: dict[str, Path],
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    reasons: list[str] = []
    manifest = load_json(paths["manifest"], default={})
    if not isinstance(manifest, dict):
        return ["evidence manifest is not a JSON object"], {}, {}

    actual_git_root = workspace_git_root(workspace_root)
    actual_head = git_sha(workspace_root)
    actual_changed_files = _current_changed_files(workspace_root)
    manifest_changed_files = sorted(str(item).strip() for item in manifest.get("changed_files", []) if str(item).strip())
    changed_file_set_hash = stable_sequence_hash(manifest_changed_files)
    required_policy_hashes = _required_policy_hashes(authority)
    required_script_hashes = _required_script_hashes(authority)

    if str(manifest.get("run_id", "")).strip() != run_id:
        reasons.append("evidence manifest run_id mismatch")
    if str(manifest.get("workspace_root_realpath", manifest.get("repo_root", ""))).strip() != str(workspace_root):
        reasons.append("evidence manifest workspace_root_realpath mismatch")
    if actual_git_root != workspace_root:
        reasons.append(f"git root mismatch: expected {workspace_root}, got {actual_git_root}")
    if str(manifest.get("git_root", "")).strip() and str(manifest.get("git_root", "")).strip() != str(actual_git_root):
        reasons.append("evidence manifest git_root mismatch")
    if str(manifest.get("head_commit", "")).strip() != actual_head:
        reasons.append("evidence manifest head_commit mismatch")
    if not str(manifest.get("base_commit", "")).strip():
        reasons.append("evidence manifest base_commit is missing")
    if manifest_changed_files != actual_changed_files:
        reasons.append("evidence manifest changed_files mismatch")
    if str(manifest.get("changed_file_set_hash", "")).strip() != changed_file_set_hash:
        reasons.append("evidence manifest changed_file_set_hash mismatch")

    manifest_policy_hashes = manifest.get("policy_hashes", {})
    current_policy_hashes = manifest_policy_hashes.get("current", {}) if isinstance(manifest_policy_hashes, dict) else {}
    for name, current_hash in required_policy_hashes.items():
        if str(current_policy_hashes.get(name, "")).strip() != current_hash:
            reasons.append(f"evidence manifest policy hash mismatch: {name}")

    manifest_script_hashes = manifest.get("script_hashes", {})
    for name, current_hash in required_script_hashes.items():
        if str(manifest_script_hashes.get(name, "")).strip() != current_hash:
            reasons.append(f"evidence manifest script hash mismatch: {name}")

    commands = [dict(item) for item in manifest.get("commands", []) if isinstance(item, dict)]
    command_ids = {
        str(item.get("command_id", "")).strip()
        for item in commands
        if str(item.get("command_id", "")).strip()
    }
    for item in commands:
        for field in ("command_id", "cmd", "cwd", "exit_code", "started_at", "ended_at"):
            if str(item.get(field, "")).strip() == "":
                reasons.append(f"evidence manifest command is missing {field}")

    allowed_artifact_roots = [paths["run_root"], workspace_root / "reports" / "authority"]
    artifacts = [dict(item) for item in manifest.get("artifacts", []) if isinstance(item, dict)]
    for artifact in artifacts:
        for field in (
            "artifact_id",
            "path",
            "sha256",
            "producer",
            "created_at",
            "workspace_root_realpath",
            "base_commit",
            "head_commit",
            "command_id",
        ):
            if str(artifact.get(field, "")).strip() == "":
                reasons.append(f"evidence manifest artifact is missing {field}")
        artifact_path = resolve_path(str(artifact.get("path", "")), workspace_root)
        if artifact_path is None or not artifact_path.exists():
            reasons.append(f"evidence manifest artifact path is missing: {artifact.get('path', '')}")
            continue
        if not any(_path_within(artifact_path, root) for root in allowed_artifact_roots if root.exists()):
            reasons.append(f"evidence manifest artifact is outside allowed roots: {artifact_path}")
        if file_hash(artifact_path) != str(artifact.get("sha256", "")).strip():
            reasons.append(f"evidence manifest artifact hash mismatch: {artifact_path.name}")
        if str(artifact.get("workspace_root_realpath", "")).strip() != str(workspace_root):
            reasons.append(f"evidence manifest artifact workspace_root_realpath mismatch: {artifact_path.name}")
        if str(artifact.get("head_commit", "")).strip() != actual_head:
            reasons.append(f"evidence manifest artifact head_commit mismatch: {artifact_path.name}")
        if str(artifact.get("base_commit", "")).strip() != str(manifest.get("base_commit", "")).strip():
            reasons.append(f"evidence manifest artifact base_commit mismatch: {artifact_path.name}")
        command_id = str(artifact.get("command_id", "")).strip()
        if command_id not in command_ids:
            reasons.append(f"evidence manifest artifact command_id mismatch: {artifact_path.name}")

    return reasons, manifest, {
        "changed_files": actual_changed_files,
        "changed_file_set_hash": changed_file_set_hash,
        "changed_file_content_hash": _changed_file_content_hash(workspace_root, actual_changed_files),
        "policy_hashes": required_policy_hashes,
        "script_hashes": required_script_hashes,
        "evidence_manifest_hash": file_hash(paths["manifest"]) if paths["manifest"].exists() else "",
    }


def _validate_waivers(paths: dict[str, Path]) -> list[str]:
    reasons: list[str] = []
    waivers = load_json(paths["waivers"], default={})
    if not isinstance(waivers, dict):
        return ["waivers payload is not a JSON object"]
    for entry in waivers.get("waivers", []):
        if not isinstance(entry, dict):
            reasons.append("waiver entry is not an object")
            continue
        for field in ("reason_code", "source", "affected_gate", "risk_acceptance", "expiry", "fallback_evidence"):
            if str(entry.get(field, "")).strip() == "":
                reasons.append(f"waiver entry is missing {field}")
        reason_code = str(entry.get("reason_code", "")).strip()
        if reason_code in FORBIDDEN_WAIVER_REASON_CODES:
            reasons.append(f"waiver uses forbidden reason_code: {reason_code}")
    return reasons


def _extend_unique(target: list[str], incoming: list[str]) -> None:
    for item in incoming:
        text = str(item).strip()
        if text and text not in target:
            target.append(text)


def _run_step(label: str, argv: list[str], cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "label": label,
        "argv": argv,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _report_path(phase: str) -> Path:
    return ROOT / "reports" / f"audit.{phase}.json"


def _build_receipt(
    *,
    authority: dict[str, Any],
    workspace_root: Path,
    run_id: str,
    profile: str,
    mode: str,
    manifest: dict[str, Any],
    manifest_meta: dict[str, Any],
    gate_status: str,
    scorecard_ref: Path,
    score_layer_ref: Path,
    audit_refs: dict[str, str],
    summary_ref: Path,
    preflight_reasons: list[str],
    step_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_gate_status = normalize_status(gate_status, "UNKNOWN")
    state_path = gate_receipt_state_path(workspace_root, run_id, authority)
    mirror_path = gate_receipt_mirror_path(workspace_root, run_id)
    changed_files = [str(item).strip() for item in manifest_meta.get("changed_files", []) if str(item).strip()]
    release_mode = mode == "release"
    release_scope_authoritative = release_mode and profile == "L4"
    payload = {
        "schema_version": 2,
        "run_id": run_id,
        "profile": profile,
        "mode": mode,
        "workspace_root_realpath": str(workspace_root),
        "git_root": str(workspace_git_root(workspace_root)),
        "base_commit": str(manifest.get("base_commit", "")).strip(),
        "head_commit": str(manifest.get("head_commit", "")).strip(),
        "changed_file_set_hash": str(manifest_meta.get("changed_file_set_hash", "")).strip(),
        "changed_file_content_hash": str(manifest_meta.get("changed_file_content_hash", "")).strip(),
        "policy_hashes": dict(manifest_meta.get("policy_hashes", {})),
        "script_hashes": dict(manifest_meta.get("script_hashes", {})),
        "evidence_manifest_hash": str(manifest_meta.get("evidence_manifest_hash", "")).strip(),
        "gate_status": normalized_gate_status,
        "scorecard_ref": str(scorecard_ref),
        "score_layer_ref": str(score_layer_ref),
        "audit_refs": audit_refs,
        "summary_ref": str(summary_ref),
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "codex_project_id": project_id(workspace_root),
        "worktree_id": worktree_id(workspace_root),
        "preflight_reasons": preflight_reasons,
        "step_failures": list(step_failures or []),
        "authoritative": True,
        "signature_policy": gate_receipt_signature_policy(),
        "authority_layer": {
            "kind": "signed_gate_receipt",
            "state_root": str(gate_receipts_root(authority)),
            "state_path": str(state_path),
            "mirror_path": str(mirror_path),
        },
        "workspace_identity": {
            "workspace_root_realpath": str(workspace_root),
            "git_root": str(workspace_git_root(workspace_root)),
            "codex_project_id": project_id(workspace_root),
            "worktree_id": worktree_id(workspace_root),
        },
        "evidence_binding": {
            "changed_files": changed_files,
            "changed_file_count": len(changed_files),
            "changed_file_set_hash": str(manifest_meta.get("changed_file_set_hash", "")).strip(),
            "changed_file_content_hash": str(manifest_meta.get("changed_file_content_hash", "")).strip(),
            "evidence_manifest_hash": str(manifest_meta.get("evidence_manifest_hash", "")).strip(),
            "policy_hashes": dict(manifest_meta.get("policy_hashes", {})),
            "script_hashes": dict(manifest_meta.get("script_hashes", {})),
        },
        "release_semantics": {
            "scope": "release" if release_mode else "verification",
            "release_mode": release_mode,
            "release_profile_required": "L4",
            "release_scope_authoritative": release_scope_authoritative,
            "release_ready": release_scope_authoritative and normalized_gate_status == "PASS",
            "verify_claims_authoritative": True,
        },
    }
    return signed_payload(payload, authority=authority, create=mode != "release")


@contextmanager
def _receipt_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"gate receipt lock is already held: {lock_path}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"pid={os.getpid()}\n")
            handle.write(f"created_at={datetime.now(timezone.utc).isoformat()}\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _save_receipt(authority: dict[str, Any], workspace_root: Path, run_id: str, receipt: dict[str, Any]) -> tuple[Path, Path]:
    state_path = gate_receipt_state_path(workspace_root, run_id, authority)
    mirror_path = gate_receipt_mirror_path(workspace_root, run_id)
    lock_path = gate_receipt_lock_path(workspace_root, run_id, authority)
    with _receipt_lock(lock_path):
        atomic_save_json(state_path, receipt)
        atomic_save_json(mirror_path, receipt)
    return state_path, mirror_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the authoritative IAW close-out chain and issue a signed gate receipt.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("L1", "L2", "L3", "L4"), required=True)
    parser.add_argument("--mode", choices=("verify", "release"), default="verify")
    parser.add_argument("--review-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--scorecard-file", default=str(DEFAULT_SCORECARD_FILE))
    parser.add_argument("--authority-file", default=str(DEFAULT_AUTHORITY_FILE))
    args = parser.parse_args()

    authority = load_authority(Path(args.authority_file))
    workspace_root = _workspace_root(args.workspace_root)
    run_id = str(args.run_id).strip()
    profile = str(args.profile).strip()
    mode = str(args.mode).strip()
    scorecard_cfg = scorecard_targets(authority)
    allowed_profiles = {str(item).strip() for item in scorecard_cfg.get("accepted_profiles", []) if str(item).strip()}
    paths = _artifact_paths(workspace_root, run_id)
    review_file = resolve_path(args.review_file, ROOT) or Path(args.review_file)
    scorecard_file = resolve_path(args.scorecard_file, ROOT) or Path(args.scorecard_file)
    score_layer_file = resolve_path(
        scorecard_cfg.get("score_layer_report", str(ROOT / "reports" / "score-layer.final.json")),
        ROOT,
    ) or (ROOT / "reports" / "score-layer.final.json")
    closeout_script = Path(scorecard_cfg.get("closeout", __file__)).expanduser().resolve()

    preflight_reasons: list[str] = []
    if allowed_profiles and profile not in allowed_profiles:
        preflight_reasons.append(f"close-out profile is not allowed by workspace authority: {profile}")
    if mode == "release" and profile != "L4":
        preflight_reasons.append("release mode requires the L4 close-out profile")
    if profile == "L4" and mode != "release":
        preflight_reasons.append("L4 close-out profile requires release mode")
    lease_verdict = validate_workspace_authority_lease(workspace_root, required=True, authority=authority)
    _extend_unique(preflight_reasons, lease_verdict["reasons"])
    _extend_unique(preflight_reasons, _validate_profile_artifacts(paths, profile))
    _extend_unique(preflight_reasons, evaluate_ai_slop(workspace_root, run_id, profile)["blockers"])
    _extend_unique(preflight_reasons, evaluate_domain_mission_refresh(workspace_root, run_id, profile)["blockers"])
    manifest_reasons, manifest, manifest_meta = _validate_manifest(
        authority=authority,
        workspace_root=workspace_root,
        run_id=run_id,
        paths=paths,
    )
    _extend_unique(preflight_reasons, manifest_reasons)
    _extend_unique(preflight_reasons, _validate_waivers(paths))

    if preflight_reasons:
        try:
            receipt = _build_receipt(
                authority=authority,
                workspace_root=workspace_root,
                run_id=run_id,
                profile=profile,
                mode=mode,
                manifest=manifest,
                manifest_meta=manifest_meta,
                gate_status="BLOCKED",
                scorecard_ref=scorecard_file,
                score_layer_ref=score_layer_file,
                audit_refs={},
                summary_ref=paths["summary"],
                preflight_reasons=preflight_reasons,
                step_failures=[],
            )
            state_path, mirror_path = _save_receipt(authority, workspace_root, run_id, receipt)
        except (FileNotFoundError, RuntimeError) as exc:
            print(f"BLOCKED: preflight failed for {workspace_root}")
            for reason in preflight_reasons:
                print(f"- {reason}")
            print(f"- receipt issuance blocked: {exc}")
            return status_exit_code("BLOCKED")
        print(f"BLOCKED: preflight failed for {workspace_root}")
        for reason in preflight_reasons:
            print(f"- {reason}")
        print(f"- gate receipt: {state_path}")
        print(f"- gate receipt mirror: {mirror_path}")
        return status_exit_code("BLOCKED")

    steps = [
        _run_step(
            "prepare",
            [
                sys.executable,
                str(SCRIPTS / "prepare_user_scorecard_review.py"),
                "--workspace-root",
                str(workspace_root),
                "--run-id",
                run_id,
                "--mode",
                mode,
                "--review-snapshot-output",
                str(review_file),
            ],
            ROOT,
        ),
        _run_step(
            "environment_baseline",
            [
                sys.executable,
                str(SCRIPTS / "check_user_dev_environment.py"),
            ],
            ROOT,
        ),
        _run_step(
            "delivery_gate",
            [
                sys.executable,
                str(SCRIPTS / "delivery_gate.py"),
                "--mode",
                mode,
                "--workspace-root",
                str(workspace_root),
                "--run-id",
                run_id,
                "--review-file",
                str(review_file),
                "--output-file",
                str(scorecard_file),
            ],
            ROOT,
        ),
        _run_step(
            "global_workflow",
            [
                sys.executable,
                str(SCRIPTS / "check_global_agent_workflow.py"),
            ],
            ROOT,
        ),
        _run_step(
            "export_summary",
            [
                sys.executable,
                str(SCRIPTS / "export_user_score_summary.py"),
                "--scorecard-file",
                str(scorecard_file),
                "--receipt-file",
                str(gate_receipt_state_path(workspace_root, run_id, authority)),
                "--allow-pending-receipt",
            ],
            ROOT,
        ),
    ]

    for step in steps:
        print(f"## {step['label']}")
        if step["stdout"].strip():
            print(step["stdout"].rstrip())
        if step["stderr"].strip():
            print(step["stderr"].rstrip())

    gate_payload = load_json(scorecard_file, default={})
    gate_status = normalize_status(gate_payload.get("gate_status"), "UNKNOWN")
    step_failures = [
        {"label": str(step.get("label", "")).strip(), "returncode": int(step.get("returncode", 0))}
        for step in steps
        if int(step.get("returncode", 0)) != 0
    ]
    for failure in step_failures:
        label = failure["label"]
        returncode = failure["returncode"]
        if label == "delivery_gate":
            gate_status = "FAIL" if returncode == status_exit_code("FAIL") else "BLOCKED"
            break
        if label in {"prepare", "export_summary"}:
            gate_status = "BLOCKED"
            break
    audit_refs = {
        "environment_baseline": str(ROOT / "reports" / "user-dev-environment-baseline.final.json"),
        "global_workflow": str(ROOT / "reports" / "global-agent-workflow.final.json"),
    }
    score_layer_payload = {
        "status": "PASS" if not step_failures else "BLOCKED",
        "source": "windows_only_closeout_chain",
        "checks": audit_refs,
    }
    atomic_save_json(score_layer_file, score_layer_payload)
    if score_layer_payload["status"] == "BLOCKED":
        gate_status = "BLOCKED"
    if gate_status == "UNKNOWN":
        gate_status = "BLOCKED"

    try:
        receipt = _build_receipt(
            authority=authority,
            workspace_root=workspace_root,
            run_id=run_id,
            profile=profile,
            mode=mode,
            manifest=manifest,
            manifest_meta=manifest_meta,
            gate_status=gate_status,
            scorecard_ref=scorecard_file,
            score_layer_ref=score_layer_file,
            audit_refs=audit_refs,
            summary_ref=paths["summary"],
            preflight_reasons=[],
            step_failures=step_failures,
        )
        state_path, mirror_path = _save_receipt(authority, workspace_root, run_id, receipt)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"## gate_receipt")
        print(f"- closeout command: python {closeout_script} --workspace-root {workspace_root} --run-id {run_id} --profile {profile} --mode {mode}")
        print(f"- gate status: BLOCKED")
        print(f"- receipt issuance blocked: {exc}")
        return status_exit_code("BLOCKED")
    print(f"## gate_receipt")
    print(f"- closeout command: python {closeout_script} --workspace-root {workspace_root} --run-id {run_id} --profile {profile} --mode {mode}")
    print(f"- gate status: {gate_status}")
    print(f"- gate receipt: {state_path}")
    print(f"- gate receipt mirror: {mirror_path}")
    return status_exit_code(gate_status)


if __name__ == "__main__":
    raise SystemExit(main())
