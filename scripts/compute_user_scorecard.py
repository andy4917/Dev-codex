#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_DISQUALIFIER_FILE,
    DEFAULT_POLICY_FILE,
    DEFAULT_REVIEW_FILE,
    DEFAULT_SCORECARD_FILE,
    current_policy_hashes,
    file_hash,
    git_sha,
    load_json,
    load_jsonl,
    normalize_status,
    normalize_user_review,
    project_id,
    published_command_log_path,
    published_evidence_manifest_path,
    published_workorder_path,
    published_waivers_path,
    published_task_tree_path,
    published_repeated_verify_path,
    published_cross_verification_path,
    published_claim_ledger_path,
    published_summary_coverage_path,
    published_convention_lock_path,
    published_taste_gate_path,
    resolve_path,
    reviewer_verdict_dir,
    save_json,
    strip_signature,
    status_exit_code,
    utc_timestamp,
    verify_truth_signature,
    worktree_id,
)
from check_disqualifiers import evaluate_disqualifiers

REVIEWER_ROLES = (
    "skeptic_reviewer",
    "correctness_verifier",
    "contamination_monitor",
    "final_auditor",
)

WRITER_OR_AGENT_REPORTERS = {"writer", "main_writer", "actor", "agent", "assistant", "codex"}
ENGINE_OWNED_CREDIT_SOURCES = {"verified_execution", "clean_room_verify", "reviewer_penalty", "system_derived"}
ENGINE_OWNED_CREDIT_INPUT_FIELDS = ("requested_credit", "credited_credit")
LEGACY_SIGNAL_CODE_ALIASES = {
    "unauthorized_user_review_update": "unauthorized_user_review_modification",
    "derived_award_spoof_attempt": "reserved_derived_award_spoofing",
    "unexpected_user_award_axis": "excessive_bonus_request",
    "excessive_user_award_points": "excessive_bonus_request",
    "non_user_award_source": "non_user_source_award",
}
DECISION_ORDER = {"warn": 0, "penalty": 1, "cap": 2, "dq": 3}
AUTO_DQ_DEFAULT_CODES = {
    "unauthorized_user_review_modification",
    "reserved_derived_award_spoofing",
    "reviewer_truth_tamper",
    "score_policy_tamper_without_policy_update_workorder",
    "protected_path_access_attempt",
}
TASK_MARKDOWN_REQUIRED_HEADINGS = (
    "Objective",
    "Inputs Read",
    "Changes Made",
    "Claims",
    "Evidence Ref",
    "Verification",
    "Open Questions",
)
VERIFICATION_WORD_PHRASES = (
    "verified",
    "verification complete",
    "as verified",
    "clean-room passed",
)
UNSUPPORTED_TRANSITION_PHRASES = (
    "therefore",
    "consistent with",
)
NEGATIVE_FINDINGS_HEADING_RE = re.compile(r"^\s*##+\s+Negative Findings\s*$", re.MULTILINE | re.IGNORECASE)


def _bool_flag(context: dict[str, Any], key: str) -> bool:
    return bool(context.get(key, False))


def _is_writer_or_agent_reporter(reported_by: str) -> bool:
    return reported_by in WRITER_OR_AGENT_REPORTERS


def _normalized_credit_source(reported_by: str) -> str:
    if reported_by in {"user", "user_review"}:
        return "user_approved_review"
    if reported_by in {"verified_execution", "clean_room_verify", "user_approved_review", "reviewer_penalty", "system_derived", "agent_request"}:
        return reported_by
    return "agent_request"


def _requested_credit_entry(axis: str, requested_points: int, source: str, reason: str, evidence_refs: list[str]) -> dict[str, Any]:
    return {
        "axis": axis,
        "requested_points": requested_points,
        "source": source,
        "reason": reason,
        "evidence_ref": evidence_refs[0] if evidence_refs else "",
    }


def _credited_credit_entry(entry: dict[str, Any]) -> dict[str, Any]:
    requested_points = int(entry.get("requested_points", entry.get("points", 0)))
    credited_points = int(entry.get("credited_points", entry.get("points", 0)))
    block_reason = str(entry.get("credit_block_reason", "")).strip()
    return {
        "axis": str(entry.get("axis", "")).strip(),
        "requested_points": requested_points,
        "credited_points": credited_points,
        "source": str(entry.get("source", "")).strip() or _normalized_credit_source(str(entry.get("reported_by", "")).strip().lower()),
        "capped": credited_points < requested_points and credited_points > 0,
        "blocked": credited_points == 0 and bool(block_reason),
        "block_reason": block_reason,
    }


def _compat_evidence_manifest(
    raw_manifest: dict[str, Any],
    *,
    manifest_path: Path | None,
    workspace_root: Path | None,
) -> dict[str, Any]:
    if raw_manifest.get("schema_version") == 1:
        manifest = dict(raw_manifest)
    else:
        fallback_head = git_sha(workspace_root) if workspace_root is not None else "nogit"
        fallback_head = fallback_head or "nogit"
        raw_git_sha = str(raw_manifest.get("git_sha", "")).strip() or fallback_head
        manifest = {
            "schema_version": 0,
            "run_id": str(raw_manifest.get("trace_id", "")).strip()
            or (manifest_path.parent.name if manifest_path is not None and manifest_path.name == "EVIDENCE_MANIFEST.json" else ""),
            "base_commit": raw_git_sha,
            "head_commit": raw_git_sha,
            "changed_files": [],
            "commands": [],
            "artifacts": [],
            "waivers": [],
            "policy_hashes": {
                "current": current_policy_hashes(),
            },
            "state_history": [],
            "trace": {},
        }
    manifest["base_commit"] = str(manifest.get("base_commit", "")).strip() or "nogit"
    manifest["head_commit"] = str(manifest.get("head_commit", "")).strip() or manifest["base_commit"]
    manifest["commands"] = list(manifest.get("commands", []))
    manifest["changed_files"] = list(manifest.get("changed_files", []))
    manifest["artifacts"] = list(manifest.get("artifacts", []))
    manifest["waivers"] = list(manifest.get("waivers", []))
    manifest["policy_hashes"] = dict(manifest.get("policy_hashes", {}))
    manifest["trace"] = dict(manifest.get("trace", {}))
    return manifest


def _load_support_artifacts(authority_review: dict[str, Any], workspace_root: Path | None) -> dict[str, Any]:
    evidence_inputs = authority_review.get("evidence_inputs", {})
    requested_run_id = str(authority_review.get("run_id", "")).strip()
    manifest_path = resolve_path(evidence_inputs.get("evidence_manifest_path", ""), workspace_root)
    if manifest_path is None and workspace_root is not None:
        manifest_path = published_evidence_manifest_path(workspace_root, run_id=requested_run_id)
    manifest_payload = load_json(manifest_path) if manifest_path is not None and manifest_path.exists() else {}
    manifest = _compat_evidence_manifest(manifest_payload if isinstance(manifest_payload, dict) else {}, manifest_path=manifest_path, workspace_root=workspace_root)
    if not requested_run_id:
        requested_run_id = str(manifest.get("run_id", "")).strip()

    workorder_path = resolve_path(evidence_inputs.get("workorder_path", ""), workspace_root)
    if workorder_path is None and workspace_root is not None:
        workorder_path = published_workorder_path(workspace_root, manifest_path, run_id=requested_run_id)
    workorder = load_json(workorder_path) if workorder_path is not None and workorder_path.exists() else {}

    command_log_path = resolve_path(evidence_inputs.get("command_log_path", ""), workspace_root)
    if command_log_path is None and workspace_root is not None:
        command_log_path = published_command_log_path(workspace_root, manifest_path, run_id=requested_run_id)
    command_log = load_jsonl(command_log_path) if command_log_path is not None and command_log_path.exists() else []

    waivers_path = resolve_path(evidence_inputs.get("waivers_path", ""), workspace_root)
    if waivers_path is None and workspace_root is not None:
        waivers_path = published_waivers_path(workspace_root, manifest_path, run_id=requested_run_id)
    waivers = load_json(waivers_path) if waivers_path is not None and waivers_path.exists() else {}

    task_tree_path = resolve_path(evidence_inputs.get("task_tree_path", ""), workspace_root)
    if task_tree_path is None and workspace_root is not None:
        task_tree_path = published_task_tree_path(workspace_root, manifest_path, run_id=requested_run_id)
    task_tree = load_json(task_tree_path) if task_tree_path is not None and task_tree_path.exists() else {}

    repeated_verify_path = resolve_path(evidence_inputs.get("repeated_verify_path", ""), workspace_root)
    if repeated_verify_path is None and workspace_root is not None:
        repeated_verify_path = published_repeated_verify_path(workspace_root, manifest_path, run_id=requested_run_id)
    repeated_verify = load_json(repeated_verify_path) if repeated_verify_path is not None and repeated_verify_path.exists() else {}

    cross_verification_path = resolve_path(evidence_inputs.get("cross_verification_path", ""), workspace_root)
    if cross_verification_path is None and workspace_root is not None:
        cross_verification_path = published_cross_verification_path(workspace_root, manifest_path, run_id=requested_run_id)
    cross_verification = load_json(cross_verification_path) if cross_verification_path is not None and cross_verification_path.exists() else {}

    claim_ledger_path = resolve_path(evidence_inputs.get("claim_ledger_path", ""), workspace_root)
    if claim_ledger_path is None and workspace_root is not None:
        claim_ledger_path = published_claim_ledger_path(workspace_root, manifest_path, run_id=requested_run_id)
    claim_ledger = load_json(claim_ledger_path) if claim_ledger_path is not None and claim_ledger_path.exists() else {}

    summary_coverage_path = resolve_path(evidence_inputs.get("summary_coverage_path", ""), workspace_root)
    if summary_coverage_path is None and workspace_root is not None:
        summary_coverage_path = published_summary_coverage_path(workspace_root, manifest_path, run_id=requested_run_id)
    summary_coverage = load_json(summary_coverage_path) if summary_coverage_path is not None and summary_coverage_path.exists() else {}

    convention_lock_path = resolve_path(evidence_inputs.get("convention_lock_path", ""), workspace_root)
    if convention_lock_path is None and workspace_root is not None:
        convention_lock_path = published_convention_lock_path(workspace_root, manifest_path, run_id=requested_run_id)
    convention_lock = load_json(convention_lock_path) if convention_lock_path is not None and convention_lock_path.exists() else {}

    taste_gate_path = resolve_path(evidence_inputs.get("taste_gate_path", ""), workspace_root)
    if taste_gate_path is None and workspace_root is not None:
        taste_gate_path = published_taste_gate_path(workspace_root, manifest_path, run_id=requested_run_id)
    taste_gate = load_json(taste_gate_path) if taste_gate_path is not None and taste_gate_path.exists() else {}

    summary_path = resolve_path(evidence_inputs.get("summary_path", ""), workspace_root)
    if summary_path is None and workspace_root is not None:
        candidate = workspace_root / "SUMMARY.md"
        if candidate.exists():
            summary_path = candidate

    design_review_path = resolve_path(evidence_inputs.get("design_review_path", ""), workspace_root)
    if design_review_path is None and workspace_root is not None:
        candidate = workspace_root / "DESIGN_REVIEW.md"
        if candidate.exists():
            design_review_path = candidate

    current_head = git_sha(workspace_root) if workspace_root is not None else "nogit"
    current_head = current_head or "nogit"
    manifest_head = str(manifest.get("head_commit", "")).strip() or current_head
    manifest_base = str(manifest.get("base_commit", "")).strip() or manifest_head
    is_current = current_head == "nogit" or manifest_head == current_head or manifest_head == "nogit"
    run_root = manifest_path.parent if manifest_path is not None and manifest_path.name == "EVIDENCE_MANIFEST.json" else None
    task_markdown_paths: list[Path] = []
    if isinstance(run_root, Path):
        task_markdown_paths = sorted(path for path in (run_root / "tasks").glob("stage-*/task-*.md") if path.is_file())

    return {
        "workspace_root": workspace_root,
        "evidence_manifest_path": manifest_path,
        "evidence_manifest": manifest,
        "workorder_path": workorder_path,
        "workorder": workorder if isinstance(workorder, dict) else {},
        "command_log_path": command_log_path,
        "command_log": command_log,
        "waivers_path": waivers_path,
        "waivers": waivers if isinstance(waivers, dict) else {},
        "task_tree_path": task_tree_path,
        "task_tree": task_tree if isinstance(task_tree, dict) else {},
        "task_markdown_paths": task_markdown_paths,
        "repeated_verify_path": repeated_verify_path,
        "repeated_verify": repeated_verify if isinstance(repeated_verify, dict) else {},
        "cross_verification_path": cross_verification_path,
        "cross_verification": cross_verification if isinstance(cross_verification, dict) else {},
        "claim_ledger_path": claim_ledger_path,
        "claim_ledger": claim_ledger if isinstance(claim_ledger, dict) else {},
        "summary_coverage_path": summary_coverage_path,
        "summary_coverage": summary_coverage if isinstance(summary_coverage, dict) else {},
        "convention_lock_path": convention_lock_path,
        "convention_lock": convention_lock if isinstance(convention_lock, dict) else {},
        "taste_gate_path": taste_gate_path,
        "taste_gate": taste_gate if isinstance(taste_gate, dict) else {},
        "summary_path": summary_path,
        "summary_text": summary_path.read_text(encoding="utf-8", errors="ignore") if isinstance(summary_path, Path) and summary_path.exists() else "",
        "design_review_path": design_review_path,
        "design_review_text": design_review_path.read_text(encoding="utf-8", errors="ignore") if isinstance(design_review_path, Path) and design_review_path.exists() else "",
        "base_commit": manifest_base,
        "head_commit": manifest_head,
        "current_head_commit": current_head,
        "is_current": is_current,
        "run_root": run_root,
        "requested_run_id": requested_run_id,
    }


