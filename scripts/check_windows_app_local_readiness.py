#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.path_authority import canonical_roots, load_path_policy, windows_codex_home
from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import status_exit_code


DEFAULT_CACHE_PATH = ROOT / "reports" / "windows-app-local-readiness.final.json"
DEFAULT_OUTPUT_PATH = DEFAULT_CACHE_PATH
PATH_POLICY = load_path_policy()
WINDOWS_CODEX_HOME = windows_codex_home(PATH_POLICY)
WINDOWS_APP_CONFIG = WINDOWS_CODEX_HOME / "config.toml"
WINDOWS_APP_AGENTS = WINDOWS_CODEX_HOME / "AGENTS.md"
LEGACY_LINUX_MARKERS = ("/home/", "/mnt/", "legacy-linux", "legacy-remote")


def normalize(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip().lower()


def has_legacy_linux_reference(value: str | Path) -> bool:
    text = normalize(value)
    return any(marker.replace("\\", "/").lower() in text for marker in LEGACY_LINUX_MARKERS)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def trusted_project_paths(config_payload: dict[str, Any]) -> list[str]:
    projects = config_payload.get("projects", {}) if isinstance(config_payload.get("projects"), dict) else {}
    return [normalize(key) for key in projects.keys()]


def local_project_status(repo_root: Path, config_payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    roots = canonical_roots(PATH_POLICY)
    expected = [normalize(path) for path in roots.values()]
    trusted = trusted_project_paths(config_payload)
    blockers: list[str] = []
    warnings: list[str] = []
    if not repo_root.exists():
        blockers.append(f"local project root is missing: {repo_root}")
    if has_legacy_linux_reference(repo_root):
        blockers.append(f"local project root still points at legacy Linux/remote runtime: {repo_root}")
    missing = [root for root in expected if not any(path.startswith(root) for path in trusted)]
    if missing:
        blockers.append("Codex config is missing trusted local Windows project roots: " + ", ".join(missing))
    legacy = [path for path in trusted if has_legacy_linux_reference(path)]
    if legacy:
        blockers.append("Codex config still contains legacy Linux/remote project references: " + ", ".join(legacy))
    if not shutil.which("pwsh"):
        blockers.append("PowerShell 7 (pwsh) is not on PATH.")
    if not shutil.which("git"):
        blockers.append("Windows Git is not on PATH.")
    return ("BLOCKED" if blockers else "WARN" if warnings else "PASS", blockers, warnings)


def config_status(config_payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    windows_cfg = config_payload.get("windows", {}) if isinstance(config_payload.get("windows"), dict) else {}
    if str(config_payload.get("approval_policy", "")).strip() != "never":
        blockers.append('approval_policy must be "never" for the selected trusted Windows-native posture.')
    if str(config_payload.get("sandbox_mode", "")).strip() != "danger-full-access":
        blockers.append('sandbox_mode must be "danger-full-access" for the selected trusted Windows-native posture.')
    if str(windows_cfg.get("sandbox", "")).strip() != "elevated":
        blockers.append('windows.sandbox must be "elevated".')
    return ("BLOCKED" if blockers else "WARN" if warnings else "PASS", blockers, warnings)


def evaluate_windows_app_local_readiness(
    repo_root: str | Path | None = None,
    *,
    refresh_windows_ssh: bool = False,
    no_live_windows_ssh_probe: bool = True,
    allow_cache_miss_live_probe: bool = False,
    app_host_listed_in_connections: bool | None = None,
    manual_add_host_worked: bool | None = None,
    app_remote_project_opened: bool | None = None,
    app_remote_project_not_opened: bool | None = None,
    app_remote_project_unobserved: bool | None = None,
    **_compat_kwargs: Any,
) -> dict[str, Any]:
    del refresh_windows_ssh, no_live_windows_ssh_probe, allow_cache_miss_live_probe
    del app_host_listed_in_connections, manual_add_host_worked
    del app_remote_project_opened, app_remote_project_not_opened, app_remote_project_unobserved

    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    config_payload = load_toml(WINDOWS_APP_CONFIG)
    cfg_status, cfg_blockers, cfg_warnings = config_status(config_payload)
    project_status, project_blockers, project_warnings = local_project_status(root, config_payload)
    statuses = [cfg_status, project_status]
    if "BLOCKED" in statuses:
        status = "APP_NOT_READY"
    elif "WARN" in statuses:
        status = "APP_READY_WITH_WARNINGS"
    else:
        status = "APP_READY"
    blocking_reasons = cfg_blockers + project_blockers
    warning_reasons = cfg_warnings + project_warnings
    remaining_user_action = ""
    if status == "APP_NOT_READY":
        remaining_user_action = f"Open Codex App locally on {root} with Windows native agent and normalize {WINDOWS_APP_CONFIG}."
    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "readiness_model": "windows-native-local",
        "local_project_root": str(root),
        "windows_codex_home": str(WINDOWS_CODEX_HOME),
        "windows_app_config": str(WINDOWS_APP_CONFIG),
        "windows_app_agents": str(WINDOWS_APP_AGENTS),
        "trusted_project_paths": trusted_project_paths(config_payload),
        "config_status": cfg_status,
        "local_project_status": project_status,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "remaining_user_action": remaining_user_action,
        "legacy_remote_fields": {"status": "DECOMMISSIONED"},
    }


def evaluate_windows_app_ssh_readiness(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return evaluate_windows_app_local_readiness(*args, **kwargs)


def bootstrap_status(config_path: Path = WINDOWS_APP_CONFIG) -> dict[str, Any]:
    payload = load_toml(config_path)
    status, blockers, warnings = config_status(payload)
    return {
        "status": "PASS" if status == "PASS" else "WARN" if status == "WARN" else "BLOCKED",
        "path": str(config_path),
        "exists": config_path.exists(),
        "reasons": blockers,
        "warnings": warnings,
    }


def reassess_report(report: dict[str, Any], **_compat_kwargs: Any) -> dict[str, Any]:
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Windows App Local Readiness",
        "",
        f"- Status: {report.get('status', 'APP_NOT_READY')}",
        f"- Local project: {report.get('local_project_root', '')}",
        f"- Config: {report.get('windows_app_config', '')}",
    ]
    if report.get("blocking_reasons"):
        lines.extend(["", "## Blocking Reasons"])
        lines.extend(f"- {item}" for item in report.get("blocking_reasons", []))
    if report.get("warning_reasons"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in report.get("warning_reasons", []))
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], output_path: Path) -> None:
    save_json(output_path, report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Codex App Windows-native local project readiness.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--refresh-windows-ssh", action="store_true", help="accepted for compatibility; ignored in Windows-only mode")
    parser.add_argument("--no-live-windows-ssh-probe", action="store_true", help="accepted for compatibility")
    parser.add_argument("--allow-cache-miss-live-probe", action="store_true", help="accepted for compatibility")
    args = parser.parse_args()
    report = evaluate_windows_app_local_readiness(
        args.repo_root,
        refresh_windows_ssh=args.refresh_windows_ssh,
        no_live_windows_ssh_probe=args.no_live_windows_ssh_probe,
        allow_cache_miss_live_probe=args.allow_cache_miss_live_probe,
    )
    output_path = Path(args.output_file).expanduser().resolve()
    write_report(report, output_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['status']}: {report.get('remaining_user_action') or 'Windows-native local readiness passed.'}")
    return status_exit_code("PASS" if report["status"] == "APP_READY" else "WARN" if report["status"] == "APP_READY_WITH_WARNINGS" else "BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
