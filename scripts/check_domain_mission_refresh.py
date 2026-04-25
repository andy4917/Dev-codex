#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Any

from _scorecard_common import load_json, resolve_path, save_json, utc_timestamp


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "domain-mission-refresh.final.json"
L2_PLUS = {"L2", "L3", "L4"}
AUTHORITY_REF_HINTS = ("test", "report", "receipt", "checker")
OPEN_REFRESH_STATUSES = {"pending_refresh", "blocked", "stale", "open"}
ALLOWED_REFRESH_STATUSES = OPEN_REFRESH_STATUSES | {"refreshed", "waived", "not_impacted"}
NONASSERTIVE_VERIFICATION_CUES = (
    "no ",
    "not ",
    "without ",
    "pending",
    "blocked",
    "unsupported",
    "unverified",
    "unknown",
    "missing",
    "lacks",
    "lack ",
    "absence",
    "not yet",
    "아님",
    "아직",
    "않",
    "없",
    "미검증",
    "차단",
    "보류",
    "누락",
)
VERIFICATION_CLAIM_RE = re.compile(r"\b(?:verified|verification complete|clean-room passed|passed|pass)\b|검증 완료|통과", re.IGNORECASE)


def _run_root(workspace_root: Path, run_id: str) -> Path:
    return workspace_root / ".agent-runs" / run_id


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, "missing"
    try:
        payload = load_json(path, default={})
    except ValueError:
        return {}, "invalid_json"
    if not isinstance(payload, dict):
        return {}, "not_object"
    return payload, ""


def _severity(profile: str, blocking: bool) -> str:
    return "blocker" if blocking and profile in L2_PLUS else "warning"


def _append_issue(target: dict[str, list[str]], profile: str, message: str, *, blocking: bool) -> None:
    bucket = "blockers" if _severity(profile, blocking) == "blocker" else "warnings"
    if message not in target[bucket]:
        target[bucket].append(message)


def _evidence_refs(payload: dict[str, Any]) -> list[str]:
    refs = payload.get("evidence_refs", [])
    return [str(item).strip() for item in refs if str(item).strip()] if isinstance(refs, list) else []


def _authority_refs(frame: dict[str, Any]) -> list[str]:
    authority = frame.get("closeout_authority", {})
    if not isinstance(authority, dict):
        return []
    refs = authority.get("evidence_refs", [])
    return [str(item).strip() for item in refs if str(item).strip()] if isinstance(refs, list) else []


def _has_authority_ref(frame: dict[str, Any]) -> bool:
    refs = " ".join(_authority_refs(frame)).casefold()
    authority_kind = str(frame.get("closeout_authority", {}).get("authority_kind", "") if isinstance(frame.get("closeout_authority", {}), dict) else "").casefold()
    combined = f"{authority_kind} {refs}"
    return any(hint in combined for hint in AUTHORITY_REF_HINTS)


