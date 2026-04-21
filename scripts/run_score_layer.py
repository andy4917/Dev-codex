#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import load_first_report, load_json, save_json
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "score-layer.unified-phase.json"
PURPOSE_CHOICES = ("code-modification", "app-usability")
SCORE_POLICY_PATH = ROOT / "contracts" / "score_policy.json"


def load_score_policy() -> dict[str, Any]:
    if not SCORE_POLICY_PATH.exists():
        return {}
    payload = load_json(SCORE_POLICY_PATH, default={})
    return payload if isinstance(payload, dict) else {}


def report_candidates(purpose: str, *candidates: str) -> list[str]:
    ordered = list(candidates)
    if purpose == "code-modification":
        root_cause_candidates = []
        for candidate in ordered:
            if candidate.endswith(".final.json"):
                root_cause_candidates.append(candidate.replace(".final.json", ".root-cause-removal.final.json"))
        ordered = root_cause_candidates + ordered
    return ordered


def evaluate_score_layer(repo_root: str | Path | None = None, *, purpose: str = "code-modification") -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    reports = root / "reports"
    config, config_source, config_missing = load_first_report(reports, report_candidates(purpose, "config-provenance.final.json", "config-provenance.unified-phase.final.json", "config-provenance.unified-phase.json"))
    active_config, active_config_source, active_config_missing = load_first_report(reports, report_candidates(purpose, "active-config-smoke.final.json", "active-config-smoke.unified-phase.final.json", "active-config-smoke.unified-phase.json"))
    runtime, runtime_source, runtime_missing = load_first_report(reports, report_candidates(purpose, "global-runtime.final.json", "global-runtime.unified-phase.final.json", "global-runtime.unified-phase.json", "global-runtime.json"))
    startup, startup_source, startup_missing = load_first_report(reports, report_candidates(purpose, "startup-workflow.final.json", "startup-workflow.unified-phase.final.json", "startup-workflow.json"))
    toolchain, toolchain_source, toolchain_missing = load_first_report(reports, report_candidates(purpose, "toolchain-surface.final.json", "toolchain-surface.unified-phase.final.json", "toolchain-surface.unified-phase.json"))
    hooks, hooks_source, hooks_missing = load_first_report(reports, report_candidates(purpose, "hook-readiness.final.json", "hook-readiness.unified-phase.final.json", "hook-readiness.unified-phase.json"))
    audit, audit_source, audit_missing = load_first_report(reports, report_candidates(purpose, "audit.final.json", "audit.unified-phase.final.json", "audit.post-export.json"))
    hygiene, hygiene_source, hygiene_missing = load_first_report(reports, report_candidates(purpose, "artifact-hygiene.final.json", "artifact-hygiene.unified-phase.final.json", "artifact-hygiene.unified-phase.json"))
    git_surface, git_surface_source, git_surface_missing = load_first_report(reports, report_candidates(purpose, "git-surface.final.json", "git-surface.unified-phase.final.json", "git-surface.json"))
    score_policy = load_score_policy()

    disqualifiers: list[str] = []
    warnings: list[str] = []
    missing_reports = {
        "config_provenance": config_missing,
        "active_config_smoke": active_config_missing,
        "global_runtime": runtime_missing,
        "startup_workflow": startup_missing,
        "toolchain_surface": toolchain_missing,
        "hook_readiness": hooks_missing,
        "audit": audit_missing,
        "artifact_hygiene": hygiene_missing,
        "git_surface": git_surface_missing,
    }
    for label, missing in missing_reports.items():
        if missing:
            disqualifiers.append(f"missing required evidence report: {label}")

    config_gate_status = str(config.get("gate_status", config.get("status", "PASS")))
    active_config_gate_status = str(active_config.get("gate_status", active_config.get("status", "PASS")))
    runtime_overall_status = str(runtime.get("overall_status", runtime.get("status", "WARN")))
    canonical_execution_status = str(runtime.get("canonical_execution_status", "WARN"))
    hook_status = str(hooks.get("status", "PASS"))
    hygiene_status = str(hygiene.get("status", "PASS"))
    audit_status = str(audit.get("gate_status", audit.get("status", "PASS")))
    startup_status = str(startup.get("status", "PASS"))

    if config_gate_status == "BLOCKED":
        disqualifiers.append("Linux generated config provenance or Windows policy surface is blocked")
    if active_config_gate_status == "BLOCKED":
        disqualifiers.append("active config smoke is blocked")
    if runtime_overall_status == "BLOCKED" or canonical_execution_status == "BLOCKED":
        disqualifiers.append("canonical runtime readiness is blocked")

    remote_codex_resolution = runtime.get("remote_codex_resolution_status", "PASS")
    remote_codex_resolution_status = (
        str(remote_codex_resolution.get("status", "WARN"))
        if isinstance(remote_codex_resolution, dict)
        else str(remote_codex_resolution)
    )
    if remote_codex_resolution_status == "BLOCKED":
        disqualifiers.append("forbidden Windows launcher remains the primary remote codex resolution")
    if hooks.get("hook_only_enforcement_claim") is True:
        disqualifiers.append("hook-only enforcement claim")
    if hook_status == "BLOCKED":
        disqualifiers.append("hook readiness is blocked")
    if str(toolchain.get("status", "PASS")) == "BLOCKED":
        disqualifiers.append("toolchain surface blocked")
    if hygiene_status == "BLOCKED":
        disqualifiers.append("artifact hygiene is blocked")
    if startup_status == "BLOCKED":
        disqualifiers.append("startup gate remains blocked for the requested purpose")
    if audit_status in {"BLOCKED", "FAIL"}:
        disqualifiers.append("workspace audit final gate blocked")
    if str(git_surface.get("status", "PASS")) == "BLOCKED":
        disqualifiers.append("git surface reports a branch lock conflict or blocked worktree condition")

    if hygiene_status == "WARN":
        warnings.append("artifact hygiene still has stale drafts, duplicate remediation reports, or transient artifacts")
    if hook_status == "WARN":
        warnings.append("hook readiness is degraded and remains advisory only")
    if startup_status == "WARN":
        if purpose == "app-usability":
            warnings.append("Serena startup still blocks general code modification, but app usability can proceed with warnings")
        else:
            warnings.append("startup gate is degraded")
    if str(runtime.get("client_surface_status", "PASS")) == "WARN":
        warnings.append("client surface PATH contamination remains a warning")
    if active_config_gate_status == "WARN":
        warnings.append("active config smoke reported warnings")
    if audit_status == "WARN":
        warnings.append("workspace audit still reports warnings")
    if str(git_surface.get("status", "PASS")) == "WARN":
        warnings.append("git surface still reports stale worktrees, drift, or repo-local guard proposals")

    status = collapse_status(["BLOCKED" if disqualifiers else "", "WARN" if warnings else ""])
    base_score = 100
    score = max(0, base_score - (len(disqualifiers) * 25) - (len(warnings) * 5))
    return {
        "purpose": purpose,
        "status": status,
        "numeric_score": score,
        "disqualifiers": disqualifiers,
        "warnings": warnings,
        "cleanup_actions": hygiene.get("cleanup_actions", []),
        "required_tests": [
            "python3 -m unittest tests.test_audit_workspace_contract tests.test_repair_codex_desktop_runtime tests.test_verify_migration_evidence tests.test_check_startup_workflow",
            "python3 -m unittest tests.test_check_global_runtime tests.test_check_agent_instruction tests.test_git_surface",
            "python3 -m unittest tests.test_activate_canonical_runtime tests.test_run_canonical_command tests.test_repair_serena_startup",
            "python3 -m unittest tests.test_check_config_provenance tests.test_check_active_config_smoke tests.test_check_toolchain_surface tests.test_check_hook_readiness tests.test_codex_app_usability tests.test_app_thread_worktree_policy tests.test_score_layer",
        ],
        "report_sources": {
            "config_provenance": config_source,
            "active_config_smoke": active_config_source,
            "global_runtime": runtime_source,
            "startup_workflow": startup_source,
            "toolchain_surface": toolchain_source,
            "hook_readiness": hooks_source,
            "audit": audit_source,
            "artifact_hygiene": hygiene_source,
            "git_surface": git_surface_source,
        },
        "evidence_files": [config_source, active_config_source, runtime_source, startup_source, toolchain_source, hooks_source, audit_source, hygiene_source, git_surface_source],
        "score_policy_path": str(SCORE_POLICY_PATH),
        "worktree_policy": score_policy.get("worktree_policy", {}),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Score Layer",
        "",
        f"- Purpose: {report.get('purpose', 'app-usability')}",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Numeric score: {report.get('numeric_score', 0)}",
    ]
    if report.get("disqualifiers"):
        lines.extend(["", "## Disqualifiers"])
        lines.extend(f"- {item}" for item in report["disqualifiers"])
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in report["warnings"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine provenance, runtime, startup, toolchain, hook, audit, and hygiene reports into a score-layer verdict.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--purpose", choices=PURPOSE_CHOICES, default="code-modification")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate_score_layer(args.repo_root, purpose=args.purpose)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
