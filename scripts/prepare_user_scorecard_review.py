#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_REVIEW_FILE,
    file_hash,
    fresh_evidence_manifest_path,
    fresh_trace_id,
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
    verify_truth_signature,
    worktree_id,
)

REVIEWER_ROLES = (
    "skeptic_reviewer",
    "correctness_verifier",
    "contamination_monitor",
    "final_auditor",
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
}


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
        "user_review": {
            "status": "PENDING",
            "penalties": [],
            "notes": "",
        },
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
    return {
        "context_version": 1,
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
            "trace_report_path": str(trace_path) if trace_path.exists() else "",
            "existing_readiness_report_path": str(readiness_path) if readiness_path.exists() else "",
            "clean_room_verify_report_path": str(acceptance_path) if acceptance_path.exists() else "",
        },
        "trace": stage_from_trace(trace, trace_path) if trace_path.exists() else {"required": True, "status": "UNKNOWN", "evidence_refs": [], "notes": ""},
        "existing_readiness": stage_from_readiness(readiness),
        "clean_room_verify": stage_from_acceptance(acceptance),
        "user_review": dict(base.get("user_review", {"status": "PENDING", "penalties": [], "notes": ""})),
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


def load_authoritative_reviewers(workspace_root: Path, context_payload: dict[str, Any], context_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
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

    audit_report = {
        "workspace_root": str(workspace_root),
        "trace_id": trace_id,
        "authoritative_context_path": str(context_path),
        "authoritative_context_hash": context_hash,
        "reviewer_verdict_dir": str(verdict_root),
        "valid_verdict_roles": valid_roles,
        "ignored_entries": ignored_entries,
        "tamper_events": [
            {
                "category": "reviewer_truth",
                "reason": item["reason"],
                "role": item["role"],
                "path": item["path"],
                "disqualifier_ids": ["DQ-002", "DQ-009"],
            }
            for item in ignored_entries
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
    payload["user_review"] = dict(base.get("user_review", context_payload.get("user_review", {})))
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

    context_payload = build_context_payload(workspace_root, args.mode, base)
    context_path = resolve_path(args.context_output_file) or scorecard_context_path(workspace_root, str(context_payload["trace_id"]))
    snapshot_path = resolve_path(args.review_snapshot_output or args.output_file) or (resolve_path(args.output_file) or DEFAULT_REVIEW_FILE)

    save_json(context_path, context_payload)
    reviewers, audit_report = load_authoritative_reviewers(workspace_root, context_payload, context_path)
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
