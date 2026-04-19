#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_REVIEW_FILE,
    default_user_review,
    file_hash,
    fresh_evidence_manifest_path,
    fresh_trace_id,
    git_lines,
    git_output,
    git_sha,
    load_json,
    load_jsonl,
    normalize_status,
    project_id,
    resolve_path,
    reviewer_verdict_dir,
    save_json,
    scorecard_context_path,
    stable_json_hash,
    strip_signature,
    utc_timestamp,
    user_review_update_authorized,
    verify_truth_signature,
    worktree_id,
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
)

REVIEWER_ROLES = (
    "skeptic_reviewer",
    "correctness_verifier",
    "contamination_monitor",
    "final_auditor",
)

SKIP_OR_XFAIL_MARKERS = (
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "pytest.skip(",
    "pytest.xfail(",
    "@unittest.skip",
    "skipTest(",
    "SkipTest(",
)

DEFAULT_TASK_CONTEXT = {
    "small_l0": False,
    "completion_review_required": True,
    "contamination_review_required": False,
    "final_auditor_required": False,
    "trace_required": True,
    "reliability_applicable": False,
    "external_calls": False,
    "reliability_evidence_present": False,
    "search_evidence_applicable": False,
    "search_engineering_core_path": False,
    "retrieval_canonical_decision_path": False,
    "external_docs_dependency": False,
    "untrusted_context": False,
    "web_or_mcp_access": False,
    "security_sensitive": False,
    "security_evidence_present": False,
    "legacy_hardcoding_violation": False,
}

MARKDOWN_HEADING_PATTERN = re.compile(r"^\s*(?P<hashes>#{1,6})\s*(?P<text>.*?)\s*$")
TEST_CHANGE_SECTION_LABELS = (
    "Test Change Rationale",
    "Test Change Notes",
)
IGNORED_TEST_CHANGE_RATIONALE_LINES = {
    "none",
    "n/a",
    "na",
    "not applicable",
    "add run-specific rationale here",
}
TEST_CHANGE_GUIDANCE_PREFIX = "if this run deleted tests, added skip or xfail"


def default_review_payload() -> dict[str, Any]:
    return {
        "status": "TEMPLATE",
        "task_id": "",
        "workspace_root": "",
        "delivery_mode": "verify",
        "task_context": dict(DEFAULT_TASK_CONTEXT),
        "evidence_inputs": {
            "trace_report_path": "",
            "existing_readiness_report_path": "",
            "clean_room_verify_report_path": "",
        },
        "trace": {
            "required": True,
            "status": "UNKNOWN",
            "evidence_refs": [],
            "notes": "",
        },
        "reviewers": {
            role: {"status": "PENDING", "green": False, "penalties": [], "notes": ""}
            for role in REVIEWER_ROLES
        },
        "user_review": default_user_review(),
        "disqualifiers": [],
        "existing_readiness": {
            "status": "UNKNOWN",
            "reason": "",
            "manual_close_out": [],
            "evidence_refs": [],
        },
        "clean_room_verify": {
            "status": "UNKNOWN",
            "reason": "",
            "manual_close_out": [],
            "evidence_refs": [],
        },
    }


def empty_reviewer_payload() -> dict[str, Any]:
    return {role: {"status": "PENDING", "green": False, "penalties": [], "notes": ""} for role in REVIEWER_ROLES}


def user_review_update_present(base: dict[str, Any]) -> bool:
    user_review = base.get("user_review")
    if not isinstance(user_review, dict):
        return False
    if list(user_review.get("awards", [])) or list(user_review.get("penalties", [])):
        return True
    if str(user_review.get("notes", "")).strip():
        return True
    return normalize_status(user_review.get("status"), "PENDING") != "PENDING"