def _build_signal_provenance(
    support: dict[str, Any],
    *,
    source_path: str = "",
    fallback_path: str = "",
) -> dict[str, Any]:
    raw_source = source_path.strip() or fallback_path.strip()
    workspace_root = support.get("workspace_root")
    path = resolve_path(raw_source, workspace_root if isinstance(workspace_root, Path) else None) if raw_source else None
    if path is None:
        path = support.get("evidence_manifest_path")
    source_hash = ""
    if isinstance(path, Path) and path.exists() and path.is_file():
        source_hash = file_hash(path)
    return {
        "source_file": str(path) if isinstance(path, Path) else raw_source,
        "source_hash": source_hash,
        "base_commit": str(support.get("base_commit", "")).strip(),
        "head_commit": str(support.get("head_commit", "")).strip(),
    }


def _normalized_text(value: object) -> str:
    return str(value or "").strip()


def _waiver_entries(support: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in support.get("evidence_manifest", {}).get("waivers", []):
        if isinstance(item, dict):
            entries.append(item)
    waiver_payload = support.get("waivers", {})
    if isinstance(waiver_payload, dict):
        for item in waiver_payload.get("waivers", []):
            if isinstance(item, dict):
                entries.append(item)
    return entries


def _waiver_reason(support: dict[str, Any], *waiver_ids: str) -> str:
    wanted = {str(item).strip().casefold() for item in waiver_ids if str(item).strip()}
    for entry in _waiver_entries(support):
        entry_id = str(entry.get("id", entry.get("affected_gate", ""))).strip().casefold()
        if entry_id and entry_id in wanted:
            reason = str(entry.get("reason", "")).strip()
            if reason:
                return reason
            return str(entry.get("reason_code", "")).strip()
    return ""


def _v12_contract_active(support: dict[str, Any]) -> bool:
    workorder = support.get("workorder", {})
    if isinstance(workorder, dict) and workorder.get("taste_gate"):
        return True
    return any(
        bool(support.get(key))
        for key in (
            "task_tree_path",
            "repeated_verify_path",
            "cross_verification_path",
            "claim_ledger_path",
            "summary_coverage_path",
            "convention_lock_path",
            "taste_gate_path",
        )
    )


def _summary_has_negative_findings(text: str) -> bool:
    return bool(NEGATIVE_FINDINGS_HEADING_RE.search(text or ""))


def _task_markdown_issues(task_refs: list[str], task_markdown_paths: list[Path]) -> list[str]:
    issues: list[str] = []
    path_map = {str(path): path for path in task_markdown_paths}
    for ref in task_refs:
        if ref not in path_map:
            issues.append(f"missing task markdown: {ref}")
            continue
        text = path_map[ref].read_text(encoding="utf-8", errors="ignore")
        headings = {
            match.group(1).strip().casefold()
            for match in re.finditer(r"^\s*##+\s*(.+?)\s*$", text, flags=re.MULTILINE)
        }
        missing = [heading for heading in TASK_MARKDOWN_REQUIRED_HEADINGS if heading.casefold() not in headings]
        if missing:
            issues.append(f"{ref} missing sections: {', '.join(missing)}")
    return issues


def _claim_entries(support: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = support.get("claim_ledger", {})
    if not isinstance(ledger, dict):
        return []
    return [dict(item) for item in ledger.get("claims", []) if isinstance(item, dict)]


def _claim_phrase_findings(support: dict[str, Any]) -> dict[str, Any]:
    verification_refs: list[str] = []
    transition_refs: list[str] = []
    stale_refs: list[str] = []
    claims = _claim_entries(support)
    if claims:
        for claim in claims:
            claim_text = _normalized_text(claim.get("claim_text", "")).casefold()
            claim_id = _normalized_text(claim.get("claim_id", "")) or _normalized_text(claim.get("source_ref", ""))
            evidence_refs = [str(item).strip() for item in claim.get("evidence_refs", []) if str(item).strip()]
            verification_artifacts = [str(item).strip() for item in claim.get("verification_refs", []) if str(item).strip()]
            if any(phrase in claim_text for phrase in VERIFICATION_WORD_PHRASES) and not evidence_refs and not verification_artifacts:
                verification_refs.append(claim_id)
            if any(phrase in claim_text for phrase in UNSUPPORTED_TRANSITION_PHRASES) and not evidence_refs:
                transition_refs.append(claim_id)
            if str(claim.get("status", "")).strip().upper() in {"UNVERIFIED", "UNKNOWN", "DISPUTED"}:
                stale_refs.append(claim_id)
    else:
        fallback_sources: list[tuple[str, str]] = []
        if support.get("summary_text"):
            fallback_sources.append((str(support.get("summary_path", "")), str(support.get("summary_text", ""))))
        for path in support.get("task_markdown_paths", []):
            if isinstance(path, Path) and path.exists():
                fallback_sources.append((str(path), path.read_text(encoding="utf-8", errors="ignore")))
        for source_ref, text in fallback_sources:
            lowered = text.casefold()
            has_evidence_ref = "evidence ref" in lowered or "evidence_ref" in lowered
            if any(phrase in lowered for phrase in VERIFICATION_WORD_PHRASES) and not has_evidence_ref:
                verification_refs.append(source_ref)
            if any(phrase in lowered for phrase in UNSUPPORTED_TRANSITION_PHRASES) and not has_evidence_ref:
                transition_refs.append(source_ref)
    return {
        "verification_word_without_artifact_count": len(sorted(set(verification_refs))),
        "verification_word_without_artifact_refs": sorted(set(verification_refs)),
        "unsupported_transition_count": len(sorted(set(transition_refs))),
        "unsupported_transition_refs": sorted(set(transition_refs)),
        "stale_claim_count": len(sorted(set(stale_refs))),
        "stale_claim_refs": sorted(set(stale_refs)),
    }


def _summary_stage(status: str, reason: str = "", **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "reason": reason}
    payload.update(extra)
    return payload


def _taste_gate_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    taste_gate = support.get("taste_gate", {})
    if not isinstance(taste_gate, dict) or not taste_gate:
        workorder = support.get("workorder", {})
        if isinstance(workorder, dict):
            taste_gate = dict(workorder.get("taste_gate", {}))
    waiver_reason = _waiver_reason(support, "taste_gate")
    if not taste_gate:
        if legacy:
            return _summary_stage(
                "WAIVED",
                "legacy run without taste gate",
                problem_class="UNKNOWN",
                checkpoint_required=False,
                checkpoint_status="WAIVED",
            )
        if waiver_reason:
            return _summary_stage(
                "WAIVED",
                waiver_reason,
                problem_class="UNKNOWN",
                checkpoint_required=False,
                checkpoint_status="WAIVED",
            )
        return _summary_stage(
            "BLOCKED",
            "taste gate artifact is missing for a v1.2 run",
            problem_class="UNKNOWN",
            checkpoint_required=False,
            checkpoint_status="BLOCKED",
        )

    problem_class = _normalized_text(taste_gate.get("problem_class", "")).upper() or "UNKNOWN"
    checkpoint_required = bool(taste_gate.get("checkpoint_required", False))
    checkpoint_status = normalize_status(taste_gate.get("checkpoint_status"), "PENDING")
    if problem_class == "G2_CHECKABLE_EXECUTION":
        if checkpoint_required and checkpoint_status not in {"APPROVED", "WAIVED", "NOT_REQUIRED"}:
            return _summary_stage(
                "BLOCKED",
                "taste gate checkpoint is required before checkable execution may proceed",
                problem_class=problem_class,
                checkpoint_required=checkpoint_required,
                checkpoint_status=checkpoint_status,
            )
        return _summary_stage(
            "PASS",
            "",
            problem_class=problem_class,
            checkpoint_required=checkpoint_required,
            checkpoint_status=checkpoint_status,
        )
    if problem_class in {"G1_LEARNING_TASK", "G3_OPEN_RESEARCH"}:
        if checkpoint_status in {"APPROVED", "WAIVED"}:
            return _summary_stage(
                "WAIVED",
                "taste gate requires proposal-only or checkpointed handling for this problem class",
                problem_class=problem_class,
                checkpoint_required=True,
                checkpoint_status=checkpoint_status,
            )
        return _summary_stage(
            "BLOCKED",
            "taste gate blocks implementation until a human checkpoint is recorded",
            problem_class=problem_class,
            checkpoint_required=True,
            checkpoint_status=checkpoint_status,
        )
    return _summary_stage(
        "BLOCKED",
        "taste gate problem_class is missing or invalid",
        problem_class=problem_class,
        checkpoint_required=checkpoint_required,
        checkpoint_status=checkpoint_status,
    )


def _task_tree_summary(support: dict[str, Any], unsupported_transition_count: int) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "task_tree")
    task_tree = support.get("task_tree", {})
    if not isinstance(task_tree, dict) or not task_tree:
        if legacy:
            return _summary_stage(
                "WAIVED",
                "legacy run without task tree",
                task_count=0,
                skip_without_rationale_count=0,
                merge_without_rationale_count=0,
                unsupported_transition_count=unsupported_transition_count,
                task_markdown_issue_count=0,
            )
        if waiver_reason:
            return _summary_stage(
                "WAIVED",
                waiver_reason,
                task_count=0,
                skip_without_rationale_count=0,
                merge_without_rationale_count=0,
                unsupported_transition_count=unsupported_transition_count,
                task_markdown_issue_count=0,
            )
        return _summary_stage(
            "BLOCKED",
            "task tree artifact is missing for a v1.2 run",
            task_count=0,
            skip_without_rationale_count=0,
            merge_without_rationale_count=0,
            unsupported_transition_count=unsupported_transition_count,
            task_markdown_issue_count=0,
        )

    tasks = [dict(item) for item in task_tree.get("tasks", []) if isinstance(item, dict)]
    task_refs = [str(item.get("task_ref", "")).strip() for item in tasks if str(item.get("task_ref", "")).strip()]
    issues = _task_markdown_issues(task_refs, list(support.get("task_markdown_paths", [])))
    skip_without_rationale = sum(
        1 for item in tasks if str(item.get("status", "")).strip().lower() == "skipped" and not _normalized_text(item.get("rationale", ""))
    )
    merge_without_rationale = sum(
        1 for item in tasks if str(item.get("status", "")).strip().lower() == "merged" and not _normalized_text(item.get("rationale", ""))
    )
    reason_parts: list[str] = []
    if skip_without_rationale:
        reason_parts.append(f"task skip without rationale: {skip_without_rationale}")
    if merge_without_rationale:
        reason_parts.append(f"task merge without rationale: {merge_without_rationale}")
    if issues:
        reason_parts.append("; ".join(issues))
    status = "PASS"
    if not tasks or skip_without_rationale or merge_without_rationale or issues:
        status = "BLOCKED"
    return _summary_stage(
        status,
        "; ".join(reason_parts),
        task_count=len(tasks),
        skip_without_rationale_count=skip_without_rationale,
        merge_without_rationale_count=merge_without_rationale,
        unsupported_transition_count=unsupported_transition_count,
        task_markdown_issue_count=len(issues),
    )


def _evidence_manifest_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "evidence_manifest")
    manifest_path = support.get("evidence_manifest_path")
    if not manifest_path:
        if legacy:
            return _summary_stage("WAIVED", "legacy run without published evidence manifest", current=False)
        if waiver_reason:
            return _summary_stage("WAIVED", waiver_reason, current=False)
        return _summary_stage("BLOCKED", "evidence manifest is missing for a v1.2 run", current=False)
    if not bool(support.get("is_current", False)):
        return _summary_stage("BLOCKED", "published evidence manifest does not match the current head commit", current=False)
    return _summary_stage("PASS", "", current=True)


