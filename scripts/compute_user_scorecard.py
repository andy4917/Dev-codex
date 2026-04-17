#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_DISQUALIFIER_FILE,
    DEFAULT_POLICY_FILE,
    DEFAULT_REVIEW_FILE,
    DEFAULT_SCORECARD_FILE,
    file_hash,
    git_sha,
    load_json,
    load_jsonl,
    normalize_status,
    project_id,
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


def _bool_flag(context: dict[str, Any], key: str) -> bool:
    return bool(context.get(key, False))


def _load_stage_payload(raw_stage: dict[str, Any], report_path_raw: str, workspace_root: Path | None) -> dict[str, Any]:
    report_path = resolve_path(report_path_raw, workspace_root)
    stage = dict(raw_stage)
    if report_path is not None and report_path.exists():
        external = load_json(report_path)
        if isinstance(external, dict):
            stage = {**stage, **external}
        stage["report_path"] = str(report_path)
    elif report_path is not None:
        stage["report_path"] = str(report_path)
    stage["status"] = normalize_status(stage.get("status"), "UNKNOWN")
    stage["manual_close_out"] = list(stage.get("manual_close_out", []))
    stage["evidence_refs"] = list(stage.get("evidence_refs", []))
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
    if "user_review" in review:
        payload["user_review"] = dict(review.get("user_review", {}))
    if "disqualifiers" in review:
        payload["disqualifiers"] = list(review.get("disqualifiers", []))
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


def compute_scorecard(policy: dict[str, Any], review: dict[str, Any], mode: str) -> dict[str, Any]:
    snapshot_workspace_root = resolve_path(review.get("workspace_root", "")) if str(review.get("workspace_root", "")).strip() else None
    authority_review, context_path = _load_context(review, snapshot_workspace_root)
    context = dict(authority_review.get("task_context", {}))
    workspace_root = resolve_path(authority_review.get("workspace_root", "")) if str(authority_review.get("workspace_root", "")).strip() else snapshot_workspace_root
    disqualifier_result = evaluate_disqualifiers(load_json(DEFAULT_DISQUALIFIER_FILE), authority_review)
    trace = _load_trace_payload(authority_review, workspace_root)
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

    axis_results: dict[str, Any] = {}
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
        reviewer_deductions = sum(item["points"] for item in reviewer_axis)
        user_deductions = sum(item["points"] for item in user_axis)
        max_points = int(axis_policy.get("max_points", 0))
        score = max(max_points - reviewer_deductions - user_deductions, 0)
        floor = int(axis_policy.get("floor", 0))
        passes_floor = score >= floor
        if not passes_floor:
            failed_axes.append(axis_name)
        raw_total += score
        axis_results[axis_name] = {
            "applicable": True,
            "max_points": max_points,
            "floor": floor,
            "score": score,
            "reviewer_deductions": reviewer_deductions,
            "user_deductions": user_deductions,
            "passes_floor": passes_floor,
            "deductions": reviewer_axis + user_axis,
        }

    total_floor = int(policy.get("total_score", {}).get("floor", 0))
    raw_total_passes = raw_total >= total_floor
    if not raw_total_passes:
        failed_axes.append("total_score")

    active_caps = _caps_for_context(policy, context)
    cap_limit = min([int(cap["max_total_score"]) for cap in active_caps], default=raw_total)
    capped_total = min(raw_total, cap_limit)
    platform_cap_status = "PASS" if capped_total >= total_floor else "BLOCKED"

    reviewer_green = not missing_required_roles and not non_green_required_roles
    axis_floor_status = "PASS" if not failed_axes else "BLOCKED"
    advisories = _advisories_for_context(policy, context)
    if errors:
        reviewer_green = False
        axis_floor_status = "BLOCKED"
        platform_cap_status = "BLOCKED"

    return {
        "status": "BLOCKED" if errors else "PASS",
        "scope": policy.get("scope", "codex-global"),
        "policy_version": policy.get("version", 1),
        "generated_at": utc_timestamp(),
        "workspace_root": str(workspace_root) if workspace_root is not None else str(review.get("workspace_root", "")).strip(),
        "mode": mode,
        "disqualifier_result": disqualifier_result,
        "authoritative_context_path": str(context_path) if context_path is not None else "",
        "trace": trace,
        "scores": axis_results,
        "applicable_axes": [axis for axis, payload in axis_results.items() if payload["applicable"]],
        "raw_total_score": raw_total,
        "capped_total_score": capped_total,
        "total_floor": total_floor,
        "axis_floor_check": {
            "status": axis_floor_status,
            "failed_axes": failed_axes,
            "raw_total_passes": raw_total_passes,
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
        "reviewer_penalties": reviewer_penalties,
        "user_penalties": user_penalties,
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
