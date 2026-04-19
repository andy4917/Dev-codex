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

WRITER_OR_AGENT_REPORTERS = {"writer", "main_writer", "actor", "agent", "assistant", "codex"}
LEGACY_SIGNAL_CODE_ALIASES = {
    "unauthorized_user_review_update": "unauthorized_user_review_modification",
    "derived_award_spoof_attempt": "reserved_derived_award_spoofing",
    "unexpected_user_award_axis": "excessive_bonus_request",
    "excessive_user_award_points": "excessive_bonus_request",
}


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


def _public_anti_cheat_signal(signal: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = [str(ref) for ref in signal.get("evidence_refs", []) if str(ref).strip()]
    return {
        "code": str(signal.get("code", signal.get("id", ""))).strip(),
        "severity": str(signal.get("severity", "medium")).strip() or "medium",
        "points": int(signal.get("points", 0)),
        "reason": str(signal.get("reason", "")).strip(),
        "evidence_ref": evidence_refs[0] if evidence_refs else "",
    }


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


def _derived_awards_for_axis(axis_name: str, axis_policy: dict[str, Any], context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    awards: list[dict[str, Any]] = []
    errors: list[str] = []
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
                "reported_by": "system_derived",
                "source": "system_derived",
                "credit_block_reason": "",
            }
        )
    return awards, errors


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
    }


def _audit_anti_cheat_signals(policy: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    rules = _anti_cheat_rules(policy)
    signals: list[dict[str, Any]] = []
    for event in audit.get("tamper_events", []):
        if not isinstance(event, dict):
            continue
        category = str(event.get("category", "")).strip()
        evidence_refs = [str(ref) for ref in event.get("evidence_refs", []) if str(ref).strip()]
        if category in {"unauthorized_user_review_update", "unauthorized_user_review_modification"}:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    "unauthorized_user_review_modification",
                    reason=str(event.get("reason", "")).strip(),
                    evidence_refs=evidence_refs,
                    details={"category": category, "path": str(event.get("path", "")).strip()},
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
                )
            )
        elif category in {
            "claimed_verification_without_evidence",
            "test_deletion_or_weakening_without_rationale",
            "score_policy_tamper_without_policy_update_workorder",
        }:
            signals.append(
                _anti_cheat_signal(
                    rules,
                    category,
                    reason=str(event.get("reason", "")).strip(),
                    evidence_refs=evidence_refs,
                    details={"category": category, "path": str(event.get("path", "")).strip()},
                )
            )
    return signals


def _raw_user_review_score_signals(policy: dict[str, Any], authority_review: dict[str, Any]) -> list[dict[str, Any]]:
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
                    )
                )
    return signals


def _credit_user_awards(
    policy: dict[str, Any], user_awards: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    anti_cheat = policy.get("anti_cheat_layer", {})
    rules = _anti_cheat_rules(policy)
    budgets = {
        str(axis).strip(): int(points)
        for axis, points in anti_cheat.get("per_axis_user_award_budgets", {}).items()
        if str(axis).strip()
    }
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
                )
            )
            continue
        if entry["source"] == "agent_request":
            entry["credit_block_reason"] = "requested_only_source"
            if not _is_writer_or_agent_reporter(reported_by):
                signals.append(
                    _anti_cheat_signal(
                        rules,
                        "non_user_source_award",
                        reason=f"user award for axis '{entry['axis']}' came from non-user source '{reported_by or 'unknown'}'",
                        evidence_refs=[str(ref) for ref in entry.get("evidence_refs", []) if str(ref).strip()],
                        details={"axis": entry["axis"], "reported_by": reported_by or "unknown"},
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
    authority_audit = _load_authority_audit(authority_review, workspace_root)
    disqualifier_policy = load_json(DEFAULT_DISQUALIFIER_FILE)
    disqualifier_result = evaluate_disqualifiers(disqualifier_policy, authority_review)
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
    context["existing_readiness_passed"] = normalize_status(existing_readiness.get("status"), "UNKNOWN") in {"PASS", "WAIVED"}
    context["clean_room_verify_passed"] = normalize_status(clean_room_verify.get("status"), "UNKNOWN") in {"PASS", "WAIVED"}

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

    scored_user_awards, requested_credit, credited_credit, award_signals = _credit_user_awards(policy, user_awards)
    anti_cheat_signals = [
        *_audit_anti_cheat_signals(policy, authority_audit),
        *_raw_user_review_score_signals(policy, authority_review),
        *award_signals,
    ]
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
            if str(signal.get("disqualifier_id", "")).strip()
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
        derived_axis, derived_errors = _derived_awards_for_axis(axis_name, axis_policy, context)
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
    anti_cheat_penalty_points = min(int(policy.get("anti_cheat_layer", {}).get("penalty_cap", 0)), anti_cheat_signal_points)
    anti_cheat_guarded_total = max(raw_total - anti_cheat_penalty_points, 0)
    anti_cheat_caps = _anti_cheat_caps(policy, anti_cheat_signal_points)
    active_caps = _materialize_caps(_caps_for_context(policy, context), total_floor) + anti_cheat_caps
    cap_limit = min([int(cap["effective_max_total_score"]) for cap in active_caps if "effective_max_total_score" in cap], default=anti_cheat_guarded_total)
    capped_total = min(anti_cheat_guarded_total, cap_limit)
    platform_cap_status = "PASS" if capped_total >= total_floor else "BLOCKED"
    anti_cheat_status = "PASS"
    if any(
        str(signal.get("disqualifier_id", "")).strip()
        or str(signal.get("severity", "")).strip().lower() == "critical"
        or str(signal.get("code", "")).strip() == "score_policy_tamper_without_policy_update_workorder"
        for signal in anti_cheat_signals
    ):
        anti_cheat_status = "FAIL"
    elif anti_cheat_signals:
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
        "mode": mode,
        "disqualifier_result": disqualifier_result,
        "authoritative_context_path": str(context_path) if context_path is not None else "",
        "trace": trace,
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
            "signal_points": anti_cheat_signal_points,
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
