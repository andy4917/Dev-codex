#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json, write_markdown
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "global-agent-workflow.final.json"
DOC_PATH = ROOT / "docs" / "GLOBAL_AGENT_WORKFLOW.md"
SETUP_DOC_PATH = ROOT / "docs" / "CODEX_APP_USER_SETUP.md"
POLICY_PATH = ROOT / "contracts" / "global_agent_workflow_policy.json"

EXPECTED_RUNTIME_MODEL = {
    "user_ui": "Codex App",
    "canonical_execution": "windows-native",
    "agent_binary": "windows-native-codex-app-agent",
    "windows_native_for_governed_repos": "required",
}
EXPECTED_AUTHORITY_LAYERS = {
    "app_settings": "concise_global_authority_capsule",
    "dev_management": "environment_policy_authority",
    "repo_agents": "stack_workflow_authority",
    "package_scripts": "command_authority",
    "skills": "workflow_modules_not_truth",
    "context7": "external_docs_evidence",
    "serena": "codebase_semantic_evidence",
    "domain_rag": "business_domain_evidence",
}
EXPECTED_QUALITY_TERMS = {
    "think_again_explain_why": "Before asserting status, approval, readiness, or PASS, re-check the declared scope, oracle, evidence, and counterexamples, then explain the reason for the claim.",
    "test": "Limited exploration for counterexamples plus partial evidence of expected behavior.",
    "verification": "Checking whether current artifacts match the declared oracle, scope, and policy.",
    "review": "Adversarial reading that exposes hidden assumptions, missing counterexamples, wrong oracles, and oversimplification.",
    "pass": "No counterexample was found inside the currently declared scope and oracle; it is not universal proof or formal approval.",
    "formal_approval": "Only an explicit user, reviewer, or gate authority can approve; tests, verification output, and PASS language alone do not grant approval.",
}
EXPECTED_SUBAGENT_DELEGATION_POLICY = {
    "modes": [
        "read_only_scouts",
        "bounded_workers",
        "verification_pair",
        "none",
        "main_only",
    ],
    "active_modes": ["read_only_scouts", "bounded_workers", "verification_pair"],
    "trigger_classes": [
        "broad_multi_surface_audit",
        "global_cleanup",
        "dirty_closeout",
        "policy_checker_change",
        "l2_plus_verification",
        "explicit_exhaustive_file_or_folder_review",
    ],
    "waiver_reasons": [
        "critical_path_live_restart",
        "narrow_leaf_change",
        "tool_unavailable",
        "no_parallelizable_sidecar",
        "plan_mode_read_only",
    ],
    "max_subagents": 2,
    "decision_artifact": ".agent-runs/<run_id>/DELEGATION_DECISION.json",
    "active_artifacts": [
        "DELEGATION_PLAN.json",
        "SUBAGENT_TASKS.json",
        "SUBAGENT_RESULTS.json",
        "INTEGRATION_DECISION_LOG.json",
        "DELEGATION_LEDGER.json",
    ],
    "missing_decision_status": "BLOCKED",
    "subagent_tool_gap_requires_fallback": True,
}
REQUIRED_HEADINGS = [
    "# Global Agent Workflow",
    "## Runtime Model",
    "## Evidence Roles",
    "## Work Cycle",
    "## Subagent Delegation",
    "## Quality Gate",
    "## Reasoning And Quality Terms",
    "## Forbidden",
]
REQUIRED_DOC_PHRASES = [
    "`C:\\Users\\anise\\.codex` is `USER_CONTROL_PLANE + APP_STATE`, not repo authority.",
    "The user's explicit instruction is the highest project authority inside allowed system/developer constraints.",
    "Repo `AGENTS.md`: stack/workflow authority for that repo.",
    "package scripts: command authority.",
    "Skills: repeatable workflow modules, not factual authority.",
    "Context7: external library/framework/API documentation evidence.",
    "Serena: codebase semantic retrieval, impact mapping, and refactor evidence.",
    "Domain RAG/Product Docs: business/domain requirement evidence.",
    "run the exact code path that was touched",
    "use `C:\\Users\\anise\\code\\.scratch\\Dev-Management\\` for local scratch harnesses",
    "report WARN/BLOCKED with disposition",
    "before broad multi-surface audits, global cleanup, dirty closeout, policy/checker changes, L2+ verification",
    "use `read_only_scouts` for parallel repo/app-state/report classification and evidence gathering",
    "if a triggered task remains `none` or `main_only`, record the waiver in `DELEGATION_DECISION.json` or `WORKORDER.json`",
    "allowed waiver reasons are `critical_path_live_restart`, `narrow_leaf_change`, `tool_unavailable`, `no_parallelizable_sidecar`, and `plan_mode_read_only`",
    "touched-code runtime verification against actual behavior",
    "Linux/remote execution authority is decommissioned",
    "dispose them through the Windows Recycle Bin",
    "keep only 1 day of logs in original live form",
    "run the recurring app maintenance cycle at logon and every 240 minutes",
    "the hook must run once per task turn with `user_prompt_throttle_seconds = 0`",
    "Think again / explain why: before asserting status, approval, readiness, or PASS",
    "Test: limited exploration for counterexamples plus partial evidence of expected behavior.",
    "Verification: checking whether current artifacts match the declared oracle, scope, and policy.",
    "Review: adversarial reading that exposes hidden assumptions, missing counterexamples, wrong oracles, and oversimplification.",
    "PASS: no counterexample was found inside the currently declared scope and oracle; it is not universal proof or formal approval.",
    "Formal approval: only an explicit user, reviewer, or gate authority can approve",
]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def build_setup_doc_template(pointer_text: str) -> str:
    return (
        "# Codex App User Setup\n\n"
        "Copy this exact text into Codex App global settings:\n\n"
        "```text\n"
        f"{pointer_text}"
        "```"
    )


