#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any

from check_global_runtime import evaluate_global_runtime


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "toolchain-surface.unified-phase.json"


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collapse_status(values: list[str]) -> str:
    values = [value for value in values if value]
    if any(value == "BLOCKED" for value in values):
        return "BLOCKED"
    if any(value == "WARN" for value in values):
        return "WARN"
    return "PASS"


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def evaluate_toolchain_surface(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    runtime = evaluate_global_runtime(root)
    workspace_dependency_report = load_json(root / "reports" / "workspace-dependency-surface.json", {})
    hooks_report = load_json(root / "reports" / "hook-readiness.unified-phase.json", {})
    usage_report = load_json(root / "reports" / "toolchain-usage.session.json", {})
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
    if hooks_report and str(hooks_report.get("status", "PASS")) == "WARN":
        warnings.append("Hook readiness is degraded or advisory-only.")
    if not usage_report:
        warnings.append("Skill, subagent, plugin, or workspace dependency provenance was not recorded for this session.")
    status = collapse_status(["BLOCKED" if blocked else "", "WARN" if warnings else ""])
    return {
        "status": status,
        "runtime_status": runtime.get("overall_status", "WARN"),
        "remote_codex_resolution_status": remote_codex_resolution_status,
        "workspace_dependency_tools": tool_status,
        "plugins": plugins,
        "features": features,
        "mcp_servers": mcp_servers,
        "session_usage_provenance": usage_report,
        "warnings": warnings,
        "blocked_reasons": blocked,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Toolchain Surface", "", f"- Status: {report['status']}", f"- Workspace dependency tools: {report['workspace_dependency_tools']}", f"- Plugins: {', '.join(report['plugins']) or '(none)'}", f"- Features: {', '.join(report['features']) or '(none)'}", f"- MCP servers: {', '.join(report['mcp_servers']) or '(none)'}"]
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
