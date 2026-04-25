#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from _scorecard_common import load_json, resolve_path, save_json, utc_timestamp


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "ai-slop.final.json"
L2_PLUS = {"L2", "L3", "L4"}
ALLOWED_QUESTION_CATEGORIES = {
    "product_intent",
    "taste",
    "irreversible_risk",
    "cost_time",
    "private_context",
}
DISCOVERABLE_QUESTION_PATTERNS = (
    "which package manager",
    "where is the repo",
    "what test command",
    "what framework",
    "is there a package.json",
    "is there a pyproject",
    "어떤 패키지",
    "테스트 명령",
    "프레임워크가 뭐",
)
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
USER_DELEGATION_PATTERNS = (
    "check it yourself",
    "verify yourself",
    "you can verify",
    "알아서 확인",
    "직접 확인",
)
DELEGATION_ACTIVE_MODES = {"read_only_scouts", "bounded_workers", "verification_pair"}
DELEGATION_MODES = DELEGATION_ACTIVE_MODES | {"none", "main_only"}


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


def _entry_open(entry: dict[str, Any]) -> bool:
    return str(entry.get("status", "open")).strip().lower() == "open"


def _entry_blocking(entry: dict[str, Any]) -> bool:
    return str(entry.get("severity", "")).strip().lower() == "block"


def _claim_has_evidence(claim: dict[str, Any]) -> bool:
    return bool([item for item in claim.get("evidence_refs", []) if str(item).strip()]) or bool(
        [item for item in claim.get("verification_refs", []) if str(item).strip()]
    )


def _claim_entries(claim_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in claim_ledger.get("claims", []) if isinstance(item, dict)]


def _supported_claims_have_evidence(claim_ledger: dict[str, Any]) -> bool:
    claims = _claim_entries(claim_ledger)
    if not claims:
        return False
    return all(str(claim.get("status", "")).strip().upper() != "SUPPORTED" or _claim_has_evidence(claim) for claim in claims)


def _summary_has_evidence_marker(summary_text: str) -> bool:
    lowered = summary_text.casefold()
    return "evidence_ref" in lowered or "evidence ref" in lowered or "claim_ledger" in lowered or "summary_coverage" in lowered


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


def _evidence_refs(payload: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in payload.get("evidence_refs", []) if str(item).strip()]


def _delegation_mode(delegation_plan: dict[str, Any], workorder: dict[str, Any]) -> str:
    for payload in (delegation_plan, workorder):
        mode = str(payload.get("delegation_mode", "")).strip()
        if mode:
            return mode
    return "none"