def _repeated_verify_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "repeated_verify")
    payload = support.get("repeated_verify", {})
    if not isinstance(payload, dict) or not payload:
        if legacy:
            return _summary_stage("WAIVED", "legacy run without repeated verify", round_count=0, no_new_material_findings=False, waived=True)
        if waiver_reason:
            return _summary_stage("WAIVED", waiver_reason, round_count=0, no_new_material_findings=False, waived=True)
        return _summary_stage("BLOCKED", "repeated verify artifact is missing for a v1.2 run", round_count=0, no_new_material_findings=False, waived=False)
    rounds = [dict(item) for item in payload.get("rounds", []) if isinstance(item, dict)]
    round_count = len(rounds)
    distinct_modes = {
        _normalized_text(item.get("mode", "")).casefold()
        for item in rounds
        if _normalized_text(item.get("mode", ""))
    }
    waived = bool(payload.get("waived", False)) or bool(waiver_reason)
    no_new_material_findings = bool(rounds) and int(rounds[-1].get("new_material_findings", 1)) == 0
    if waived:
        return _summary_stage(
            "WAIVED",
            _normalized_text(payload.get("waiver_reason", "")) or waiver_reason,
            round_count=round_count,
            no_new_material_findings=no_new_material_findings,
            waived=True,
            distinct_mode_count=len(distinct_modes),
        )
    if round_count < 2:
        return _summary_stage(
            "BLOCKED",
            "repeated verify requires at least 2 rounds unless waived",
            round_count=round_count,
            no_new_material_findings=no_new_material_findings,
            waived=False,
            distinct_mode_count=len(distinct_modes),
        )
    if round_count > 5:
        return _summary_stage(
            "BLOCKED",
            "repeated verify allows at most 5 rounds",
            round_count=round_count,
            no_new_material_findings=no_new_material_findings,
            waived=False,
            distinct_mode_count=len(distinct_modes),
        )
    if len(distinct_modes) < 2:
        return _summary_stage(
            "BLOCKED",
            "repeated verify requires at least 2 distinct modes unless waived",
            round_count=round_count,
            no_new_material_findings=no_new_material_findings,
            waived=False,
            distinct_mode_count=len(distinct_modes),
        )
    if not no_new_material_findings:
        return _summary_stage(
            "BLOCKED",
            "repeated verify must stop only when no new material findings remain",
            round_count=round_count,
            no_new_material_findings=False,
            waived=False,
            distinct_mode_count=len(distinct_modes),
        )
    return _summary_stage("PASS", "", round_count=round_count, no_new_material_findings=True, waived=False, distinct_mode_count=len(distinct_modes))


def _cross_verification_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "cross_verification")
    payload = support.get("cross_verification", {})
    if not isinstance(payload, dict) or not payload:
        if legacy:
            return _summary_stage("WAIVED", "legacy run without cross verification", material_claim_count=0, unresolved_disagreement_count=0, disagreement_refs=[])
        if waiver_reason:
            return _summary_stage("WAIVED", waiver_reason, material_claim_count=0, unresolved_disagreement_count=0, disagreement_refs=[])
        return _summary_stage("BLOCKED", "cross verification artifact is missing for a v1.2 run", material_claim_count=0, unresolved_disagreement_count=0, disagreement_refs=[])
    entries = [dict(item) for item in payload.get("verifiers", []) if isinstance(item, dict)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        claim_id = _normalized_text(entry.get("claim_id", ""))
        if not claim_id:
            continue
        grouped.setdefault(claim_id, []).append(entry)
    unresolved: list[str] = []
    disagreement_refs: list[str] = []
    for claim_id, claim_entries in grouped.items():
        results = {str(item.get("result", "")).strip().lower() for item in claim_entries}
        if "disagree" in results or "unable_to_verify" in results:
            unresolved.append(claim_id)
            for entry in claim_entries:
                refs = [str(item).strip() for item in entry.get("evidence_refs", []) if str(item).strip()]
                disagreement_refs.extend(refs or [claim_id])
    if unresolved:
        return _summary_stage(
            "BLOCKED",
            "cross verification contains unresolved disagreement",
            material_claim_count=len(grouped),
            unresolved_disagreement_count=len(unresolved),
            disagreement_refs=sorted(set(disagreement_refs)),
        )
    return _summary_stage(
        "PASS",
        "",
        material_claim_count=len(grouped),
        unresolved_disagreement_count=0,
        disagreement_refs=[],
    )


def _convention_lock_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "convention_lock")
    payload = support.get("convention_lock", {})
    required_terms = {"requested_credit", "credited_credit", "system_derived", "clean_room_verify", "user_review", "reviewer truth"}
    if not isinstance(payload, dict) or not payload:
        if legacy:
            return _summary_stage("WAIVED", "legacy run without convention lock", observed_drift_count=0, missing_locked_term_count=0)
        if waiver_reason:
            return _summary_stage("WAIVED", waiver_reason, observed_drift_count=0, missing_locked_term_count=0)
        return _summary_stage("BLOCKED", "convention lock artifact is missing for a v1.2 run", observed_drift_count=0, missing_locked_term_count=len(required_terms))
    locked_terms = {
        _normalized_text(item.get("term", "")).casefold()
        for item in payload.get("locked_terms", [])
        if isinstance(item, dict) and _normalized_text(item.get("term", ""))
    }
    missing_terms = [term for term in required_terms if term.casefold() not in locked_terms]
    observed_drift = [dict(item) for item in payload.get("observed_drift", []) if isinstance(item, dict)]
    status = "PASS" if not observed_drift and not missing_terms else "BLOCKED"
    reason_parts: list[str] = []
    if observed_drift:
        reason_parts.append(f"observed convention drift: {len(observed_drift)}")
    if missing_terms:
        reason_parts.append(f"missing locked terms: {', '.join(sorted(missing_terms))}")
    return _summary_stage(
        status,
        "; ".join(reason_parts),
        observed_drift_count=len(observed_drift),
        missing_locked_term_count=len(missing_terms),
    )


def _summary_coverage_summary(support: dict[str, Any]) -> dict[str, Any]:
    legacy = not _v12_contract_active(support)
    waiver_reason = _waiver_reason(support, "summary_coverage")
    coverage = support.get("summary_coverage", {})
    negative_findings_present = _summary_has_negative_findings(str(support.get("summary_text", "")))
    if isinstance(coverage, dict) and coverage:
        negative_findings_present = bool(coverage.get("negative_findings_present", False)) and negative_findings_present
        summary_claims = [dict(item) for item in coverage.get("summary_claims", []) if isinstance(item, dict)]
        uncovered_claim_count = sum(1 for item in summary_claims if str(item.get("status", "")).strip().lower() == "uncovered")
        zombie_sections = [str(item).strip() for item in coverage.get("zombie_sections", []) if str(item).strip()]
        status = "PASS" if negative_findings_present and uncovered_claim_count == 0 and not zombie_sections else "BLOCKED"
        reason_parts: list[str] = []
        if not negative_findings_present:
            reason_parts.append("summary is missing a Negative Findings section")
        if uncovered_claim_count:
            reason_parts.append(f"summary has uncovered material claims: {uncovered_claim_count}")
        if zombie_sections:
            reason_parts.append(f"summary has zombie sections: {', '.join(zombie_sections)}")
        return _summary_stage(
            status,
            "; ".join(reason_parts),
            uncovered_claim_count=uncovered_claim_count,
            zombie_section_count=len(zombie_sections),
            negative_findings_present=negative_findings_present,
        )
    if legacy:
        return _summary_stage(
            "WAIVED",
            "legacy run without summary coverage artifact",
            uncovered_claim_count=0,
            zombie_section_count=0,
            negative_findings_present=negative_findings_present,
        )
    if waiver_reason:
        return _summary_stage(
            "WAIVED",
            waiver_reason,
            uncovered_claim_count=0,
            zombie_section_count=0,
            negative_findings_present=negative_findings_present,
        )
    reason = "summary coverage artifact is missing for a v1.2 run"
    if not negative_findings_present:
        reason += "; summary is also missing a Negative Findings section"
    return _summary_stage(
        "BLOCKED",
        reason,
        uncovered_claim_count=0,
        zombie_section_count=0,
        negative_findings_present=negative_findings_present,
    )