def _check(status: str, reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "reasons": reasons or []}
    payload.update(extra)
    return payload


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    required_top_level = {
        "schema_version",
        "runtime_model",
        "authority_layers",
        "required_evidence_matrix",
        "subagent_delegation_policy",
        "vibe_coding_standard",
        "touched_code_runtime_verification",
        "quality_workflow",
        "quality_terms",
        "fallback_rules",
        "forbidden",
    }
    missing = sorted(required_top_level - set(policy.keys()))
    if missing:
        blockers.append(f"policy is missing required top-level keys: {', '.join(missing)}")
    if policy.get("schema_version") != "2026.04.global-agent-workflow.windows-native.v1":
        blockers.append("policy schema_version does not match 2026.04.global-agent-workflow.windows-native.v1")
    if policy.get("runtime_model") != EXPECTED_RUNTIME_MODEL:
        blockers.append("runtime_model does not match the required canonical runtime definition")
    if policy.get("authority_layers") != EXPECTED_AUTHORITY_LAYERS:
        blockers.append("authority_layers do not match the required workflow/evidence roles")

    matrix = policy.get("required_evidence_matrix", {})
    if matrix.get("backend_auth_payment_db_migration") != ["serena", "context7", "domain_rag"]:
        blockers.append("backend auth/payment/DB/migration is allowed without Serena + Context7 + Domain RAG")
    if "domain_rag" not in list(matrix.get("domain_business_rule", [])):
        blockers.append("domain/business logic is allowed without domain evidence")
    if list(matrix.get("external_library_api_change", [])) != ["context7"]:
        blockers.append("Context7 is not the required external library/API evidence source")
    if list(matrix.get("code_refactor", [])) != ["serena"]:
        blockers.append("Serena is not the required code refactor evidence source")

    if policy.get("subagent_delegation_policy") != EXPECTED_SUBAGENT_DELEGATION_POLICY:
        blockers.append("subagent_delegation_policy does not match the required delegation decision contract")

    vibe = policy.get("vibe_coding_standard", {})
    for key in (
        "exploration_required",
        "artifact_required",
        "clean_context_execution_required",
        "three_test_gate_required",
        "trunk_branch_leaf_required",
    ):
        if vibe.get(key) is not True:
            blockers.append(f"vibe_coding_standard.{key} must be true")
    gates = list(vibe.get("verification_gates", []))
    for gate in (
        "Touched code path executed with all touched functions exercised directly when practical",
        "C:\\Users\\anise\\code\\.scratch\\Dev-Management scratch harness may copy relevant production code/config/data to observe actual production behavior",
    ):
        if gate not in gates:
            blockers.append(f"vibe_coding_standard.verification_gates is missing: {gate}")

    touched = policy.get("touched_code_runtime_verification", {})
    for key in (
        "required",
        "exact_code_path_required",
        "exercise_all_touched_functions_when_practical",
        "copy_relevant_production_context_to_scratch_when_needed",
    ):
        if touched.get(key) is not True:
            blockers.append(f"touched_code_runtime_verification.{key} must be true")
    if touched.get("scratch_dir") != r"C:\Users\anise\code\.scratch\Dev-Management":
        blockers.append(r"touched_code_runtime_verification.scratch_dir must be C:\Users\anise\code\.scratch\Dev-Management")
    if touched.get("scratch_dir_outside_repo") is not True:
        blockers.append("touched_code_runtime_verification.scratch_dir_outside_repo must be true")
    if not str(touched.get("claim_rule", "")).strip():
        blockers.append("touched_code_runtime_verification.claim_rule must be declared")

    quality = policy.get("quality_workflow", {})
    if quality.get("sqa") != "process_assurance":
        blockers.append("quality_workflow.sqa must be process_assurance")
    if quality.get("qc") != "product_defect_detection":
        blockers.append("quality_workflow.qc must be product_defect_detection")
    if quality.get("vv") != "verification_and_validation":
        blockers.append("quality_workflow.vv must be verification_and_validation")
    if quality.get("valid_quality_gates") is None:
        blockers.append("quality_workflow.valid_quality_gates must be declared")

    terms = policy.get("quality_terms", {})
    for key, expected in EXPECTED_QUALITY_TERMS.items():
        if terms.get(key) != expected:
            blockers.append(f"quality_terms.{key} must match the global reasoning definition")

    blocked_assertions = policy.get("blocked_assertions", {})
    for key in (
        "skills_as_authority",
        "context7_as_product_domain_source",
        "serena_as_external_docs_source",
        "domain_logic_without_domain_evidence",
        "backend_auth_payment_db_migration_without_all_required_evidence",
        "windows_codex_as_ssot",
        "long_policy_in_app_settings",
    ):
        if blocked_assertions.get(key) is not True:
            blockers.append(f"blocked_assertions.{key} must be true")

    pointer = policy.get("app_settings_pointer", {})
    if not str(pointer.get("exact_text", "")).strip():
        blockers.append("policy app_settings_pointer.exact_text is missing")
    if "The user's explicit instruction is the highest project authority" not in str(pointer.get("exact_text", "")):
        blockers.append("policy app_settings_pointer.exact_text is missing highest user authority text")
    if "Always run the exact code path touched before claiming behavior" not in str(pointer.get("exact_text", "")):
        blockers.append("policy app_settings_pointer.exact_text is missing touched-code runtime verification text")

    fallback_rules = policy.get("fallback_rules", {})
    if not str(fallback_rules.get("missing_context7", "")).strip():
        blockers.append("fallback_rules.missing_context7 must be declared")
    if not str(fallback_rules.get("missing_serena", "")).strip():
        blockers.append("fallback_rules.missing_serena must be declared")
    if not str(fallback_rules.get("missing_domain_rag", "")).strip():
        blockers.append("fallback_rules.missing_domain_rag must be declared")
    if fallback_rules.get("skills_cannot_replace_evidence") is not True:
        blockers.append("fallback_rules.skills_cannot_replace_evidence must be true")
    if fallback_rules.get("fabricated_evidence_forbidden") is not True:
        blockers.append("fallback_rules.fabricated_evidence_forbidden must be true")
    forbidden = set(str(item) for item in policy.get("forbidden", []))
    if "backup_or_temporary_artifact_retention" not in forbidden:
        blockers.append("forbidden must include backup_or_temporary_artifact_retention")
    maintenance = policy.get("codex_app_performance_maintenance", {})
    if maintenance.get("log_retention_days_uncompressed") != 1:
        blockers.append("codex_app_performance_maintenance.log_retention_days_uncompressed must be 1")
    if maintenance.get("compress_older_logs") is not True:
        blockers.append("codex_app_performance_maintenance.compress_older_logs must be true")
    if maintenance.get("scheduled_interval_minutes") != 240:
        blockers.append("codex_app_performance_maintenance.scheduled_interval_minutes must be 240")
    if maintenance.get("run_at_logon") is not True:
        blockers.append("codex_app_performance_maintenance.run_at_logon must be true")
    if maintenance.get("max_serena_roots") != 1:
        blockers.append("codex_app_performance_maintenance.max_serena_roots must be 1")
    if maintenance.get("duplicate_serena_grace_minutes") != 10:
        blockers.append("codex_app_performance_maintenance.duplicate_serena_grace_minutes must be 10")
    if maintenance.get("codex_priority_throttle_default") is not False:
        blockers.append("codex_app_performance_maintenance.codex_priority_throttle_default must be false")
    if maintenance.get("codex_low_power_gpu_default") is not False:
        blockers.append("codex_app_performance_maintenance.codex_low_power_gpu_default must be false")
    hook = policy.get("scorecard_runtime_hook", {})
    if hook.get("required") is not True:
        blockers.append("scorecard_runtime_hook.required must be true")
    if hook.get("event") != "UserPromptSubmit":
        blockers.append("scorecard_runtime_hook.event must be UserPromptSubmit")
    if hook.get("required_each_task_turn") is not True:
        blockers.append("scorecard_runtime_hook.required_each_task_turn must be true")
    if hook.get("user_prompt_throttle_seconds") != 0:
        blockers.append("scorecard_runtime_hook.user_prompt_throttle_seconds must be 0")

    return _check("BLOCKED" if blockers else "PASS", blockers)