def authorized_user_review(base: dict[str, Any]) -> dict[str, Any]:
    if not user_review_update_authorized(base):
        return default_user_review()
    source = base.get("user_review", {})
    return {
        "status": normalize_status(source.get("status"), "PENDING"),
        "awards": list(source.get("awards", [])),
        "penalties": list(source.get("penalties", [])),
        "notes": str(source.get("notes", "")).strip(),
    }


def user_review_tamper_events(base: dict[str, Any], base_path: Path) -> list[dict[str, Any]]:
    if not user_review_update_present(base) or user_review_update_authorized(base):
        return []
    return [
        {
            "category": "unauthorized_user_review_modification",
            "reason": "base review tried to modify the protected user-review layer without explicit user approval or task request",
            "path": str(base_path),
            "disqualifier_ids": ["DQ-011"],
            "evidence_refs": [str(base_path)],
        }
    ]


def _verification_stage_claim_event(
    *,
    workspace_root: Path,
    stage_name: str,
    stage_payload: dict[str, Any],
    report_path_raw: str,
) -> dict[str, Any] | None:
    status = normalize_status(stage_payload.get("status"), "UNKNOWN")
    if status not in {"PASS", "WAIVED"}:
        return None

    report_path = resolve_path(report_path_raw, workspace_root)
    evidence_refs = [str(item).strip() for item in stage_payload.get("evidence_refs", []) if str(item).strip()]
    if (report_path is not None and report_path.exists()) or evidence_refs:
        return None

    return {
        "category": "claimed_verification_without_evidence",
        "reason": f"{stage_name} claimed {status} without a report path or evidence references",
        "path": str(report_path) if report_path is not None else str(workspace_root / "reports"),
        "disqualifier_ids": [],
        "evidence_refs": [str(report_path)] if report_path is not None else [],
    }