def _v12_anti_cheat_signals(
    policy: dict[str, Any],
    support: dict[str, Any],
    *,
    task_tree: dict[str, Any],
    claim_findings: dict[str, Any],
    cross_verification: dict[str, Any],
    convention_lock: dict[str, Any],
    summary_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    signals: list[dict[str, Any]] = []

    task_tree_path = support.get("task_tree_path")
    if int(task_tree.get("skip_without_rationale_count", 0)) or int(task_tree.get("merge_without_rationale_count", 0)):
        count = int(task_tree.get("skip_without_rationale_count", 0)) + int(task_tree.get("merge_without_rationale_count", 0))
        signals.append(
            _anti_cheat_signal(
                rules,
                "task_skip_or_merge_without_rationale",
                reason=f"task tree recorded {count} skipped or merged tasks without rationale",
                evidence_refs=[str(task_tree_path)] if isinstance(task_tree_path, Path) else [],
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=str(task_tree_path) if isinstance(task_tree_path, Path) else ""),
            )
        )

    if int(claim_findings.get("unsupported_transition_count", 0)):
        refs = [str(item) for item in claim_findings.get("unsupported_transition_refs", []) if str(item).strip()]
        signals.append(
            _anti_cheat_signal(
                rules,
                "unsupported_transition_claim",
                reason="transition language such as therefore or consistent with was used without linked evidence",
                evidence_refs=refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=refs[0] if refs else str(support.get("claim_ledger_path", ""))),
            )
        )

    if int(claim_findings.get("verification_word_without_artifact_count", 0)):
        refs = [str(item) for item in claim_findings.get("verification_word_without_artifact_refs", []) if str(item).strip()]
        signals.append(
            _anti_cheat_signal(
                rules,
                "verification_word_without_artifact",
                reason="verification language was used without a fresh command, report, or test artifact",
                evidence_refs=refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=refs[0] if refs else str(support.get("claim_ledger_path", ""))),
            )
        )

    if int(convention_lock.get("observed_drift_count", 0)) or int(convention_lock.get("missing_locked_term_count", 0)):
        lock_path = support.get("convention_lock_path")
        signals.append(
            _anti_cheat_signal(
                rules,
                "convention_drift",
                reason=str(convention_lock.get("reason", "")).strip() or "convention lock drift was recorded",
                evidence_refs=[str(lock_path)] if isinstance(lock_path, Path) else [],
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=str(lock_path) if isinstance(lock_path, Path) else ""),
            )
        )

    if int(summary_coverage.get("uncovered_claim_count", 0)) or int(summary_coverage.get("zombie_section_count", 0)) or int(claim_findings.get("stale_claim_count", 0)):
        refs = [str(item) for item in claim_findings.get("stale_claim_refs", []) if str(item).strip()]
        coverage_path = support.get("summary_coverage_path")
        signals.append(
            _anti_cheat_signal(
                rules,
                "zombie_section_or_stale_claim",
                reason=str(summary_coverage.get("reason", "")).strip() or "summary coverage recorded uncovered claims, zombie sections, or stale claims",
                evidence_refs=refs or ([str(coverage_path)] if isinstance(coverage_path, Path) else []),
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=str(coverage_path) if isinstance(coverage_path, Path) else ""),
            )
        )

    if int(cross_verification.get("unresolved_disagreement_count", 0)):
        refs = [str(item) for item in cross_verification.get("disagreement_refs", []) if str(item).strip()]
        cross_path = support.get("cross_verification_path")
        signals.append(
            _anti_cheat_signal(
                rules,
                "cross_verification_disagreement_unresolved",
                reason="cross verification contains unresolved disagreement",
                evidence_refs=refs or ([str(cross_path)] if isinstance(cross_path, Path) else []),
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=_build_signal_provenance(support, source_path=str(cross_path) if isinstance(cross_path, Path) else ""),
            )
        )

    if not bool(summary_coverage.get("negative_findings_present", False)):
        negative_pressure = bool(_waiver_entries(support)) or int(cross_verification.get("unresolved_disagreement_count", 0)) > 0 or int(summary_coverage.get("uncovered_claim_count", 0)) > 0
        if negative_pressure:
            summary_path = support.get("summary_path")
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "aesthetic_or_report_smoothing",
                    reason="summary omitted a Negative Findings section despite waivers, disagreements, or uncovered claims",
                    evidence_refs=[str(summary_path)] if isinstance(summary_path, Path) else [],
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support, source_path=str(summary_path) if isinstance(summary_path, Path) else ""),
                )
            )
    return signals