def _changed_paths(workspace_root: Path) -> list[str]:
    paths: set[str] = set()
    for args in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        result = subprocess.run(
            ["git", "-C", str(workspace_root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            continue
        paths.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    return sorted(paths)


def _touches_authoritative_artifact(changed_paths: list[str]) -> bool:
    prefixes = ("contracts/", "docs/", "tests/", "reports/", "workflows/", "skills/", "templates/")
    filenames = {"SUMMARY.md", "DESIGN_REVIEW.md", "AGENTS.md"}
    return any(path.startswith(prefixes) or path in filenames for path in changed_paths)


def _validate_frame(issues: dict[str, list[str]], profile: str, frame: dict[str, Any], error: str) -> None:
    if error:
        reason = "MISSION_FRAME.json is missing" if error == "missing" else f"MISSION_FRAME.json is {error}"
        _append_issue(issues, profile, reason, blocking=True)
        return
    if not str(frame.get("parent_objective", "")).strip():
        _append_issue(issues, profile, "MISSION_FRAME.json parent_objective is empty", blocking=True)
    done_when = [str(item).strip() for item in frame.get("done_when_evidence", []) if str(item).strip()] if isinstance(frame.get("done_when_evidence", []), list) else []
    if not done_when:
        _append_issue(issues, profile, "MISSION_FRAME.json done_when_evidence is empty", blocking=True)
    if not _has_authority_ref(frame):
        _append_issue(issues, profile, "MISSION_FRAME.json closeout authority lacks tests/reports/receipt/checker evidence", blocking=True)


def _validate_manifest(issues: dict[str, list[str]], profile: str, manifest: dict[str, Any], error: str, changed_paths: list[str]) -> None:
    if error:
        reason = "ARTIFACT_REFRESH_MANIFEST.json is missing" if error == "missing" else f"ARTIFACT_REFRESH_MANIFEST.json is {error}"
        if profile in L2_PLUS or _touches_authoritative_artifact(changed_paths):
            _append_issue(issues, profile, reason, blocking=True)
        else:
            _append_issue(issues, profile, reason, blocking=False)
        return
    for item in manifest.get("impacted_artifacts", []):
        if not isinstance(item, dict):
            _append_issue(issues, profile, "ARTIFACT_REFRESH_MANIFEST.json contains a non-object item", blocking=True)
            continue
        artifact_id = str(item.get("artifact_id", "artifact")).strip() or "artifact"
        status = str(item.get("status", "")).strip().lower()
        if status in OPEN_REFRESH_STATUSES or status not in ALLOWED_REFRESH_STATUSES:
            _append_issue(issues, profile, f"artifact refresh remains open for {artifact_id}: {status or 'missing_status'}", blocking=True)
        if status == "waived" and not str(item.get("waiver_reason", "")).strip():
            _append_issue(issues, profile, f"artifact refresh waiver lacks reason: {artifact_id}", blocking=True)


def _claim_entries(claim_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in claim_ledger.get("claims", []) if isinstance(item, dict)]


def _claim_has_evidence(claim: dict[str, Any]) -> bool:
    return bool([item for item in claim.get("evidence_refs", []) if str(item).strip()]) or bool(
        [item for item in claim.get("verification_refs", []) if str(item).strip()]
    )


def _claim_ledger_maps_summary(claim_ledger: dict[str, Any]) -> bool:
    return any(str(claim.get("status", "")).strip().upper() == "SUPPORTED" and _claim_has_evidence(claim) for claim in _claim_entries(claim_ledger))


def _summary_coverage_maps_summary(summary_coverage: dict[str, Any]) -> bool:
    claims = [dict(item) for item in summary_coverage.get("summary_claims", []) if isinstance(item, dict)]
    if not claims:
        return False
    return all(str(item.get("status", "")).strip().lower() not in {"uncovered", ""} for item in claims)


def _mission_closeout_maps_summary(mission_closeout: dict[str, Any]) -> bool:
    if str(mission_closeout.get("status", "")).strip().upper() == "BLOCKED":
        return False
    evidence = [str(item).strip() for item in mission_closeout.get("authoritative_evidence", []) if str(item).strip()]
    return bool(evidence)


def _summary_uses_verification_claim_language(summary_text: str) -> bool:
    chunks = re.split(r"(?<=[.!?。])\s+|\n+", summary_text)
    for chunk in chunks:
        text = chunk.strip()
        if not text or not VERIFICATION_CLAIM_RE.search(text):
            continue
        lowered = text.casefold()
        if any(cue in lowered for cue in NONASSERTIVE_VERIFICATION_CUES):
            continue
        return True
    return False


def _validate_closeout(
    issues: dict[str, list[str]],
    profile: str,
    mission_closeout: dict[str, Any],
    closeout_error: str,
    claim_ledger: dict[str, Any],
    summary_coverage: dict[str, Any],
    summary_text: str,
) -> None:
    if closeout_error:
        reason = "MISSION_CLOSEOUT.json is missing" if closeout_error == "missing" else f"MISSION_CLOSEOUT.json is {closeout_error}"
        _append_issue(issues, profile, reason, blocking=True)
    elif str(mission_closeout.get("status", "")).strip().upper() == "BLOCKED":
        _append_issue(issues, profile, "MISSION_CLOSEOUT.json status is BLOCKED", blocking=True)

    if _summary_uses_verification_claim_language(summary_text):
        mapped = (
            _mission_closeout_maps_summary(mission_closeout)
            or _claim_ledger_maps_summary(claim_ledger)
            or _summary_coverage_maps_summary(summary_coverage)
        )
        if not mapped:
            _append_issue(issues, profile, "SUMMARY.md uses verification/PASS language without mission, claim, or coverage evidence", blocking=True)


def evaluate_domain_mission_refresh(workspace_root: Path, run_id: str, profile: str = "L2") -> dict[str, Any]:
    resolved_workspace = workspace_root.expanduser().resolve()
    normalized_profile = str(profile or "L2").strip().upper()
    run_root = _run_root(resolved_workspace, run_id)
    paths = {
        "mission_frame": run_root / "MISSION_FRAME.json",
        "artifact_refresh_manifest": run_root / "ARTIFACT_REFRESH_MANIFEST.json",
        "mission_closeout": run_root / "MISSION_CLOSEOUT.json",
        "claim_ledger": run_root / "CLAIM_LEDGER.json",
        "summary_coverage": run_root / "SUMMARY_COVERAGE.json",
        "summary": resolved_workspace / "SUMMARY.md",
    }
    issues: dict[str, list[str]] = {"blockers": [], "warnings": []}
    changed_paths = _changed_paths(resolved_workspace)

    frame, frame_error = _read_json(paths["mission_frame"])
    manifest, manifest_error = _read_json(paths["artifact_refresh_manifest"])
    closeout, closeout_error = _read_json(paths["mission_closeout"])
    claim_ledger, _claim_error = _read_json(paths["claim_ledger"])
    summary_coverage, _coverage_error = _read_json(paths["summary_coverage"])
    summary_text = paths["summary"].read_text(encoding="utf-8", errors="ignore") if paths["summary"].exists() else ""

    if normalized_profile in L2_PLUS:
        _validate_frame(issues, normalized_profile, frame, frame_error)
        _validate_manifest(issues, normalized_profile, manifest, manifest_error, changed_paths)
        _validate_closeout(issues, normalized_profile, closeout, closeout_error, claim_ledger, summary_coverage, summary_text)
    elif normalized_profile == "L1":
        if frame_error:
            _append_issue(issues, normalized_profile, "mission frame is report-only or missing for L1", blocking=False)
        else:
            _validate_frame(issues, normalized_profile, frame, frame_error)
        if manifest_error and not _touches_authoritative_artifact(changed_paths):
            _append_issue(issues, normalized_profile, "refresh manifest missing for L1 with no authoritative changed paths", blocking=False)
        elif manifest_error:
            _append_issue(issues, normalized_profile, "refresh manifest missing for L1 authoritative-path change", blocking=False)
        else:
            _validate_manifest(issues, normalized_profile, manifest, manifest_error, changed_paths)
    else:
        if not frame_error:
            _validate_frame(issues, normalized_profile, frame, frame_error)

    status = "BLOCKED" if issues["blockers"] else ("WARN" if issues["warnings"] else "PASS")
    return {
        "status": status,
        "workspace_root": str(resolved_workspace),
        "run_id": run_id,
        "profile": normalized_profile,
        "blockers": issues["blockers"],
        "warnings": issues["warnings"],
        "checks": {
            "mission_frame_present": not frame_error,
            "artifact_refresh_manifest_present": not manifest_error,
            "mission_closeout_present": not closeout_error,
            "changed_paths": changed_paths,
            "authoritative_changed_paths": _touches_authoritative_artifact(changed_paths),
        },
        "artifacts": {name: str(path) for name, path in paths.items()},
        "generated_at": utc_timestamp(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check domain-aware mission refresh evidence for an IAW run.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", default="L2")
    parser.add_argument("--output-file", default=str(REPORT))
    args = parser.parse_args()

    workspace_root = resolve_path(args.workspace_root) or Path(args.workspace_root)
    report = evaluate_domain_mission_refresh(workspace_root, str(args.run_id).strip(), str(args.profile).strip().upper())
    output = resolve_path(args.output_file, ROOT) or Path(args.output_file)
    save_json(output, report)
    print(report["status"])
    for reason in report["blockers"]:
        print(f"- {reason}")
    for warning in report["warnings"]:
        print(f"- warning: {warning}")
    return 0 if report["status"] in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