def _validate_delegation_artifacts(
    *,
    issues: dict[str, list[str]],
    profile: str,
    mode: str,
    artifact_payloads: dict[str, tuple[dict[str, Any], str]],
) -> None:
    if mode not in DELEGATION_MODES:
        _append_issue(issues, profile, f"DELEGATION_PLAN.json uses unknown delegation_mode: {mode}", blocking=True)
        return
    if mode not in DELEGATION_ACTIVE_MODES:
        return

    for name in ("subagent_tasks", "subagent_results", "integration_decision_log", "delegation_ledger"):
        _payload, error = artifact_payloads[name]
        if error:
            filename = {
                "subagent_tasks": "SUBAGENT_TASKS.json",
                "subagent_results": "SUBAGENT_RESULTS.json",
                "integration_decision_log": "INTEGRATION_DECISION_LOG.json",
                "delegation_ledger": "DELEGATION_LEDGER.json",
            }[name]
            reason = f"required delegation artifact is missing for active delegation: {filename}" if error == "missing" else f"{filename} is {error}"
            _append_issue(issues, profile, reason, blocking=True)
    if any(error for _payload, error in artifact_payloads.values()):
        return

    subagent_tasks = artifact_payloads["subagent_tasks"][0]
    subagent_results = artifact_payloads["subagent_results"][0]
    integration_log = artifact_payloads["integration_decision_log"][0]
    delegation_ledger = artifact_payloads["delegation_ledger"][0]

    seen_write_scopes: dict[str, str] = {}
    for task in subagent_tasks.get("tasks", []):
        if not isinstance(task, dict):
            _append_issue(issues, profile, "SUBAGENT_TASKS.json contains a non-object task", blocking=True)
            continue
        task_id = str(task.get("task_id", "task")).strip() or "task"
        role = str(task.get("role", "")).strip()
        sandbox = str(task.get("sandbox", "")).strip()
        write_scope = [str(item).strip() for item in task.get("write_scope", []) if str(item).strip()]
        if sandbox == "read-only" and write_scope:
            _append_issue(issues, profile, f"read-only subagent task has write_scope: {task_id}", blocking=True)
        if role == "bounded_worker":
            if not write_scope or any(item == "assigned-by-main-agent-before-spawn" for item in write_scope):
                _append_issue(issues, profile, f"bounded worker lacks concrete write ownership: {task_id}", blocking=True)
            for path in write_scope:
                owner = seen_write_scopes.get(path)
                if owner and owner != task_id:
                    _append_issue(issues, profile, f"overlapping subagent write ownership: {path}", blocking=True)
                seen_write_scopes[path] = task_id

    results = [dict(item) for item in subagent_results.get("results", []) if isinstance(item, dict)]
    if not results:
        _append_issue(issues, profile, "SUBAGENT_RESULTS.json has no completed results for active delegation", blocking=True)
    for result in results:
        task_id = str(result.get("task_id", "task")).strip() or "task"
        role = str(result.get("role", "")).strip()
        status = str(result.get("status", "")).strip().upper()
        if status == "PENDING":
            _append_issue(issues, profile, f"SUBAGENT_RESULTS.json contains pending result at closeout: {task_id}", blocking=True)
        if not _evidence_refs(result):
            _append_issue(issues, profile, f"SUBAGENT_RESULTS.json result lacks evidence_refs: {task_id}", blocking=True)
        if status == "PASS" and role == "independent_verifier":
            verification_scope = str(result.get("verification_scope", "")).strip().lower()
            ran_full_suite = result.get("ran_full_suite")
            if verification_scope == "partial" or ran_full_suite is False:
                _append_issue(issues, profile, f"verification subagent marked PASS after partial verification: {task_id}", blocking=True)

    decisions = [dict(item) for item in integration_log.get("decisions", []) if isinstance(item, dict)]
    if not decisions:
        _append_issue(issues, profile, "INTEGRATION_DECISION_LOG.json has no decisions for active delegation", blocking=True)
    for decision in decisions:
        decision_id = str(decision.get("decision_id", "decision")).strip() or "decision"
        if not _evidence_refs(decision):
            _append_issue(issues, profile, f"INTEGRATION_DECISION_LOG.json decision lacks evidence_refs: {decision_id}", blocking=True)

    if bool(delegation_ledger.get("idle_waiting_detected", False)):
        _append_issue(issues, profile, "DELEGATION_LEDGER.json records idle waiting on a blocking subagent task", blocking=True)
    for conflict in delegation_ledger.get("conflicts", []):
        if isinstance(conflict, dict) and str(conflict.get("status", "")).strip().lower() == "open":
            conflict_id = str(conflict.get("conflict_id", "conflict")).strip() or "conflict"
            _append_issue(issues, profile, f"DELEGATION_LEDGER.json has unresolved conflict: {conflict_id}", blocking=True)
    if [item for item in delegation_ledger.get("unsupported_claims", []) if str(item).strip()]:
        _append_issue(issues, profile, "DELEGATION_LEDGER.json records unsupported subagent claims", blocking=True)