def _public_anti_cheat_signal(signal: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = [str(ref) for ref in signal.get("evidence_refs", []) if str(ref).strip()]
    return {
        "code": str(signal.get("code", signal.get("id", ""))).strip(),
        "severity": str(signal.get("severity", "medium")).strip() or "medium",
        "confidence": str(signal.get("confidence", "medium")).strip() or "medium",
        "decision": str(signal.get("decision", "warn")).strip() or "warn",
        "detected_by": str(signal.get("detected_by", "compute_user_scorecard.py")).strip() or "compute_user_scorecard.py",
        "provenance": dict(signal.get("provenance", {})),
        "points": int(signal.get("points", 0)),
        "reason": str(signal.get("reason", "")).strip(),
        "evidence_ref": evidence_refs[0] if evidence_refs else "",
    }


def _finalize_anti_cheat_signal(policy: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    code = str(signal.get("code", signal.get("id", ""))).strip()
    confidence = str(signal.get("confidence", "medium")).strip().lower() or "medium"
    severity = str(signal.get("severity", "medium")).strip().lower() or "medium"
    disqualifier_id = str(signal.get("disqualifier_id", "")).strip()
    auto_dq_codes = set(policy.get("anti_cheat_layer", {}).get("decision_policy", {}).get("auto_dq_codes", AUTO_DQ_DEFAULT_CODES))

    decision = str(signal.get("decision", "")).strip().lower()
    if not decision:
        if confidence != "high":
            decision = "warn"
        elif severity == "medium":
            decision = "penalty"
        elif severity == "high":
            decision = "cap"
        elif severity == "critical" and disqualifier_id and code in auto_dq_codes:
            decision = "dq"
        elif severity == "critical":
            decision = "cap"
        else:
            decision = "warn"
    return {
        **signal,
        "confidence": confidence,
        "decision": decision,
        "detected_by": str(signal.get("detected_by", "compute_user_scorecard.py")).strip() or "compute_user_scorecard.py",
        "provenance": dict(signal.get("provenance", {})),
    }


def _decision_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}
    highest = "warn"
    auto_dq_signals: list[str] = []
    for signal in signals:
        decision = str(signal.get("decision", "warn")).strip().lower() or "warn"
        if decision not in counts:
            decision = "warn"
        counts[decision] += 1
        if DECISION_ORDER[decision] > DECISION_ORDER[highest]:
            highest = decision
        if decision == "dq":
            auto_dq_signals.append(str(signal.get("code", signal.get("id", ""))).strip())
    return {
        "highest_decision": highest,
        "counts": counts,
        "auto_dq_signals": auto_dq_signals,
    }


def _load_stage_payload(raw_stage: dict[str, Any], report_path_raw: str, workspace_root: Path | None) -> dict[str, Any]:
    report_path = resolve_path(report_path_raw, workspace_root)
    stage = dict(raw_stage)
    report_present = False
    if report_path is not None and report_path.exists():
        external = load_json(report_path)
        if isinstance(external, dict):
            stage = {**stage, **external}
        stage["report_path"] = str(report_path)
        report_present = True
    elif report_path is not None:
        stage["report_path"] = str(report_path)
    stage["status"] = normalize_status(stage.get("status"), "UNKNOWN")
    stage["manual_close_out"] = list(stage.get("manual_close_out", []))
    stage["evidence_refs"] = list(stage.get("evidence_refs", []))
    stage["report_present"] = report_present
    return stage


def _load_trace_payload(review: dict[str, Any], workspace_root: Path | None) -> dict[str, Any]:
    trace = dict(review.get("trace", {}))
    report_path = resolve_path(review.get("evidence_inputs", {}).get("trace_report_path", ""), workspace_root)
    if report_path is not None and report_path.exists():
        external = load_json(report_path)
        if isinstance(external, dict):
            trace = {**trace, **external}
        trace["report_path"] = str(report_path)
    elif report_path is not None:
        trace["report_path"] = str(report_path)
    trace["required"] = bool(trace.get("required", True))
    trace["status"] = normalize_status(trace.get("status"), "UNKNOWN")
    trace["present"] = bool(trace.get("report_path")) or bool(trace.get("evidence_refs"))
    trace["evidence_refs"] = list(trace.get("evidence_refs", []))
    return trace


def _role_required(role_policy: dict[str, Any], context: dict[str, Any], mode: str) -> bool:
    required_modes = role_policy.get("required_modes", [])
    if required_modes and mode not in required_modes:
        return False
    if any(_bool_flag(context, flag) for flag in role_policy.get("required_when_any", [])):
        return True
    if role_policy.get("required_by_default", False):
        return not any(_bool_flag(context, flag) for flag in role_policy.get("required_unless", []))
    return False


def _axis_applicable(axis_policy: dict[str, Any], context: dict[str, Any]) -> bool:
    if axis_policy.get("applicable_when") == "always":
        return True
    flags = axis_policy.get("applicable_when_any", [])
    return any(_bool_flag(context, flag) for flag in flags)


def _caps_for_context(policy: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for cap in policy.get("caps", []):
        required = cap.get("when_all", {})
        if all(bool(context.get(key, False)) == bool(value) for key, value in required.items()):
            active.append(cap)
    return active


def _derived_awards_for_axis(
    axis_name: str,
    axis_policy: dict[str, Any],
    context: dict[str, Any],
    *,
    evidence_manifest_ok: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    awards: list[dict[str, Any]] = []
    errors: list[str] = []
    if not evidence_manifest_ok:
        return awards, errors
    for award in axis_policy.get("derived_awards", []):
        required = award.get("when_all", {})
        if not all(bool(context.get(key, False)) == bool(value) for key, value in required.items()):
            continue
        try:
            points = int(award.get("points", 0))
        except (TypeError, ValueError):
            errors.append(f"invalid derived award points for axis '{axis_name}'")
            continue
        if points <= 0:
            errors.append(f"derived award points must be positive for axis '{axis_name}'")
            continue
        reason = str(award.get("reason", "")).strip()
        if not reason:
            errors.append(f"derived award reason is required for axis '{axis_name}'")
            continue
        awards.append(
            {
                "axis": axis_name,
                "award_id": str(award.get("id", "")).strip(),
                "points": points,
                "requested_points": points,
                "credited_points": points,
                "reason": reason,
                "category": str(award.get("category", "")).strip() or "verified_work",
                "evidence_refs": list(award.get("evidence_refs", [])),
                "reported_by": str(award.get("source", "")).strip() or "system_derived",
                "source": str(award.get("source", "")).strip() or "system_derived",
                "credit_block_reason": "",
            }
        )
    return awards, errors


def _apply_clean_room_credit_metadata(awards: list[dict[str, Any]], clean_room_verify: dict[str, Any]) -> list[dict[str, Any]]:
    status = normalize_status(clean_room_verify.get("status"), "UNKNOWN")
    report_path = str(clean_room_verify.get("report_path", "")).strip()
    report_present = bool(clean_room_verify.get("report_present", False))
    evidence_refs: list[str] = []
    if report_present and report_path:
        evidence_refs.append(report_path)
    for ref in clean_room_verify.get("evidence_refs", []):
        text = str(ref).strip()
        if text and text not in evidence_refs:
            evidence_refs.append(text)

    updated: list[dict[str, Any]] = []
    for award in awards:
        entry = dict(award)
        if str(entry.get("source", "")).strip() != "clean_room_verify":
            updated.append(entry)
            continue
        entry["reserved"] = True
        entry["credit_status"] = status
        entry["reason"] = f"reserved completion credit generated from clean_room_verify {status} evidence"
        if evidence_refs:
            entry["evidence_refs"] = evidence_refs
        updated.append(entry)
    return updated


def _materialize_caps(active_caps: list[dict[str, Any]], total_floor: int) -> list[dict[str, Any]]:
    materialized: list[dict[str, Any]] = []
    for cap in active_caps:
        entry = dict(cap)
        limits: list[int] = []
        if "max_total_score" in entry:
            limits.append(int(entry["max_total_score"]))
        if "target_score_multiplier" in entry:
            multiplier_limit = int(total_floor * float(entry["target_score_multiplier"]))
            entry["computed_max_total_score"] = multiplier_limit
            limits.append(multiplier_limit)
        if limits:
            entry["effective_max_total_score"] = min(limits)
        materialized.append(entry)
    return materialized


def _advisories_for_context(policy: dict[str, Any], context: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for item in policy.get("advisories", []):
        required = item.get("when_all", {})
        if all(bool(context.get(key, False)) == bool(value) for key, value in required.items()):
            messages.append(str(item.get("message", "")).strip())
    return [message for message in messages if message]


def _normalize_penalty(penalty: dict[str, Any], source: str, allowed_axes: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    axis = str(penalty.get("axis", "")).strip()
    if axis not in allowed_axes:
        return None, f"unknown axis '{axis or '<missing>'}' from {source}"
    try:
        points = int(penalty.get("points", 0))
    except (TypeError, ValueError):
        return None, f"invalid penalty points for axis '{axis}' from {source}"
    if points <= 0:
        return None, f"penalty points must be positive for axis '{axis}' from {source}"
    reported_by = str(penalty.get("reported_by", source)).strip().lower()
    if reported_by in {"writer", "main_writer", "actor"}:
        return None, f"writer self-scoring is forbidden for axis '{axis}'"
    normalized = {
        "axis": axis,
        "points": points,
        "reason": str(penalty.get("reason", "")).strip() or "deduction recorded",
        "evidence_refs": list(penalty.get("evidence_refs", [])),
        "reported_by": reported_by or source,
    }
    return normalized, None


def _normalize_award(award: dict[str, Any], source: str, allowed_axes: set[str]) -> tuple[dict[str, Any] | None, str | None]:
    axis = str(award.get("axis", "")).strip()
    if axis not in allowed_axes:
        return None, f"unknown axis '{axis or '<missing>'}' from {source}"
    try:
        points = int(award.get("points", 0))
    except (TypeError, ValueError):
        return None, f"invalid award points for axis '{axis}' from {source}"
    if points <= 0:
        return None, f"award points must be positive for axis '{axis}' from {source}"
    reported_by = str(award.get("reported_by", source)).strip().lower()
    reason = str(award.get("reason", "")).strip()
    if not reason:
        return None, f"award reason is required for axis '{axis}' from {source}"
    normalized = {
        "axis": axis,
        "points": points,
        "reason": reason,
        "category": str(award.get("category", "")).strip() or "problem_resolution",
        "evidence_refs": list(award.get("evidence_refs", [])),
        "reported_by": reported_by or source,
    }
    return normalized, None


def _load_authority_audit(review: dict[str, Any], workspace_root: Path | None) -> dict[str, Any]:
    audit_path = resolve_path(review.get("authority_audit_path", ""), workspace_root)
    if audit_path is None:
        return {}
    return load_json(audit_path)


def _load_context(review: dict[str, Any], workspace_root: Path | None) -> tuple[dict[str, Any], Path | None]:
    context_path = resolve_path(review.get("authoritative_context_path", ""), workspace_root)
    if context_path is None or not context_path.exists():
        return dict(review), None
    payload = load_json(context_path)
    if "disqualifiers" in review:
        payload["disqualifiers"] = list(review.get("disqualifiers", []))
    if "run_id" in review:
        payload["run_id"] = str(review.get("run_id", "")).strip()
    payload["authority_audit_path"] = str(resolve_path(review.get("authority_audit_path", ""), workspace_root) or "")
    return payload, context_path


def _empty_reviewers() -> dict[str, dict[str, Any]]:
    return {role: {"status": "PENDING", "green": False, "penalties": [], "notes": ""} for role in REVIEWER_ROLES}


def _validate_reviewer_entry(
    entry: dict[str, Any],
    *,
    role: str,
    context_path: Path,
    workspace_root: Path,
    trace_id: str,
    current_git_sha: str,
    current_worktree_id: str,
    current_project_id: str,
) -> str:
    signature = str(entry.get("signature", "")).strip()
    if not signature:
        return "missing signature"
    if not verify_truth_signature(strip_signature(entry), signature):
        return "signature mismatch"
    if str(entry.get("role", "")).strip() != role:
        return f"role mismatch: expected {role}"
    if str(entry.get("producer_lane", "")).strip() != role:
        return f"producer_lane mismatch: expected {role}"
    if str(entry.get("repo_root", "")).strip() != str(workspace_root):
        return f"repo_root mismatch: expected {workspace_root}"
    if str(entry.get("trace_id", "")).strip() != trace_id:
        return f"trace_id mismatch: expected {trace_id}"
    if str(entry.get("git_sha", "")).strip() != current_git_sha:
        return f"git_sha mismatch: expected {current_git_sha}"
    if str(entry.get("worktree_id", "")).strip() != current_worktree_id:
        return f"worktree_id mismatch: expected {current_worktree_id}"
    if str(entry.get("codex_project_id", "")).strip() != current_project_id:
        return f"codex_project_id mismatch: expected {current_project_id}"
    if str(entry.get("input_report_hash", "")).strip() != file_hash(context_path):
        return "input_report_hash mismatch"
    return ""


def _load_authoritative_reviewers(review: dict[str, Any], workspace_root: Path | None, context_path: Path | None) -> tuple[dict[str, Any], list[str]]:
    reviewers = _empty_reviewers()
    if workspace_root is None or context_path is None:
        return reviewers, []

    trace_id = str(review.get("trace_id", "")).strip()
    current_git_sha = str(review.get("git_sha", "")).strip() or git_sha(workspace_root)
    current_worktree_id = str(review.get("worktree_id", "")).strip() or worktree_id(workspace_root)
    current_project_id = str(review.get("codex_project_id", "")).strip() or project_id(workspace_root)
    verdict_root = reviewer_verdict_dir(workspace_root, trace_id)
    errors: list[str] = []
    for role in REVIEWER_ROLES:
        valid_entry: dict[str, Any] | None = None
        for entry in load_jsonl(verdict_root / f"{role}.jsonl"):
            reason = _validate_reviewer_entry(
                entry,
                role=role,
                context_path=context_path,
                workspace_root=workspace_root,
                trace_id=trace_id,
                current_git_sha=current_git_sha,
                current_worktree_id=current_worktree_id,
                current_project_id=current_project_id,
            )
            if reason:
                continue
            valid_entry = entry
        if valid_entry is None:
            continue
        reviewers[role] = {
            "status": normalize_status(valid_entry.get("status"), "PENDING"),
            "green": bool(valid_entry.get("green", False)),
            "penalties": list(valid_entry.get("penalties", [])),
            "notes": str(valid_entry.get("notes", "")).strip(),
        }
    audit = _load_authority_audit(review, workspace_root)
    for event in audit.get("tamper_events", []):
        errors.append(str(event.get("reason", "")).strip() or "authority tamper detected")
    return reviewers, [item for item in errors if item]


def _disqualifier_rules() -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id", "")).strip(): item
        for item in load_json(DEFAULT_DISQUALIFIER_FILE).get("rules", [])
        if str(item.get("id", "")).strip()
    }


def _append_disqualifier_matches(
    result: dict[str, Any],
    rules: dict[str, dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    updated = {
        **result,
        "matched_rules": list(result.get("matched_rules", [])),
        "unknown_ids": list(result.get("unknown_ids", [])),
        "reasons": list(result.get("reasons", [])),
    }
    if updated["reasons"] == ["no disqualifiers recorded"]:
        updated["reasons"] = []
    seen = {
        (str(item.get("id", "")).strip(), str(item.get("reason", "")).strip())
        for item in updated["matched_rules"]
        if isinstance(item, dict)
    }
    for entry in entries:
        rule_id = str(entry.get("id", "")).strip()
        if not rule_id:
            continue
        if rule_id not in rules:
            updated["unknown_ids"].append(rule_id)
            continue
        reason = str(entry.get("reason", "")).strip() or str(rules[rule_id].get("description", "")).strip()
        token = (rule_id, reason)
        if token in seen:
            continue
        seen.add(token)
        rule = rules[rule_id]
        outcome = normalize_status(rule.get("outcome"), "FAIL")
        if outcome == "SECURITY_INCIDENT":
            updated["status"] = "SECURITY_INCIDENT"
        elif updated["status"] == "PASS":
            updated["status"] = "FAIL"
        updated["matched_rules"].append(
            {
                "id": rule_id,
                "title": rule.get("title", ""),
                "outcome": outcome,
                "reason": reason,
                "evidence_refs": list(entry.get("evidence_refs", [])),
            }
        )
        updated["reasons"].append(reason)
    if not updated["reasons"] and updated["status"] == "PASS":
        updated["reasons"].append("no disqualifiers recorded")
    return updated


def _anti_cheat_rules(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id", "")).strip(): item
        for item in policy.get("anti_cheat_layer", {}).get("signal_rules", [])
        if str(item.get("id", "")).strip()
    }


def _anti_cheat_signal(
    rules: dict[str, dict[str, Any]],
    signal_id: str,
    *,
    reason: str = "",
    evidence_refs: list[str] | None = None,
    details: dict[str, Any] | None = None,
    confidence: str = "",
    decision: str = "",
    detected_by: str = "",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    code = LEGACY_SIGNAL_CODE_ALIASES.get(signal_id, signal_id)
    rule = rules.get(code, {})
    refs = [str(ref) for ref in (evidence_refs or []) if str(ref).strip()]
    return {
        "id": code,
        "code": code,
        "points": int(rule.get("points", 0)),
        "severity": str(rule.get("severity", "medium")).strip() or "medium",
        "reason": reason or str(rule.get("reason", "")).strip() or code,
        "disqualifier_id": str(rule.get("disqualifier_id", "")).strip(),
        "evidence_refs": refs,
        "evidence_ref": refs[0] if refs else "",
        "details": dict(details or {}),
        "confidence": confidence or str(rule.get("confidence", "high")).strip() or "high",
        "decision": decision or str(rule.get("decision", "")).strip().lower(),
        "detected_by": detected_by or "compute_user_scorecard.py",
        "provenance": dict(provenance or {}),
    }


def _audit_anti_cheat_signals(policy: dict[str, Any], audit: dict[str, Any], support: dict[str, Any]) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    signals: list[dict[str, Any]] = []
    for event in audit.get("tamper_events", []):
        if not isinstance(event, dict):
            continue
        category = str(event.get("category", "")).strip()
        evidence_refs = [str(ref) for ref in event.get("evidence_refs", []) if str(ref).strip()]
        provenance = _build_signal_provenance(
            support,
            source_path=str(event.get("path", "")).strip(),
            fallback_path=str(audit.get("workspace_audit_path", "")).strip(),
        )
        if category in {"unauthorized_user_review_update", "unauthorized_user_review_modification"}:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "unauthorized_user_review_modification",
                    reason=str(event.get("reason", "")).strip(),
                    evidence_refs=evidence_refs,
                    details={"category": category, "path": str(event.get("path", "")).strip()},
                    confidence="high",
                    detected_by="prepare_user_scorecard_review.py",
                    provenance=provenance,
                )
            )
        elif category in {"reviewer_truth", "reviewer_truth_tamper"}:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "reviewer_truth_tamper",
                    reason=str(event.get("reason", "")).strip(),
                    evidence_refs=evidence_refs,
                    details={"category": category, "path": str(event.get("path", "")).strip()},
                    confidence="high",
                    detected_by="prepare_user_scorecard_review.py",
                    provenance=provenance,
                )
            )
        elif category in rules:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    category,
                    reason=str(event.get("reason", "")).strip(),
                    evidence_refs=evidence_refs,
                    details={"category": category, "path": str(event.get("path", "")).strip()},
                    confidence=str(event.get("confidence", "high")).strip() or "high",
                    detected_by=str(event.get("detected_by", "prepare_user_scorecard_review.py")).strip() or "prepare_user_scorecard_review.py",
                    provenance=provenance,
                )
            )
    return signals


def _raw_user_review_score_signals(policy: dict[str, Any], authority_review: dict[str, Any], support: dict[str, Any]) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    signals: list[dict[str, Any]] = []
    user_review = authority_review.get("user_review", {})
    if not isinstance(user_review, dict):
        return signals
    for section in ("awards", "penalties"):
        for item in user_review.get(section, []):
            if not isinstance(item, dict):
                continue
            reported_by = str(item.get("reported_by", "")).strip().lower()
            if _is_writer_or_agent_reporter(reported_by):
                signals.append(
                    _anti_cheat_signal(
                        rules,
                        "writer_self_score_attempt",
                        reason=f"writer or agent attempted to write user_review.{section}",
                        evidence_refs=[str(authority_review.get("authoritative_context_path", "")).strip()],
                        details={"section": section, "axis": str(item.get("axis", "")).strip()},
                        confidence="high",
                        detected_by="compute_user_scorecard.py",
                        provenance=_build_signal_provenance(
                            support,
                            source_path=str(authority_review.get("authoritative_context_path", "")).strip(),
                        ),
                    )
                )
    return signals


def _normalized_reviewer_snapshot(entry: dict[str, Any] | None) -> dict[str, Any]:
    payload = entry if isinstance(entry, dict) else {}
    return {
        "status": normalize_status(payload.get("status"), "PENDING"),
        "green": bool(payload.get("green", False)),
        "penalties": list(payload.get("penalties", [])),
        "notes": str(payload.get("notes", "")).strip(),
    }


def _protected_review_input_signals(
    policy: dict[str, Any],
    review: dict[str, Any],
    authority_review: dict[str, Any],
    authoritative_reviewers: dict[str, Any],
    *,
    context_present: bool,
    support: dict[str, Any],
) -> list[dict[str, Any]]:
    if not context_present:
        return []

    rules = _anti_cheat_rules(policy)
    signals: list[dict[str, Any]] = []
    context_path = str(authority_review.get("authoritative_context_path", "")).strip()

    if "user_review" in review:
        authoritative_user_review = normalize_user_review(authority_review.get("user_review", {}))
        snapshot_user_review = normalize_user_review(review.get("user_review", {}))
        if snapshot_user_review != authoritative_user_review:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "unauthorized_user_review_modification",
                    reason="review snapshot tried to override the authoritative approved user-review data",
                    evidence_refs=[context_path] if context_path else [],
                    details={"section": "user_review"},
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support, source_path=context_path),
                )
            )

    snapshot_reviewers = review.get("reviewers", {})
    if isinstance(snapshot_reviewers, dict):
        for role in REVIEWER_ROLES:
            if role not in snapshot_reviewers:
                continue
            if _normalized_reviewer_snapshot(snapshot_reviewers.get(role)) != _normalized_reviewer_snapshot(authoritative_reviewers.get(role)):
                signals.append(
                    _anti_cheat_signal(
                        rules,
                        "reviewer_truth_tamper",
                        reason=f"review snapshot reviewer '{role}' does not match reviewer truth",
                        evidence_refs=[context_path] if context_path else [],
                        details={"role": role},
                        confidence="high",
                        detected_by="compute_user_scorecard.py",
                        provenance=_build_signal_provenance(support, source_path=context_path),
                    )
                )
    return signals


