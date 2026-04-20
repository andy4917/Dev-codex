#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "score-layer.unified-phase.json"


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def collapse_status(values: list[str]) -> str:
    items = [value for value in values if value]
    if any(value == "BLOCKED" for value in items):
        return "BLOCKED"
    if any(value == "WARN" for value in items):
        return "WARN"
    return "PASS"


def load_first_report(reports: Path, candidates: list[str]) -> tuple[dict[str, Any], str, bool]:
    for candidate in candidates:
        path = reports / candidate
        if path.exists():
            payload = load_json(path, default={})
            return (payload if isinstance(payload, dict) else {}, str(path), False)
    return ({}, str(reports / candidates[0]), True)


def evaluate_score_layer(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    reports = root / "reports"
    config, config_source, config_missing = load_first_report(reports, ["config-provenance.unified-phase.final.json", "config-provenance.unified-phase.json"])
    runtime, runtime_source, runtime_missing = load_first_report(reports, ["global-runtime.unified-phase.final.json", "global-runtime.unified-phase.json", "global-runtime.json"])
    startup, startup_source, startup_missing = load_first_report(reports, ["startup-workflow.unified-phase.final.json", "startup-workflow.json"])
    toolchain, toolchain_source, toolchain_missing = load_first_report(reports, ["toolchain-surface.unified-phase.final.json", "toolchain-surface.unified-phase.json"])
    hooks, hooks_source, hooks_missing = load_first_report(reports, ["hook-readiness.unified-phase.final.json", "hook-readiness.unified-phase.json"])
    audit, audit_source, audit_missing = load_first_report(reports, ["audit.unified-phase.final.json", "audit.final.json", "audit.post-export.json"])
    hygiene, hygiene_source, hygiene_missing = load_first_report(reports, ["artifact-hygiene.unified-phase.final.json", "artifact-hygiene.unified-phase.json"])
    disqualifiers: list[str] = []
    warnings: list[str] = []
    missing_reports = {
        "config_provenance": config_missing,
        "global_runtime": runtime_missing,
        "startup_workflow": startup_missing,
        "toolchain_surface": toolchain_missing,
        "hook_readiness": hooks_missing,
        "audit": audit_missing,
        "artifact_hygiene": hygiene_missing,
    }
    for label, missing in missing_reports.items():
        if missing:
            disqualifiers.append(f"missing required evidence report: {label}")
    config_gate_status = str(config.get("gate_status", config.get("status", "PASS")))
    runtime_overall_status = str(runtime.get("overall_status", runtime.get("status", "WARN")))
    canonical_execution_status = str(runtime.get("canonical_execution_status", "WARN"))
    hook_status = str(hooks.get("status", "PASS"))
    hygiene_status = str(hygiene.get("status", "PASS"))
    audit_status = str(audit.get("gate_status", audit.get("status", "PASS")))
    if config_gate_status == "BLOCKED":
        disqualifiers.append("generated mirror self-feed or stale active config")
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
    if audit_status in {"BLOCKED", "FAIL"}:
        disqualifiers.append("workspace audit final gate blocked")
    if hygiene_status == "WARN":
        warnings.append("artifact hygiene still has stale drafts, duplicate remediation reports, or transient artifacts")
    if hook_status == "WARN":
        warnings.append("hook readiness is degraded and remains advisory only")
    if str(startup.get("activation", {}).get("status", startup.get("status", "PASS"))) == "BLOCKED":
        warnings.append("Serena activation remains blocked for general code modification")
    if str(runtime.get("client_surface_status", "PASS")) == "WARN":
        warnings.append("client surface PATH contamination remains a warning")
    if audit_status == "WARN":
        warnings.append("workspace audit still reports warnings or blockers")
    status = collapse_status(["BLOCKED" if disqualifiers else "", "WARN" if warnings else ""])
    base_score = 100
    score = max(0, base_score - (len(disqualifiers) * 40) - (len(warnings) * 5))
    return {
        "status": status,
        "numeric_score": score,
        "disqualifiers": disqualifiers,
        "warnings": warnings,
        "report_sources": {
            "config_provenance": config_source,
            "global_runtime": runtime_source,
            "startup_workflow": startup_source,
            "toolchain_surface": toolchain_source,
            "hook_readiness": hooks_source,
            "audit": audit_source,
            "artifact_hygiene": hygiene_source,
        },
        "missing_reports": missing_reports,
        "cleanup_actions": hygiene.get("transient_files", []),
        "required_tests": [
            "python3 -m unittest tests.test_audit_workspace_contract tests.test_repair_codex_desktop_runtime tests.test_verify_migration_evidence tests.test_check_startup_workflow",
            "python3 -m unittest tests.test_check_global_runtime tests.test_check_agent_instruction tests.test_git_surface",
            "python3 -m unittest tests.test_check_config_provenance tests.test_check_toolchain_surface tests.test_check_hook_readiness tests.test_windows_app_ssh_readiness tests.test_artifact_hygiene tests.test_score_layer",
        ],
        "evidence_files": [str(path) for path in [reports / "config-provenance.unified-phase.final.json", reports / "toolchain-surface.unified-phase.final.json", reports / "artifact-hygiene.unified-phase.final.json", reports / "global-runtime.unified-phase.final.json", reports / "audit.unified-phase.final.json"] if path.exists()],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Score Layer", "", f"- Status: {report['status']}", f"- Numeric score: {report['numeric_score']}"]
    if report.get("missing_reports"):
        missing = [name for name, missing in report["missing_reports"].items() if missing]
        lines.append(f"- Missing reports: {', '.join(missing) if missing else '(none)'}")
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
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate_score_layer(args.repo_root)
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
