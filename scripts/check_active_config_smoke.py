#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_config_provenance import header_status, load_policy, windows_policy_surface_report
from devmgmt_runtime.authority import canonical_authority_path, load_authority
from devmgmt_runtime.paths import runtime_paths
from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "active-config-smoke.unified-phase.json"


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def evaluate_active_config_smoke(repo_root: str | Path | None = None) -> dict[str, Any]:
    authority = load_authority(repo_root)
    paths = runtime_paths(authority)
    repo_authority_path = canonical_authority_path(authority, repo_root)
    policy = load_policy(repo_root)
    linux_config = paths["linux_config"]
    blockers: list[str] = []
    warnings: list[str] = []

    header = header_status(linux_config, authority, repo_authority_path, policy)
    parsed: dict[str, Any] = {}
    parse_error = ""
    if not linux_config.exists():
        blockers.append(f"Linux active generated config is missing: {linux_config}")
    else:
        try:
            parsed = load_toml(linux_config)
        except tomllib.TOMLDecodeError as exc:
            parse_error = str(exc)
            blockers.append(f"Linux active generated config is not valid TOML: {exc}")

    features = parsed.get("features", {}) if isinstance(parsed.get("features"), dict) else {}
    mcp_servers = parsed.get("mcp_servers", {}) if isinstance(parsed.get("mcp_servers"), dict) else {}
    approval_policy = str(parsed.get("approval_policy", "")).strip()
    sandbox_mode = str(parsed.get("sandbox_mode", "")).strip()
    shell_zsh_fork = features.get("shell_zsh_fork")

    if linux_config.exists() and header["status"] != "PASS":
        blockers.extend(f"{linux_config}: {reason}" for reason in header.get("reasons", []))
    if linux_config.exists() and not parse_error:
        if approval_policy == "never":
            blockers.append("Linux active generated config still contains approval_policy=never")
        if sandbox_mode == "danger-full-access":
            blockers.append("Linux active generated config still contains sandbox_mode=danger-full-access")
        if not isinstance(mcp_servers.get("context7"), dict):
            blockers.append("Linux active generated config is missing the canonical Context7 MCP block")
        if not isinstance(mcp_servers.get("serena"), dict):
            blockers.append("Linux active generated config is missing the canonical Serena MCP block")
        if shell_zsh_fork is not True:
            blockers.append("Linux active generated config must keep features.shell_zsh_fork=true")

    windows_policy_surface = windows_policy_surface_report(paths, authority)
    blockers.extend(
        str(item.get("reason", ""))
        for item in windows_policy_surface.get("findings", [])
        if str(item.get("classification", "")).strip() == "known_generated_cleanup_candidate"
    )
    warnings.extend(
        str(item.get("reason", ""))
        for item in windows_policy_surface.get("findings", [])
        if str(item.get("classification", "")).strip() == "unknown_policy_surface"
    )

    windows_app_evidence_status = "PASS" if paths["observed_windows_codex_home"].exists() else "WARN"
    if windows_app_evidence_status != "PASS":
        warnings.append("Windows Codex App state was not observed; app evidence is missing on this host.")

    status = collapse_status(["BLOCKED" if blockers else "", "WARN" if warnings else ""])
    return {
        "status": status,
        "gate_status": "BLOCKED" if blockers else "PASS",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "authority_path": str(repo_authority_path),
        "linux_active_config": {
            "path": str(linux_config),
            "exists": linux_config.exists(),
            "parse_error": parse_error,
            "approval_policy": approval_policy,
            "sandbox_mode": sandbox_mode,
            "shell_zsh_fork": shell_zsh_fork,
            "canonical_mcp_blocks_present": {
                "context7": isinstance(mcp_servers.get("context7"), dict),
                "serena": isinstance(mcp_servers.get("serena"), dict),
            },
            "provenance_header": header,
        },
        "windows_policy_surface_status": windows_policy_surface.get("status", "PASS"),
        "windows_policy_surface_findings": windows_policy_surface.get("findings", []),
        "known_generated_windows_policy_files_deleted": [],
        "unknown_windows_policy_files_blocking": windows_policy_surface.get("unknown_blocking", []),
        "unknown_windows_policy_files_observed": windows_policy_surface.get("unknown_observed", []),
        "windows_app_evidence_status": windows_app_evidence_status,
        "windows_app_evidence_path": str(paths["observed_windows_codex_home"]),
        "blockers": blockers,
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    active = report.get("linux_active_config", {}) if isinstance(report.get("linux_active_config"), dict) else {}
    mcp = active.get("canonical_mcp_blocks_present", {}) if isinstance(active.get("canonical_mcp_blocks_present"), dict) else {}
    lines = [
        "# Active Config Smoke",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Linux active config: {active.get('path', '')}",
        f"- Provenance header: {active.get('provenance_header', {}).get('status', 'WARN') if isinstance(active.get('provenance_header'), dict) else 'WARN'}",
        f"- TOML parse error: {active.get('parse_error', '') or '(none)'}",
        f"- Approval policy: {active.get('approval_policy', '')}",
        f"- Sandbox mode: {active.get('sandbox_mode', '')}",
        f"- shell_zsh_fork: {active.get('shell_zsh_fork', '')}",
        f"- Context7 MCP block: {str(mcp.get('context7', False)).lower()}",
        f"- Serena MCP block: {str(mcp.get('serena', False)).lower()}",
        f"- Windows policy surface: {report.get('windows_policy_surface_status', 'WARN')}",
        f"- Windows app evidence: {report.get('windows_app_evidence_status', 'WARN')}",
    ]
    if report.get("blockers"):
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in report["blockers"])
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in report["warnings"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a static smoke test against the Linux active config and Windows bootstrap boundary.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_active_config_smoke(args.repo_root)
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