def _credit_input_spoof_signals(policy: dict[str, Any], review: dict[str, Any], support: dict[str, Any]) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    source_path = str(review.get("authoritative_context_path", "")).strip()
    evidence_refs = [source_path] if source_path else []
    provenance = _build_signal_provenance(support, source_path=source_path)
    signals: list[dict[str, Any]] = []

    for field in ENGINE_OWNED_CREDIT_INPUT_FIELDS:
        raw_entries = review.get(field, [])
        if not isinstance(raw_entries, list) or not raw_entries:
            continue
        spoof_entries: list[dict[str, Any]] = []
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            spoof_entries.append(
                {
                    "axis": str(item.get("axis", "")).strip(),
                    "source": str(item.get("source", "")).strip(),
                    "requested_points": int(item.get("requested_points", item.get("points", 0)) or 0),
                    "credited_points": int(item.get("credited_points", item.get("points", 0)) or 0),
                }
            )
        signals.append(
            _anti_cheat_signal(
                rules,
                "reserved_derived_award_spoofing",
                reason=f"review payload tried to inject engine-owned {field} entries",
                evidence_refs=evidence_refs,
                details={"field": field, "entries": spoof_entries},
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=provenance,
            )
        )
    return signals


def _manifest_anti_cheat_signals(
    policy: dict[str, Any],
    support: dict[str, Any],
    *,
    mode: str,
    existing_readiness: dict[str, Any],
    clean_room_verify: dict[str, Any],
) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    manifest = dict(support.get("evidence_manifest", {}))
    workorder = dict(support.get("workorder", {}))
    manifest_path = support.get("evidence_manifest_path")
    evidence_refs = [str(manifest_path)] if isinstance(manifest_path, Path) else []
    provenance = _build_signal_provenance(
        support,
        fallback_path=str(manifest_path) if isinstance(manifest_path, Path) else "",
    )
    signals: list[dict[str, Any]] = []

    verify_claimed = normalize_status(existing_readiness.get("status"), "UNKNOWN") in {"PASS", "WAIVED"} or normalize_status(clean_room_verify.get("status"), "UNKNOWN") in {"PASS", "WAIVED"}
    if mode in {"verify", "release"} and verify_claimed and not bool(support.get("is_current", False)):
        signals.append(
            _anti_cheat_signal(
                rules,
                "evidence_backdating_or_stale_report_reuse",
                reason="verification evidence manifest does not match the current head commit",
                evidence_refs=evidence_refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=provenance,
            )
        )

    for waiver in manifest.get("waivers", []):
        if not isinstance(waiver, dict):
            continue
        if str(waiver.get("reason", "")).strip() or str(waiver.get("reason_code", "")).strip():
            continue
        signals.append(
            _anti_cheat_signal(
                rules,
                "waiver_without_reason",
                reason=f"waiver '{str(waiver.get('id', '')).strip() or 'unknown'}' is missing a reason",
                evidence_refs=evidence_refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=provenance,
            )
        )

    current_hashes = current_policy_hashes()
    manifest_hashes = dict(manifest.get("policy_hashes", {}).get("current", {}))
    mismatched_hashes = [name for name, digest in current_hashes.items() if manifest_hashes.get(name) and manifest_hashes.get(name) != digest]
    if mismatched_hashes:
        signals.append(
            _anti_cheat_signal(
                rules,
                "evidence_manifest_mismatch",
                reason=f"policy hashes differ from the published evidence manifest: {', '.join(sorted(mismatched_hashes))}",
                evidence_refs=evidence_refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=provenance,
            )
        )

    protected_markers = [str(item).strip() for item in workorder.get("protected_paths", []) if str(item).strip()]
    protected_markers.extend(["user_review.approved.json", "reviewer_verdict.log", "/reviewer-verdicts/"])
    changed_files = [str(item).strip() for item in manifest.get("changed_files", []) if str(item).strip()]
    confirmed_protected_writes = [path for path in changed_files if any(marker in path for marker in protected_markers)]
    if confirmed_protected_writes:
        signals.append(
            _anti_cheat_signal(
                rules,
                "protected_path_access_attempt",
                reason=f"published changed_files include protected authority surfaces: {', '.join(sorted(set(confirmed_protected_writes)))}",
                evidence_refs=evidence_refs,
                confidence="high",
                detected_by="compute_user_scorecard.py",
                provenance=provenance,
            )
        )
    else:
        command_texts = [
            str(entry.get("cmd", "")).strip()
            for entry in [*manifest.get("commands", []), *support.get("command_log", [])]
            if isinstance(entry, dict)
        ]
        command_hits = [cmd for cmd in command_texts if any(marker in cmd for marker in protected_markers)]
        if command_hits:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "protected_path_access_attempt",
                    reason="command log referenced a protected authority surface without a confirmed write artifact",
                    evidence_refs=evidence_refs,
                    confidence="low",
                    detected_by="compute_user_scorecard.py",
                    provenance=provenance,
                )
            )

    verification_commands = [str(item).strip() for item in workorder.get("verification_commands", []) if str(item).strip()]
    observed_commands = [
        str(entry.get("cmd", "")).strip()
        for entry in [*manifest.get("commands", []), *support.get("command_log", [])]
        if isinstance(entry, dict) and str(entry.get("cmd", "")).strip()
    ]
    if verification_commands and observed_commands:
        missing = [cmd for cmd in verification_commands if not any(cmd in observed or observed in cmd for observed in observed_commands)]
        if missing:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "verification_command_substitution",
                    reason=f"required verification commands were not observed in the evidence manifest: {', '.join(missing)}",
                    evidence_refs=evidence_refs,
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=provenance,
                )
            )

    return signals


