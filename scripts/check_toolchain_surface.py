#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import load_json, save_json
from devmgmt_runtime.status import collapse_status, status_exit_code
from check_global_runtime import evaluate_global_runtime


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "toolchain-surface.unified-phase.json"
POLICY_PATH = ROOT / "contracts" / "toolchain_policy.json"


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def evaluate_toolchain_surface(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    policy = load_json(root / "contracts" / "toolchain_policy.json", default=load_json(POLICY_PATH, default={}))
    runtime = evaluate_global_runtime(root)
    reports_root = root / "reports"
    usage_path = reports_root / str(policy.get("usage_provenance", {}).get("report_path", "toolchain-usage.session.json")).replace("reports/", "", 1)
    workspace_dependency_report = load_json(reports_root / "workspace-dependency-surface.json", {})
    hooks_report = load_json(reports_root / "hook-readiness.final.json", load_json(reports_root / "hook-readiness.unified-phase.final.json", load_json(reports_root / "hook-readiness.unified-phase.json", {})))
    usage_report = load_json(usage_path, {})
    if isinstance(usage_report, dict):
        if "skills" not in usage_report and isinstance(usage_report.get("skills_used"), list):
            usage_report["skills"] = usage_report.get("skills_used", [])
        if "subagents" not in usage_report and isinstance(usage_report.get("subagents_used"), list):
            usage_report["subagents"] = usage_report.get("subagents_used", [])
    release_report = load_json(reports_root / "codex-app-installed-release-impact.unified-phase.json", {})
    linux_config = load_toml(Path.home() / ".codex" / "config.toml")
    plugins = sorted((linux_config.get("plugins") or {}).keys()) if isinstance(linux_config.get("plugins"), dict) else []
    features = sorted((linux_config.get("features") or {}).keys()) if isinstance(linux_config.get("features"), dict) else []
    mcp_servers = sorted((linux_config.get("mcp_servers") or {}).keys()) if isinstance(linux_config.get("mcp_servers"), dict) else []

    warnings: list[str] = []
    blocked: list[str] = []
    remote_codex_resolution = runtime.get("remote_codex_resolution_status", "PASS")
    remote_codex_resolution_status = (
        str(remote_codex_resolution.get("status", "WARN"))
        if isinstance(remote_codex_resolution, dict)
        else str(remote_codex_resolution)
    )
    if remote_codex_resolution_status == "BLOCKED":
        blocked.append("Linux-native Codex CLI is missing while remote codex still resolves through the Windows launcher path.")

    tool_status = str(workspace_dependency_report.get("tool_status", "UNKNOWN"))
    if tool_status == "DISABLED_IN_APP_SETTINGS" and workspace_dependency_report.get("required_by_workflow"):
        warnings.append("Workspace dependency tools are disabled in app settings even though the workflow says they are required.")
    if tool_status == "DISABLED_IN_APP_SETTINGS" and not workspace_dependency_report.get("required_by_workflow"):
        pass

    projectless = usage_report.get("projectless_chat", {}) if isinstance(usage_report, dict) else {}
    if projectless.get("active") and projectless.get("code_modification_requested") and not projectless.get("repo_root_resolved"):
        blocked.append("Projectless chat requested code modification without a resolved repo root.")

    terminals = usage_report.get("multiple_terminals", {}) if isinstance(usage_report, dict) else {}
    if terminals.get("path_mismatch"):
        warnings.append("Multiple terminal PATH mismatch is present.")
    if str(terminals.get("selected_execution_terminal_status", "")).upper() == "CONTAMINATED":
        blocked.append("Selected execution terminal is contaminated.")

    if hooks_report and str(hooks_report.get("status", "PASS")) == "WARN":
        warnings.append("Hook readiness is degraded or advisory-only.")
    if hooks_report and hooks_report.get("hook_only_enforcement_claim") is True:
        blocked.append("Hooks are being used as the sole enforcement surface.")

    required_usage_keys = [str(item) for item in policy.get("usage_provenance", {}).get("required_keys", [])]
    missing_usage_keys = [key for key in required_usage_keys if key not in usage_report]
    if not usage_report:
        warnings.append("Skill, subagent, plugin, or workspace dependency provenance was not recorded for this session.")
    elif missing_usage_keys:
        warnings.append(f"Toolchain usage provenance is missing keys: {', '.join(missing_usage_keys)}")

    if not release_report:
        warnings.append("Installed Codex App release evidence was not found.")

    status = collapse_status(["BLOCKED" if blocked else "", "WARN" if warnings else ""])
    return {
        "status": status,
        "runtime_status": runtime.get("overall_status", "WARN"),
        "remote_codex_resolution_status": remote_codex_resolution_status,
        "workspace_dependency_tools": tool_status,
        "workspace_dependency_report": workspace_dependency_report,
        "installed_app_release": release_report,
        "plugins": plugins,
        "features": features,
        "mcp_servers": mcp_servers,
        "policy_path": str(root / "contracts" / "toolchain_policy.json"),
        "session_usage_provenance_path": str(usage_path),
        "session_usage_provenance": usage_report,
        "warnings": warnings,
        "blocked_reasons": blocked,
    }


def render_markdown(report: dict[str, Any]) -> str:
    plugins = report.get("plugins", [])
    if not isinstance(plugins, list):
        plugins = []
    features = report.get("features", [])
    if not isinstance(features, list):
        features = []
    mcp_servers = report.get("mcp_servers", [])
    if not isinstance(mcp_servers, list):
        mcp_servers = []
    lines = [
        "# Toolchain Surface",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Workspace dependency tools: {report.get('workspace_dependency_tools', 'UNKNOWN')}",
        f"- Plugins: {', '.join(str(item) for item in plugins) or '(none)'}",
        f"- Features: {', '.join(str(item) for item in features) or '(none)'}",
        f"- MCP servers: {', '.join(str(item) for item in mcp_servers) or '(none)'}",
    ]
    if report.get("blocked_reasons"):
        lines.extend(["", "## Blocked Reasons"])
        lines.extend(f"- {item}" for item in report["blocked_reasons"])
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in report["warnings"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Codex feature flags, plugins, MCP surface, workspace dependencies, hooks, and remote codex readiness.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate_toolchain_surface(args.repo_root)
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