def validate_workflow_doc(text: str) -> dict[str, Any]:
    blockers: list[str] = []
    for heading in REQUIRED_HEADINGS:
        if heading not in text:
            blockers.append(f"workflow doc is missing heading: {heading}")
    for phrase in REQUIRED_DOC_PHRASES:
        if phrase not in text:
            blockers.append(f"workflow doc is missing required text: {phrase}")
    return _check("BLOCKED" if blockers else "PASS", blockers)


def validate_setup_doc(policy: dict[str, Any], text: str) -> dict[str, Any]:
    pointer = str(policy.get("app_settings_pointer", {}).get("exact_text", ""))
    blockers: list[str] = []
    if not pointer:
        blockers.append("policy app_settings_pointer.exact_text is missing")
    elif pointer not in text:
        blockers.append("docs/CODEX_APP_USER_SETUP.md must include the exact app_settings_pointer text")
    for phrase in (
        "Agent environment: Windows native",
        "Integrated terminal: PowerShell 7",
        "C:\\Users\\anise\\code\\Dev-Management",
        "sandbox_mode = \"danger-full-access\"",
        "approval_policy = \"never\"",
    ):
        if phrase not in text:
            blockers.append(f"docs/CODEX_APP_USER_SETUP.md is missing required Windows-native setup text: {phrase}")
    return _check("BLOCKED" if blockers else "PASS", blockers)