def _credit_user_awards(
    policy: dict[str, Any],
    user_awards: list[dict[str, Any]],
    *,
    evidence_manifest_ok: bool,
    support: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    anti_cheat = policy.get("anti_cheat_layer", {})
    rules = _anti_cheat_rules(policy)
    budgets = {
        str(axis).strip(): int(points)
        for axis, points in anti_cheat.get("per_axis_user_award_budgets", {}).items()
        if str(axis).strip()
    }
    reserved_sources = set(ENGINE_OWNED_CREDIT_SOURCES)
    reserved_categories = {
        str(item).strip()
        for item in anti_cheat.get("reserved_award_categories", [])
        if str(item).strip()
    }
    signals: list[dict[str, Any]] = []
    scored_awards: list[dict[str, Any]] = []
    requested_credit: list[dict[str, Any]] = []
    pending_by_axis: dict[str, list[dict[str, Any]]] = {}

    for award in user_awards:
        entry = dict(award)
        requested_points = int(entry.get("points", 0))
        entry["requested_points"] = requested_points
        entry["credited_points"] = 0
        entry["credit_block_reason"] = ""
        category = str(entry.get("category", "")).strip()
        reported_by = str(entry.get("reported_by", "")).strip().lower()
        entry["source"] = _normalized_credit_source(reported_by)
        scored_awards.append(entry)
        requested_credit.append(
            _requested_credit_entry(
                entry["axis"],
                requested_points,
                entry["source"],
                str(entry.get("reason", "")).strip(),
                [str(ref) for ref in entry.get("evidence_refs", []) if str(ref).strip()],
            )
        )

        if category in reserved_categories:
            entry["credit_block_reason"] = "reserved_award_category"
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "reserved_derived_award_spoofing",
                    reason=f"user award tried to use reserved category '{category}' on axis '{entry['axis']}'",
                    evidence_refs=[str(ref) for ref in entry.get("evidence_refs", []) if str(ref).strip()],
                    details={"axis": entry["axis"], "category": category},
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support),
                )
            )
            continue
        if entry["source"] in reserved_sources:
            entry["credit_block_reason"] = "reserved_credit_source"
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "reserved_derived_award_spoofing",
                    reason=f"user award tried to use reserved credit source '{entry['source']}' on axis '{entry['axis']}'",
                    evidence_refs=[str(ref) for ref in entry.get("evidence_refs", []) if str(ref).strip()],
                    details={"axis": entry["axis"], "source": entry["source"]},
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support),
                )
            )
            continue
        if not evidence_manifest_ok:
            entry["credit_block_reason"] = "missing_or_stale_evidence_manifest"
            continue
        if entry["source"] != "user_approved_review":
            entry["credit_block_reason"] = "requested_only_source" if entry["source"] == "agent_request" else "non_user_source_award"
            if entry["source"] != "agent_request" or not _is_writer_or_agent_reporter(reported_by):
                signals.append(
                    _anti_cheat_signal(
                        rules,
                        "non_user_source_award",
                        reason=f"user award for axis '{entry['axis']}' came from non-user source '{reported_by or 'unknown'}'",
                        evidence_refs=[str(ref) for ref in entry.get("evidence_refs", []) if str(ref).strip()],
                        details={"axis": entry["axis"], "reported_by": reported_by or "unknown"},
                        confidence="high",
                        detected_by="compute_user_scorecard.py",
                        provenance=_build_signal_provenance(support),
                    )
                )
            continue
        pending_by_axis.setdefault(entry["axis"], []).append(entry)

    for axis, items in pending_by_axis.items():
        budget = int(budgets.get(axis, 0))
        requested_total = sum(int(item.get("requested_points", 0)) for item in items)
        if budget <= 0:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "excessive_bonus_request",
                    reason=f"user awards on axis '{axis}' are not allowed by the anti-cheat budget",
                    details={"axis": axis, "requested_points": requested_total, "budget": budget},
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support),
                )
            )
            for item in items:
                item["credit_block_reason"] = "axis_not_awardable"
            continue

        remaining = budget
        for item in items:
            requested_points = int(item.get("requested_points", 0))
            credited = min(requested_points, max(remaining, 0))
            item["credited_points"] = credited
            if credited < requested_points:
                item["credit_block_reason"] = "budget_exhausted"
            remaining -= credited

        if requested_total > budget:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "excessive_bonus_request",
                    reason=f"user awards on axis '{axis}' requested {requested_total} points above budget {budget}",
                    details={"axis": axis, "requested_points": requested_total, "budget": budget, "excess_points": requested_total - budget},
                    confidence="high",
                    detected_by="compute_user_scorecard.py",
                    provenance=_build_signal_provenance(support),
                )
            )

    credited_credit = [_credited_credit_entry(entry) for entry in scored_awards]
    return scored_awards, requested_credit, credited_credit, signals


def _anti_cheat_caps(policy: dict[str, Any], signal_points: int) -> list[dict[str, Any]]:
    caps: list[dict[str, Any]] = []
    for tier in policy.get("anti_cheat_layer", {}).get("cap_tiers", []):
        try:
            min_points = int(tier.get("min_points", 0))
            max_total_score = int(tier.get("max_total_score", 0))
        except (TypeError, ValueError):
            continue
        if signal_points < min_points:
            continue
        caps.append(
            {
                "id": f"anti_cheat_guard_{min_points}",
                "max_total_score": max_total_score,
                "effective_max_total_score": max_total_score,
                "reason": str(tier.get("reason", "")).strip() or "anti-cheat guard cap applied",
            }
        )
    return caps