def evaluate_ai_slop(workspace_root: Path, run_id: str, profile: str = "L2") -> dict[str, Any]:
    resolved_workspace = workspace_root.expanduser().resolve()
    normalized_profile = str(profile or "L2").strip().upper()
    run_root = _run_root(resolved_workspace, run_id)
    paths = {
        "workorder": run_root / "WORKORDER.json",
        "slop_ledger": run_root / "SLOP_LEDGER.json",
        "question_queue": run_root / "QUESTION_QUEUE.json",
        "claim_ledger": run_root / "CLAIM_LEDGER.json",
        "summary_coverage": run_root / "SUMMARY_COVERAGE.json",
        "delegation_plan": run_root / "DELEGATION_PLAN.json",
        "subagent_tasks": run_root / "SUBAGENT_TASKS.json",
        "subagent_results": run_root / "SUBAGENT_RESULTS.json",
        "integration_decision_log": run_root / "INTEGRATION_DECISION_LOG.json",
        "delegation_ledger": run_root / "DELEGATION_LEDGER.json",
        "summary": resolved_workspace / "SUMMARY.md",
    }
    issues: dict[str, list[str]] = {"blockers": [], "warnings": []}
    checks: dict[str, Any] = {}

    slop_ledger, slop_error = _read_json(paths["slop_ledger"])
    checks["slop_ledger_present"] = not slop_error
    if slop_error:
        reason = f"required run artifact is missing for {normalized_profile}: SLOP_LEDGER.json" if slop_error == "missing" else f"SLOP_LEDGER.json is {slop_error}"
        _append_issue(issues, normalized_profile, reason, blocking=True)
    else:
        for entry in slop_ledger.get("entries", []):
            if not isinstance(entry, dict):
                _append_issue(issues, normalized_profile, "SLOP_LEDGER.json contains a non-object entry", blocking=True)
                continue
            if _entry_open(entry) and _entry_blocking(entry):
                issue_type = str(entry.get("issue_type", "")).strip() or "unknown"
                claim = str(entry.get("claim", "")).strip() or "open blocking AI slop entry"
                _append_issue(issues, normalized_profile, f"open blocking AI slop entry: {issue_type}: {claim}", blocking=True)

    question_queue, question_error = _read_json(paths["question_queue"])
    checks["question_queue_present"] = not question_error
    if not question_error:
        questions = [dict(item) for item in question_queue.get("questions", []) if isinstance(item, dict)]
        if len(questions) > 3:
            _append_issue(issues, normalized_profile, "QUESTION_QUEUE.json asks more than three questions", blocking=True)
        for item in questions:
            category = str(item.get("category", "")).strip()
            if category and category not in ALLOWED_QUESTION_CATEGORIES:
                _append_issue(issues, normalized_profile, f"QUESTION_QUEUE.json uses disallowed category: {category}", blocking=True)
            question_text = str(item.get("question", "")).casefold()
            if any(pattern in question_text for pattern in DISCOVERABLE_QUESTION_PATTERNS):
                _append_issue(issues, normalized_profile, "QUESTION_QUEUE.json asks a repo-discoverable fact", blocking=True)

    claim_ledger, claim_error = _read_json(paths["claim_ledger"])
    checks["claim_ledger_present"] = not claim_error
    if not claim_error:
        for claim in _claim_entries(claim_ledger):
            if str(claim.get("status", "")).strip().upper() == "SUPPORTED" and not _claim_has_evidence(claim):
                claim_id = str(claim.get("claim_id", "claim")).strip() or "claim"
                _append_issue(issues, normalized_profile, f"CLAIM_LEDGER.json marks claim as SUPPORTED without evidence: {claim_id}", blocking=True)

    summary_coverage, coverage_error = _read_json(paths["summary_coverage"])
    checks["summary_coverage_present"] = not coverage_error
    if not coverage_error:
        uncovered = [
            item
            for item in summary_coverage.get("summary_claims", [])
            if isinstance(item, dict) and str(item.get("status", "")).strip().lower() == "uncovered"
        ]
        if uncovered:
            _append_issue(issues, normalized_profile, "SUMMARY_COVERAGE.json contains uncovered summary claims", blocking=True)

    summary_text = paths["summary"].read_text(encoding="utf-8", errors="ignore") if paths["summary"].exists() else ""
    lowered_summary = summary_text.casefold()
    checks["summary_present"] = bool(summary_text)
    if any(pattern in lowered_summary for pattern in USER_DELEGATION_PATTERNS):
        _append_issue(issues, normalized_profile, "SUMMARY.md delegates verification back to the user", blocking=True)
    if _summary_uses_verification_claim_language(summary_text):
        if not _summary_has_evidence_marker(summary_text) and not _supported_claims_have_evidence(claim_ledger):
            _append_issue(issues, normalized_profile, "SUMMARY.md uses verification/PASS language without evidence mapping", blocking=True)

    workorder, workorder_error = _read_json(paths["workorder"])
    delegation_plan, delegation_error = _read_json(paths["delegation_plan"])
    checks["workorder_present"] = not workorder_error
    checks["delegation_plan_present"] = not delegation_error
    mode = _delegation_mode(delegation_plan if not delegation_error else {}, workorder if not workorder_error else {})
    checks["delegation_mode"] = mode
    if mode in DELEGATION_ACTIVE_MODES:
        if delegation_error:
            reason = "required delegation artifact is missing for active delegation: DELEGATION_PLAN.json" if delegation_error == "missing" else f"DELEGATION_PLAN.json is {delegation_error}"
            _append_issue(issues, normalized_profile, reason, blocking=True)
        if delegation_error:
            status = "BLOCKED" if issues["blockers"] else ("WARN" if issues["warnings"] else "PASS")
            return {
                "status": status,
                "workspace_root": str(resolved_workspace),
                "run_id": run_id,
                "profile": normalized_profile,
                "blockers": issues["blockers"],
                "warnings": issues["warnings"],
                "checks": checks,
                "artifacts": {name: str(path) for name, path in paths.items()},
                "generated_at": utc_timestamp(),
            }
        artifact_payloads = {
            "subagent_tasks": _read_json(paths["subagent_tasks"]),
            "subagent_results": _read_json(paths["subagent_results"]),
            "integration_decision_log": _read_json(paths["integration_decision_log"]),
            "delegation_ledger": _read_json(paths["delegation_ledger"]),
        }
        _validate_delegation_artifacts(
            issues=issues,
            profile=normalized_profile,
            mode=mode,
            artifact_payloads=artifact_payloads,
        )

    status = "BLOCKED" if issues["blockers"] else ("WARN" if issues["warnings"] else "PASS")
    return {
        "status": status,
        "workspace_root": str(resolved_workspace),
        "run_id": run_id,
        "profile": normalized_profile,
        "blockers": issues["blockers"],
        "warnings": issues["warnings"],
        "checks": checks,
        "artifacts": {name: str(path) for name, path in paths.items()},
        "generated_at": utc_timestamp(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Vibe Director AI-slop evidence for an IAW run.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", default="L2")
    parser.add_argument("--output-file", default=str(REPORT))
    args = parser.parse_args()

    workspace_root = resolve_path(args.workspace_root) or Path(args.workspace_root)
    report = evaluate_ai_slop(workspace_root, str(args.run_id).strip(), str(args.profile).strip().upper())
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