def evaluate_global_agent_workflow(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    doc_path = root / "docs" / "GLOBAL_AGENT_WORKFLOW.md"
    setup_doc_path = root / "docs" / "CODEX_APP_USER_SETUP.md"
    policy_path = root / "contracts" / "global_agent_workflow_policy.json"

    checks: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    if not doc_path.exists():
        blockers.append("docs/GLOBAL_AGENT_WORKFLOW.md is missing")
    if not policy_path.exists():
        blockers.append("contracts/global_agent_workflow_policy.json is missing")

    policy = load_json(policy_path)
    workflow_text = read_text(doc_path)
    setup_text = read_text(setup_doc_path)

    checks["policy"] = validate_policy(policy) if policy else _check("BLOCKED", ["global agent workflow policy could not be loaded"])
    checks["workflow_doc"] = validate_workflow_doc(workflow_text) if workflow_text else _check("BLOCKED", ["global workflow document could not be loaded"])
    checks["app_settings_pointer"] = validate_setup_doc(policy, setup_text) if setup_text else _check("BLOCKED", ["docs/CODEX_APP_USER_SETUP.md is missing"])

    for payload in checks.values():
        if payload["status"] == "BLOCKED":
            blockers.extend(payload.get("reasons", []))
        elif payload["status"] == "WARN":
            warnings.extend(payload.get("reasons", []))

    status = collapse_status(["BLOCKED" if blockers else "", "WARN" if warnings else ""])
    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "doc_path": str(doc_path),
        "setup_doc_path": str(setup_doc_path),
        "policy_path": str(policy_path),
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Global Agent Workflow Check",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Policy: {report.get('policy_path', '')}",
        f"- Workflow doc: {report.get('doc_path', '')}",
        f"- App setup doc: {report.get('setup_doc_path', '')}",
    ]
    for name, payload in report.get("checks", {}).items():
        lines.extend(["", f"## {name}"])
        lines.append(f"- Status: {payload.get('status', 'WARN')}")
        reasons = payload.get("reasons", [])
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        else:
            lines.append("- PASS")
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], output_file: Path) -> None:
    save_json(output_file, report)
    write_markdown(output_file.with_suffix(".md"), render_markdown(report))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Dev-Management global agent workflow policy and documentation.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_global_agent_workflow(args.repo_root)
    output_file = Path(args.output_file).expanduser().resolve()
    write_reports(report, output_file)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