def compute_scorecard(policy: dict[str, Any], review: dict[str, Any], mode: str) -> dict[str, Any]:
    snapshot_workspace_root = resolve_path(review.get("workspace_root", "")) if str(review.get("workspace_root", "")).strip() else None
    authority_review, context_path = _load_context(review, snapshot_workspace_root)
    context = dict(authority_review.get("task_context", {}))
    workspace_root = resolve_path(authority_review.get("workspace_root", "")) if str(authority_review.get("workspace_root", "")).strip() else snapshot_workspace_root
    support = _load_support_artifacts(authority_review, workspace_root)
    authority_audit = _load_authority_audit(authority_review, workspace_root)
    disqualifier_policy = load_json(DEFAULT_DISQUALIFIER_FILE)
    disqualifier_result = evaluate_disqualifiers(disqualifier_policy, authority_review)
    trace = _load_trace_payload(authority_review, workspace_root)
    trace.update({key: value for key, value in dict(support.get("evidence_manifest", {}).get("trace", {})).items() if key in {"otel_enabled", "trace_ref", "tool_decision_count", "tool_result_count", "approval_denied_count"}})
    if "otel_enabled" not in trace:
        trace["otel_enabled"] = False
    existing_readiness = _load_stage_payload(
        authority_review.get("existing_readiness", {}),
        authority_review.get("evidence_inputs", {}).get("existing_readiness_report_path", ""),
        workspace_root,
    )
    clean_room_verify = _load_stage_payload(
        authority_review.get("clean_room_verify", {}),
        authority_review.get("evidence_inputs", {}).get("clean_room_verify_report_path", ""),
        workspace_root,
    )
    clean_room_verify_status = normalize_status(clean_room_verify.get("status"), "UNKNOWN")
    context["existing_readiness_passed"] = normalize_status(existing_readiness.get("status"), "UNKNOWN") in {"PASS", "WAIVED"}
    context["clean_room_verify_passed"] = clean_room_verify_status == "PASS"
    context["clean_room_verify_credit_eligible"] = clean_room_verify_status in {"PASS", "WAIVED"} and bool(clean_room_verify.get("report_present", False))
    context["evidence_manifest_present"] = bool(support.get("evidence_manifest_path"))
    context["evidence_manifest_current"] = bool(support.get("is_current", False))
    claim_findings = _claim_phrase_findings(support)
    taste_gate_summary = _taste_gate_summary(support)
    task_tree_summary = _task_tree_summary(support, int(claim_findings.get("unsupported_transition_count", 0)))
    evidence_manifest_summary = _evidence_manifest_summary(support)
    repeated_verify_summary = _repeated_verify_summary(support)
    cross_verification_summary = _cross_verification_summary(support)
    convention_lock_summary = _convention_lock_summary(support)
    summary_coverage_summary = _summary_coverage_summary(support)

    required_roles: list[str] = []
    missing_required_roles: list[str] = []
    non_green_required_roles: list[str] = []
    reviewer_penalties: dict[str, list[dict[str, Any]]] = {}
    allowed_axes = set(policy.get("axes", {}).keys())
    authoritative_reviewers, authority_errors = _load_authoritative_reviewers(authority_review, workspace_root, context_path)
    errors: list[str] = list(authority_errors)

    for role, role_policy in policy.get("review_roles", {}).items():
        if _role_required(role_policy, context, mode):
            required_roles.append(role)
        reviewer_entry = authoritative_reviewers.get(role, {})
        reviewer_penalties[role] = []
        for penalty in reviewer_entry.get("penalties", []):
            normalized_penalty, error = _normalize_penalty(penalty, role, allowed_axes)
            if error:
                errors.append(error)
            elif normalized_penalty is not None:
                reviewer_penalties[role].append(normalized_penalty)
        if role in required_roles:
            if not reviewer_entry:
                missing_required_roles.append(role)
            elif not reviewer_entry.get("green", False):
                non_green_required_roles.append(role)

    user_penalties: list[dict[str, Any]] = []
    for penalty in authority_review.get("user_review", {}).get("penalties", []):
        normalized_penalty, error = _normalize_penalty(penalty, "user_review", allowed_axes)
        if error:
            errors.append(error)
        elif normalized_penalty is not None:
            user_penalties.append(normalized_penalty)

    user_awards: list[dict[str, Any]] = []
    for award in authority_review.get("user_review", {}).get("awards", []):
        normalized_award, error = _normalize_award(award, "user_review", allowed_axes)
        if error:
            errors.append(error)
        elif normalized_award is not None:
            user_awards.append(normalized_award)

    scored_user_awards, requested_credit, credited_credit, award_signals = _credit_user_awards(
        policy,
        user_awards,
        evidence_manifest_ok=bool(support.get("is_current", False)),
        support=support,
    )
    anti_cheat_signals = [
        *_audit_anti_cheat_signals(policy, authority_audit, support),
        *_protected_review_input_signals(
            policy,
            review,
            authority_review,
            authoritative_reviewers,
            context_present=context_path is not None,
            support=support,
        ),
        *_raw_user_review_score_signals(policy, authority_review, support),
        *_credit_input_spoof_signals(policy, review, support),
        *_manifest_anti_cheat_signals(
            policy,
            support,
            mode=mode,
            existing_readiness=existing_readiness,
            clean_room_verify=clean_room_verify,
        ),
        *_v12_anti_cheat_signals(
            policy,
            support,
            task_tree=task_tree_summary,
            claim_findings=claim_findings,
            cross_verification=cross_verification_summary,
            convention_lock=convention_lock_summary,
            summary_coverage=summary_coverage_summary,
        ),
        *award_signals,
    ]
    anti_cheat_signals = [_finalize_anti_cheat_signal(policy, signal) for signal in anti_cheat_signals]
    decision_summary = _decision_summary(anti_cheat_signals)
    disqualifier_result = _append_disqualifier_matches(
        disqualifier_result,
        _disqualifier_rules(),
        [
            {
                "id": signal["disqualifier_id"],
                "reason": signal["reason"],
                "evidence_refs": signal.get("evidence_refs", []),
            }
            for signal in anti_cheat_signals
            if str(signal.get("disqualifier_id", "")).strip() and str(signal.get("decision", "")).strip() == "dq"
        ],
    )
    context["legacy_hardcoding_violation"] = any(
        item.get("id") in {"DQ-003", "DQ-004", "DQ-005", "DQ-010"}
        for item in disqualifier_result.get("matched_rules", [])
        if isinstance(item, dict)
    )

    axis_results: dict[str, Any] = {}
    derived_awards: list[dict[str, Any]] = []
    raw_total = 0
    failed_axes: list[str] = []
    for axis_name, axis_policy in policy.get("axes", {}).items():
        applicable = _axis_applicable(axis_policy, context)
        if not applicable:
            axis_results[axis_name] = {
                "applicable": False,
                "max_points": axis_policy.get("max_points"),
                "floor": axis_policy.get("floor"),
                "score": None,
                "reviewer_deductions": 0,
                "user_deductions": 0,
                "passes_floor": None,
                "deductions": [],
            }
            continue

        reviewer_axis = [item for penalties in reviewer_penalties.values() for item in penalties if item["axis"] == axis_name]
        user_axis = [item for item in user_penalties if item["axis"] == axis_name]
        award_axis = [item for item in scored_user_awards if item["axis"] == axis_name]
        derived_axis, derived_errors = _derived_awards_for_axis(
            axis_name,
            axis_policy,
            context,
            evidence_manifest_ok=bool(support.get("is_current", False)),
        )
        derived_axis = _apply_clean_room_credit_metadata(derived_axis, clean_room_verify)
        errors.extend(derived_errors)
        derived_awards.extend(derived_axis)
        reviewer_deductions = sum(item["points"] for item in reviewer_axis)
        user_deductions = sum(item["points"] for item in user_axis)
        requested_user_award_points = sum(int(item.get("requested_points", item.get("points", 0))) for item in award_axis)
        user_award_points = sum(int(item.get("credited_points", item.get("points", 0))) for item in award_axis)
        derived_award_points = sum(item["points"] for item in derived_axis)
        max_points = int(axis_policy.get("max_points", 0))
        scoring_mode = str(axis_policy.get("scoring_mode", "deduction_only")).strip() or "deduction_only"
        if scoring_mode in {"user_additive_awards", "verified_work_plus_user_awards"}:
            base_points = int(axis_policy.get("base_points", 0))
        else:
            base_points = int(axis_policy.get("base_points", max_points))
        score = min(max(base_points + derived_award_points + user_award_points - reviewer_deductions - user_deductions, 0), max_points)
        floor = int(axis_policy.get("floor", 0))
        passes_floor = score >= floor
        if not passes_floor:
            failed_axes.append(axis_name)
        raw_total += score
        axis_results[axis_name] = {
            "applicable": True,
            "max_points": max_points,
            "floor": floor,
            "scoring_mode": scoring_mode,
            "base_points": base_points,
            "score": score,
            "reviewer_deductions": reviewer_deductions,
            "user_deductions": user_deductions,
            "derived_award_points": derived_award_points,
            "requested_user_award_points": requested_user_award_points,
            "user_award_points": user_award_points,
            "passes_floor": passes_floor,
            "deductions": reviewer_axis + user_axis,
            "derived_awards": derived_axis,
            "awards": award_axis,
        }

    for award in derived_awards:
        requested_credit.append(
            _requested_credit_entry(
                str(award.get("axis", "")).strip(),
                int(award.get("requested_points", award.get("points", 0))),
                str(award.get("source", "system_derived")).strip() or "system_derived",
                str(award.get("reason", "")).strip(),
                [str(ref) for ref in award.get("evidence_refs", []) if str(ref).strip()],
            )
        )
        credited_credit.append(_credited_credit_entry(award))

    total_floor = int(policy.get("total_score", {}).get("floor", 0))
    raw_total_passes = raw_total >= total_floor
    if not raw_total_passes:
        failed_axes.append("total_score")

    anti_cheat_signal_points = sum(int(signal.get("points", 0)) for signal in anti_cheat_signals)
    penalty_signal_points = sum(int(signal.get("points", 0)) for signal in anti_cheat_signals if str(signal.get("decision", "")).strip() in {"penalty", "cap", "dq"})
    cap_signal_points = sum(int(signal.get("points", 0)) for signal in anti_cheat_signals if str(signal.get("decision", "")).strip() in {"cap", "dq"})
    anti_cheat_penalty_points = min(int(policy.get("anti_cheat_layer", {}).get("penalty_cap", 0)), penalty_signal_points)
    anti_cheat_guarded_total = max(raw_total - anti_cheat_penalty_points, 0)
    anti_cheat_caps = _anti_cheat_caps(policy, cap_signal_points)
    active_caps = _materialize_caps(_caps_for_context(policy, context), total_floor) + anti_cheat_caps
    cap_limit = min([int(cap["effective_max_total_score"]) for cap in active_caps if "effective_max_total_score" in cap], default=anti_cheat_guarded_total)
    capped_total = min(anti_cheat_guarded_total, cap_limit)
    platform_cap_status = "PASS" if capped_total >= total_floor else "BLOCKED"
    anti_cheat_status = "PASS"
    if decision_summary["highest_decision"] == "dq":
        anti_cheat_status = "FAIL"
    elif decision_summary["highest_decision"] in {"penalty", "cap"}:
        anti_cheat_status = "GUARDED"

    anti_cheat_public_signals = [_public_anti_cheat_signal(signal) for signal in anti_cheat_signals]

    reviewer_green = not missing_required_roles and not non_green_required_roles
    axis_floor_status = "PASS" if not failed_axes else "BLOCKED"
    advisories = _advisories_for_context(policy, context)
    if errors:
        reviewer_green = False
        axis_floor_status = "BLOCKED"
        platform_cap_status = "BLOCKED"

    return {
        "status": "BLOCKED" if errors else "PASS",
        "scorecard_schema_version": 2,
        "scope": policy.get("scope", "codex-global"),
        "policy_version": policy.get("version", 1),
        "generated_at": utc_timestamp(),
        "workspace_root": str(workspace_root) if workspace_root is not None else str(review.get("workspace_root", "")).strip(),
        "run_id": str(support.get("evidence_manifest", {}).get("run_id", "")).strip(),
        "mode": mode,
        "disqualifier_result": disqualifier_result,
        "authoritative_context_path": str(context_path) if context_path is not None else "",
        "trace": trace,
        "evidence_manifest_path": str(support.get("evidence_manifest_path")) if support.get("evidence_manifest_path") else "",
        "workorder_path": str(support.get("workorder_path")) if support.get("workorder_path") else "",
        "taste_gate": taste_gate_summary,
        "task_tree": task_tree_summary,
        "evidence_manifest": evidence_manifest_summary,
        "repeated_verify": repeated_verify_summary,
        "cross_verification": cross_verification_summary,
        "convention_lock": convention_lock_summary,
        "summary_coverage": summary_coverage_summary,
        "scores": axis_results,
        "applicable_axes": [axis for axis, payload in axis_results.items() if payload["applicable"]],
        "raw_total_score": raw_total,
        "guarded_total_score": anti_cheat_guarded_total,
        "capped_total_score": capped_total,
        "total_floor": total_floor,
        "gate_order": list(policy.get("gate_order", [])),
        "axis_floor_check": {
            "status": axis_floor_status,
            "failed_axes": failed_axes,
            "raw_total_passes": raw_total_passes,
        },
        "anti_cheat_signals": anti_cheat_public_signals,
        "anti_cheat_layer": {
            "status": anti_cheat_status,
            "signals": anti_cheat_signals,
            "decision_summary": decision_summary,
            "signal_points": anti_cheat_signal_points,
            "penalty_signal_points": penalty_signal_points,
            "cap_signal_points": cap_signal_points,
            "penalty_points": anti_cheat_penalty_points,
            "guarded_total_score": anti_cheat_guarded_total,
            "active_caps": anti_cheat_caps,
        },
        "platform_cap": {
            "status": platform_cap_status,
            "cap_applied": bool(active_caps),
            "cap_limit": cap_limit,
            "active_caps": active_caps,
        },
        "reviewer_requirements": {
            "required_roles": required_roles,
            "missing_required_roles": missing_required_roles,
            "non_green_required_roles": non_green_required_roles,
            "reviewer_green": reviewer_green,
        },
        "requested_credit": requested_credit,
        "credited_credit": credited_credit,
        "reviewer_penalties": reviewer_penalties,
        "derived_awards": derived_awards,
        "user_penalties": user_penalties,
        "user_awards": scored_user_awards,
        "existing_readiness": existing_readiness,
        "clean_room_verify": clean_room_verify,
        "advisories": advisories,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute the Codex global user scorecard.")
    parser.add_argument("--policy-file", default=str(DEFAULT_POLICY_FILE))
    parser.add_argument("--review-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-file", default=str(DEFAULT_SCORECARD_FILE))
    parser.add_argument("--mode", choices=["quick", "verify", "release"], default="")
    args = parser.parse_args()

    policy_path = resolve_path(args.policy_file) or Path(args.policy_file)
    review_path = resolve_path(args.review_file) or Path(args.review_file)
    output_path = resolve_path(args.output_file) or Path(args.output_file)

    review = load_json(review_path)
    mode = args.mode or str(review.get("delivery_mode", "verify")).strip().lower() or "verify"
    scorecard = compute_scorecard(load_json(policy_path), review, mode)
    save_json(output_path, scorecard)

    print(scorecard["status"])
    if scorecard["errors"]:
        for reason in scorecard["errors"]:
            print(f"- {reason}")
    else:
        print(f"- raw_total_score={scorecard['raw_total_score']}")
        print(f"- capped_total_score={scorecard['capped_total_score']}")
    return status_exit_code(scorecard["status"])


if __name__ == "__main__":
    raise SystemExit(main())