def verification_claim_tamper_events(workspace_root: Path, context_payload: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_inputs = context_payload.get("evidence_inputs", {})
    events: list[dict[str, Any]] = []
    for stage_name, report_key in (
        ("existing_readiness", "existing_readiness_report_path"),
        ("clean_room_verify", "clean_room_verify_report_path"),
    ):
        event = _verification_stage_claim_event(
            workspace_root=workspace_root,
            stage_name=stage_name,
            stage_payload=dict(context_payload.get(stage_name, {})),
            report_path_raw=str(evidence_inputs.get(report_key, "")),
        )
        if event is not None:
            events.append(event)
    return events


def _parse_markdown_heading(line: str) -> tuple[int, str] | None:
    match = MARKDOWN_HEADING_PATTERN.match(line)
    if match is None:
        return None
    return len(match.group("hashes")), match.group("text").strip()


def _parse_test_change_section_start(text: str) -> str | None:
    stripped = text.strip()
    for label in TEST_CHANGE_SECTION_LABELS:
        if stripped.casefold() == label.casefold():
            return ""
        if not stripped.casefold().startswith(label.casefold()):
            continue
        remainder = stripped[len(label) :]
        if not remainder:
            return ""
        trimmed = remainder.lstrip()
        if trimmed.startswith(":"):
            return trimmed[1:].strip()
    return None


def _extract_test_change_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        markdown_heading = _parse_markdown_heading(lines[index])
        if markdown_heading is not None:
            level, heading_text = markdown_heading
            inline_rationale = _parse_test_change_section_start(heading_text)
            if inline_rationale is not None:
                body_lines = [inline_rationale] if inline_rationale else []
                index += 1
                while index < len(lines):
                    next_heading = _parse_markdown_heading(lines[index])
                    if next_heading is not None and next_heading[0] <= level:
                        break
                    body_lines.append(lines[index])
                    index += 1
                sections.append(body_lines)
                continue

        inline_rationale = _parse_test_change_section_start(lines[index])
        if inline_rationale is not None:
            body_lines = [inline_rationale] if inline_rationale else []
            index += 1
            while index < len(lines):
                if _parse_markdown_heading(lines[index]) is not None:
                    break
                if _parse_test_change_section_start(lines[index]) is not None:
                    break
                body_lines.append(lines[index])
                index += 1
            sections.append(body_lines)
            continue
        index += 1
    return sections


def _normalize_rationale_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    stripped = stripped.lstrip("-*").strip()
    if _parse_markdown_heading(stripped) is not None:
        return ""
    return stripped.rstrip(":").strip().rstrip(".,;!?").strip().casefold()


def _test_change_rationale_present(workspace_root: Path) -> bool:
    def _meaningful_rationale_body(text: str) -> bool:
        for body_lines in _extract_test_change_sections(text):
            for raw_line in body_lines:
                normalized = _normalize_rationale_line(raw_line)
                if not normalized:
                    continue
                if normalized in IGNORED_TEST_CHANGE_RATIONALE_LINES:
                    continue
                if normalized.startswith(TEST_CHANGE_GUIDANCE_PREFIX):
                    continue
                return True
        return False

    for path in (workspace_root / "DESIGN_REVIEW.md", workspace_root / "SUMMARY.md"):
        if path.exists() and _meaningful_rationale_body(path.read_text(encoding="utf-8", errors="ignore")):
            return True
    return False


def workspace_test_change_tamper_events(workspace_root: Path) -> list[dict[str, Any]]:
    if _test_change_rationale_present(workspace_root):
        return []

    deleted_tests: list[str] = []
    for line in git_lines(workspace_root, "diff", "--name-status", "HEAD", "--", "tests"):
        parts = line.split("\t")
        if parts and parts[0].startswith("D") and len(parts) > 1:
            deleted_tests.append(parts[-1])

    weakening_lines = [
        line
        for line in git_output(workspace_root, "diff", "HEAD", "--", "tests").splitlines()
        if line.startswith("+")
        and not line.startswith("+++")
        and any(marker in line for marker in SKIP_OR_XFAIL_MARKERS)
    ]

    if not deleted_tests and not weakening_lines:
        return []

    reason_parts: list[str] = []
    if deleted_tests:
        reason_parts.append(f"deleted tests: {', '.join(sorted(set(deleted_tests)))}")
    if weakening_lines:
        reason_parts.append("added skip or xfail markers in tests without Test Change Rationale")
    return [
        {
            "category": "test_deletion_or_weakening_without_rationale",
            "reason": "; ".join(reason_parts),
            "path": str(workspace_root / "tests"),
            "disqualifier_ids": [],
            "evidence_refs": [str(workspace_root / "tests")],
        }
    ]


def stage_from_readiness(report: dict[str, Any]) -> dict[str, Any]:
    overall = str(report.get("overall", "")).strip().lower()
    if overall == "ready":
        return {"status": "PASS", "reason": "", "manual_close_out": [], "evidence_refs": []}
    if overall == "conditional":
        return {"status": "BLOCKED", "reason": "user readiness is conditional", "manual_close_out": [], "evidence_refs": []}
    if overall == "not_ready":
        return {"status": "FAIL", "reason": "user readiness is not_ready", "manual_close_out": [], "evidence_refs": []}
    return {
        "status": normalize_status(report.get("status"), "UNKNOWN"),
        "reason": str(report.get("reason", "")).strip(),
        "manual_close_out": list(report.get("manual_close_out", [])),
        "evidence_refs": list(report.get("evidence_refs", [])),
    }


def stage_from_acceptance(report: dict[str, Any]) -> dict[str, Any]:
    status = normalize_status(report.get("status"), "UNKNOWN")
    reason = str(report.get("reason", "")).strip()
    if not reason:
        reason = str(report.get("failure_summary", "")).strip()
    return {
        "status": status,
        "reason": reason,
        "manual_close_out": list(report.get("manual_close_out", [])),
        "evidence_refs": list(report.get("evidence_refs", [])),
    }


def stage_from_trace(report: dict[str, Any], path: Path) -> dict[str, Any]:
    notes = str(report.get("summary", "")).strip() or str(report.get("reason", "")).strip()
    return {
        "required": True,
        "status": normalize_status(report.get("status"), "UNKNOWN"),
        "evidence_refs": [str(path)] if path.exists() else [],
        "notes": notes,
    }


def derive_task_context(mode: str, base_context: dict[str, Any], context7: dict[str, Any]) -> dict[str, Any]:
    context = dict(DEFAULT_TASK_CONTEXT)
    context.update(base_context)
    context["small_l0"] = mode == "quick"
    context["completion_review_required"] = mode in {"verify", "release"}
    context["final_auditor_required"] = mode in {"verify", "release"}
    context["trace_required"] = True

    has_context7 = bool(context7.get("entries", []))
    if has_context7:
        context["search_evidence_applicable"] = True
        context["external_docs_dependency"] = True
        context["web_or_mcp_access"] = True
    return context


def current_trace_id(workspace_root: Path, mode: str) -> str:
    return fresh_trace_id(workspace_root) or f"{workspace_root.name}-{mode}"


def build_context_payload(workspace_root: Path, mode: str, base: dict[str, Any]) -> dict[str, Any]:
    reports = workspace_root / "reports"
    delivery_gate_path = reports / "delivery-gate.json"
    readiness_path = reports / "user-readiness.json"
    acceptance_path = reports / "acceptance-report.json"
    trace_path = reports / "traceability-report.json"
    context7_path = reports / "context7-usage.json"

    delivery_gate = load_json(delivery_gate_path)
    readiness = load_json(readiness_path)
    acceptance = load_json(acceptance_path)
    trace = load_json(trace_path)
    context7 = load_json(context7_path)

    if not readiness and delivery_gate:
        readiness = {"status": delivery_gate.get("status", "UNKNOWN"), "reason": "; ".join(delivery_gate.get("reasons", []))}
    if not acceptance and delivery_gate:
        acceptance = dict(delivery_gate.get("acceptance", {}))

    trace_id = current_trace_id(workspace_root, mode)
    user_review = authorized_user_review(base)
    evidence_manifest_path = published_evidence_manifest_path(workspace_root)
    workorder_path = published_workorder_path(workspace_root, evidence_manifest_path)
    command_log_path = published_command_log_path(workspace_root, evidence_manifest_path)
    waivers_path = published_waivers_path(workspace_root, evidence_manifest_path)
    task_tree_path = published_task_tree_path(workspace_root, evidence_manifest_path)
    repeated_verify_path = published_repeated_verify_path(workspace_root, evidence_manifest_path)
    cross_verification_path = published_cross_verification_path(workspace_root, evidence_manifest_path)
    claim_ledger_path = published_claim_ledger_path(workspace_root, evidence_manifest_path)
    summary_coverage_path = published_summary_coverage_path(workspace_root, evidence_manifest_path)
    convention_lock_path = published_convention_lock_path(workspace_root, evidence_manifest_path)
    taste_gate_path = published_taste_gate_path(workspace_root, evidence_manifest_path)
    summary_path = workspace_root / "SUMMARY.md"
    design_review_path = workspace_root / "DESIGN_REVIEW.md"
    return {
        "context_version": 2,
        "status": "READY",
        "task_id": str(base.get("task_id", "")).strip() or f"{workspace_root.name}-{mode}",
        "workspace_root": str(workspace_root),
        "delivery_mode": mode,
        "trace_id": trace_id,
        "codex_project_id": project_id(workspace_root),
        "git_sha": git_sha(workspace_root),
        "worktree_id": worktree_id(workspace_root),
        "fresh_evidence_manifest_path": str(fresh_evidence_manifest_path(workspace_root)),
        "task_context": derive_task_context(mode, dict(base.get("task_context", {})), context7),
        "evidence_inputs": {
            "evidence_manifest_path": str(evidence_manifest_path) if evidence_manifest_path.exists() else "",
            "workorder_path": str(workorder_path) if workorder_path is not None and workorder_path.exists() else "",
            "command_log_path": str(command_log_path) if command_log_path is not None and command_log_path.exists() else "",
            "waivers_path": str(waivers_path) if waivers_path is not None and waivers_path.exists() else "",
            "task_tree_path": str(task_tree_path) if task_tree_path is not None and task_tree_path.exists() else "",
            "repeated_verify_path": str(repeated_verify_path) if repeated_verify_path is not None and repeated_verify_path.exists() else "",
            "cross_verification_path": str(cross_verification_path) if cross_verification_path is not None and cross_verification_path.exists() else "",
            "claim_ledger_path": str(claim_ledger_path) if claim_ledger_path is not None and claim_ledger_path.exists() else "",
            "summary_coverage_path": str(summary_coverage_path) if summary_coverage_path is not None and summary_coverage_path.exists() else "",
            "convention_lock_path": str(convention_lock_path) if convention_lock_path is not None and convention_lock_path.exists() else "",
            "taste_gate_path": str(taste_gate_path) if taste_gate_path is not None and taste_gate_path.exists() else "",
            "summary_path": str(summary_path) if summary_path.exists() else "",
            "design_review_path": str(design_review_path) if design_review_path.exists() else "",
            "trace_report_path": str(trace_path) if trace_path.exists() else "",
            "existing_readiness_report_path": str(readiness_path) if readiness_path.exists() else "",
            "clean_room_verify_report_path": str(acceptance_path) if acceptance_path.exists() else "",
        },
        "trace": stage_from_trace(trace, trace_path) if trace_path.exists() else {"required": True, "status": "UNKNOWN", "evidence_refs": [], "notes": ""},
        "existing_readiness": stage_from_readiness(readiness),
        "clean_room_verify": stage_from_acceptance(acceptance),
        "user_review": user_review,
        "disqualifiers": list(base.get("disqualifiers", [])),
    }


def validate_verdict_entry(
    entry: dict[str, Any],
    *,
    role: str,
    workspace_root: Path,
    context_hash: str,
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
    if str(entry.get("input_report_hash", "")).strip() != context_hash:
        return "input_report_hash mismatch"
    if not str(entry.get("generated_at", "")).strip():
        return "generated_at is missing"
    return ""


def load_authoritative_reviewers(
    workspace_root: Path,
    context_payload: dict[str, Any],
    context_path: Path,
    extra_tamper_events: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reviewers = empty_reviewer_payload()
    trace_id = str(context_payload["trace_id"])
    context_hash = file_hash(context_path)
    current_git_sha = str(context_payload["git_sha"])
    current_worktree_id = str(context_payload["worktree_id"])
    current_project_id = str(context_payload["codex_project_id"])
    verdict_root = reviewer_verdict_dir(workspace_root, trace_id)

    ignored_entries: list[dict[str, Any]] = []
    valid_roles: list[str] = []
    for role in REVIEWER_ROLES:
        entries = load_jsonl(verdict_root / f"{role}.jsonl")
        valid_entry: dict[str, Any] | None = None
        for index, entry in enumerate(entries):
            reason = validate_verdict_entry(
                entry,
                role=role,
                workspace_root=workspace_root,
                context_hash=context_hash,
                trace_id=trace_id,
                current_git_sha=current_git_sha,
                current_worktree_id=current_worktree_id,
                current_project_id=current_project_id,
            )
            if reason:
                ignored_entries.append(
                    {
                        "role": role,
                        "path": str(verdict_root / f"{role}.jsonl"),
                        "entry_index": index,
                        "reason": reason,
                    }
                )
                continue
            valid_entry = entry
        if valid_entry is None:
            continue
        valid_roles.append(role)
        reviewers[role] = {
            "status": normalize_status(valid_entry.get("status"), "PENDING"),
            "green": bool(valid_entry.get("green", False)),
            "penalties": list(valid_entry.get("penalties", [])),
            "notes": str(valid_entry.get("notes", "")).strip(),
        }

    workspace_audit_path = workspace_root / "reports" / "audit.final.json"
    workspace_audit = load_json(workspace_audit_path)
    workspace_tamper_events = [dict(item) for item in workspace_audit.get("tamper_events", []) if isinstance(item, dict)]
    if extra_tamper_events:
        workspace_tamper_events = [*extra_tamper_events, *workspace_tamper_events]

    audit_report = {
        "workspace_root": str(workspace_root),
        "trace_id": trace_id,
        "authoritative_context_path": str(context_path),
        "authoritative_context_hash": context_hash,
        "reviewer_verdict_dir": str(verdict_root),
        "workspace_audit_path": str(workspace_audit_path),
        "workspace_audit_status": normalize_status(workspace_audit.get("status"), "UNKNOWN") if workspace_audit else "UNKNOWN",
        "valid_verdict_roles": valid_roles,
        "ignored_entries": ignored_entries,
        "tamper_events": [
            *[
                {
                    "category": "reviewer_truth",
                    "reason": item["reason"],
                    "role": item["role"],
                    "path": item["path"],
                    "disqualifier_ids": ["DQ-011"],
                }
                for item in ignored_entries
            ],
            *workspace_tamper_events,
        ],
        "generated_at": utc_timestamp(),
    }
    return reviewers, audit_report


def build_snapshot_payload(
    *,
    base: dict[str, Any],
    context_payload: dict[str, Any],
    context_path: Path,
    reviewers: dict[str, Any],
    audit_path: Path,
) -> dict[str, Any]:
    payload = dict(context_payload)
    payload["reviewers"] = reviewers
    payload["authoritative_context_path"] = str(context_path)
    payload["authoritative_context_hash"] = file_hash(context_path)
    payload["authority_audit_path"] = str(audit_path)
    payload["user_review"] = dict(context_payload.get("user_review", default_user_review()))
    payload["disqualifiers"] = list(base.get("disqualifiers", context_payload.get("disqualifiers", [])))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the scorecard context and derived review snapshot from workspace reports.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--mode", choices=["quick", "verify", "release"], default="verify")
    parser.add_argument("--base-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-file", default="", help="Deprecated alias for --review-snapshot-output.")
    parser.add_argument("--context-output-file", default="")
    parser.add_argument("--review-snapshot-output", default="")
    args = parser.parse_args()

    workspace_root = resolve_path(args.workspace_root) or Path(args.workspace_root)
    base_path = resolve_path(args.base_file) or Path(args.base_file)
    base = load_json(base_path, default_review_payload())
    base_user_review_tamper_events = user_review_tamper_events(base, base_path)

    context_payload = build_context_payload(workspace_root, args.mode, base)
    extra_tamper_events = [
        *base_user_review_tamper_events,
        *verification_claim_tamper_events(workspace_root, context_payload),
        *workspace_test_change_tamper_events(workspace_root),
    ]
    context_path = resolve_path(args.context_output_file) or scorecard_context_path(workspace_root, str(context_payload["trace_id"]))
    snapshot_path = resolve_path(args.review_snapshot_output or args.output_file) or (resolve_path(args.output_file) or DEFAULT_REVIEW_FILE)

    save_json(context_path, context_payload)
    reviewers, audit_report = load_authoritative_reviewers(
        workspace_root,
        context_payload,
        context_path,
        extra_tamper_events=extra_tamper_events,
    )
    audit_path = workspace_root / "reports" / "scorecard-authority-audit.json"
    save_json(audit_path, audit_report)

    snapshot = build_snapshot_payload(
        base=base,
        context_payload=context_payload,
        context_path=context_path,
        reviewers=reviewers,
        audit_path=audit_path,
    )
    save_json(snapshot_path, snapshot)

    print("PASS")
    print(f"- prepared context file: {context_path}")
    print(f"- prepared review snapshot: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
