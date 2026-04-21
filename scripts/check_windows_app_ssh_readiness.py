#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.paths import canonical_surface
from devmgmt_runtime.reports import load_json, save_json
from devmgmt_runtime.status import collapse_status, status_exit_code
from devmgmt_runtime.subprocess_safe import run_powershell


DEFAULT_CACHE_PATH = ROOT / "reports" / "windows-app-ssh-remote-readiness.final.json"
DEFAULT_OUTPUT_PATH = DEFAULT_CACHE_PATH
AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
WINDOWS_SSH_CONFIG = Path("/mnt/c/Users/anise/.ssh/config")
WSL_SSH_CONFIG = Path("/home/andy4917/.ssh/config")
WSL_SSH_MANAGED_CONFIG = Path("/home/andy4917/.ssh/config.d/dev-management.conf")
MARKER_BEGIN = "# BEGIN DEV-MANAGEMENT devmgmt-wsl"
MARKER_END = "# END DEV-MANAGEMENT devmgmt-wsl"
DEFAULT_CACHE_TTL_SECONDS = 3600


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def run_windows_ssh_version() -> dict[str, Any]:
    return run_powershell('& "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -V', set_userprofile=False)


def run_windows_ssh(host_alias: str) -> dict[str, Any]:
    return run_powershell(f'& "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -o BatchMode=yes {host_alias} hostname')


def choose_identity_file() -> str:
    for candidate in ("~/.ssh/devmgmt_wsl_ed25519", "~/.ssh/codex_wsl_ed25519"):
        if (WINDOWS_SSH_CONFIG.parent / Path(candidate).name).exists():
            return candidate
    return "~/.ssh/devmgmt_wsl_ed25519"


def render_alias(host_alias: str) -> str:
    return "\n".join([
        MARKER_BEGIN,
        f"Host {host_alias}",
        "  HostName localhost",
        "  Port 22",
        "  User andy4917",
        f"  IdentityFile {choose_identity_file()}",
        "  IdentitiesOnly yes",
        MARKER_END,
        "",
    ])


def ensure_alias(host_alias: str, *, apply: bool) -> tuple[bool, list[str]]:
    text = read_text(WINDOWS_SSH_CONFIG)
    if f"Host {host_alias}" in text:
        return False, []
    backups: list[str] = []
    if apply:
        WINDOWS_SSH_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if WINDOWS_SSH_CONFIG.exists():
            backup = WINDOWS_SSH_CONFIG.with_suffix(f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(WINDOWS_SSH_CONFIG, backup)
            backups.append(str(backup))
        updated = text.rstrip() + ("\n\n" if text.strip() else "") + render_alias(host_alias)
        WINDOWS_SSH_CONFIG.write_text(updated, encoding="utf-8")
    return True, backups


def simple_user_instruction(status: str, host_alias: str) -> str:
    if status == "PASS":
        return f"Open Codex App Settings > Connections and select {host_alias}."
    if status == "WARN":
        return f"Open Codex App Settings > Connections, verify {host_alias}, then retry the remote connection."
    return f"Add or repair the Windows user SSH alias for {host_alias}, then reopen Codex App Settings > Connections."


def build_live_report(
    repo_root: str | Path | None = None,
    *,
    apply_user_level: bool = False,
) -> dict[str, Any]:
    authority = load_authority(repo_root, authority_path=AUTHORITY_PATH)
    surface = canonical_surface(authority)
    host_alias = str(surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    alias_present = f"Host {host_alias}" in read_text(WINDOWS_SSH_CONFIG)
    backups: list[str] = []
    changed = False
    if apply_user_level and not alias_present:
        changed, backups = ensure_alias(host_alias, apply=True)
        alias_present = f"Host {host_alias}" in read_text(WINDOWS_SSH_CONFIG)
    ssh_version = run_windows_ssh_version()
    probe = run_windows_ssh(host_alias) if alias_present else {"ok": False, "exit_code": None, "stdout": "", "stderr": "alias missing", "command": ""}
    status = collapse_status([
        "PASS" if alias_present and bool(probe.get("ok")) else "",
        "WARN" if alias_present and not bool(probe.get("ok")) else "",
        "BLOCKED" if not alias_present else "",
    ])
    warnings = [] if status == "PASS" else ["Windows app-side SSH alias is missing or Windows ssh.exe cannot yet reach devmgmt-wsl."]
    return {
        "status": status,
        "scope": "app-usability",
        "host_alias": host_alias,
        "windows_ssh_dir": str(WINDOWS_SSH_CONFIG.parent),
        "windows_ssh_config": str(WINDOWS_SSH_CONFIG),
        "wsl_user_ssh_config": str(WSL_SSH_CONFIG),
        "wsl_managed_ssh_config": str(WSL_SSH_MANAGED_CONFIG),
        "alias_present": alias_present,
        "identity_file": choose_identity_file(),
        "ssh_exe_version": ssh_version,
        "probe": probe,
        "applied": changed,
        "backups": backups,
        "repairable_user_level": True,
        "system_config_modified": False,
        "windows_path_modified": False,
        "simple_user_instruction": simple_user_instruction(status, host_alias),
        "user_action_required": [] if status == "PASS" else [simple_user_instruction(status, host_alias)],
        "warnings": warnings,
    }


def _cache_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "cache_status": "missing", "cache_age_seconds": None}
    age_seconds = max(0.0, time.time() - path.stat().st_mtime)
    return {
        "exists": True,
        "cache_status": "fresh",
        "cache_age_seconds": age_seconds,
    }


def _decorate_report(
    report: dict[str, Any],
    *,
    probe_source: str,
    cache_path: Path,
    cache_status: str,
    cache_age_seconds: float | None,
    live_probe_permitted: bool,
) -> dict[str, Any]:
    payload = dict(report)
    warnings = list(payload.get("warnings", [])) if isinstance(payload.get("warnings"), list) else []
    user_actions = list(payload.get("user_action_required", [])) if isinstance(payload.get("user_action_required"), list) else []
    host_alias = str(payload.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    refresh_action = (
        "Run `python3 scripts/check_windows_app_ssh_readiness.py --refresh-windows-ssh --json` to refresh Windows SSH readiness."
    )
    if cache_status == "stale":
        warnings.append("Cached Windows SSH readiness is stale; run an explicit refresh instead of relying on repeated automatic probes.")
        if refresh_action not in user_actions:
            user_actions.append(refresh_action)
        payload["status"] = "WARN"
    elif cache_status == "missing" and probe_source == "cached_report":
        warnings.append("No cached Windows SSH readiness report is available; run an explicit refresh to capture live Windows ssh.exe evidence.")
        if refresh_action not in user_actions:
            user_actions.append(refresh_action)
        payload["status"] = "WARN"
    payload["simple_user_instruction"] = simple_user_instruction(str(payload.get("status", "WARN")), host_alias)
    payload["warnings"] = warnings
    payload["user_action_required"] = user_actions
    payload["probe_source"] = probe_source
    payload["cache_status"] = cache_status
    payload["cache_path"] = str(cache_path)
    payload["cache_age_seconds"] = cache_age_seconds
    payload["live_probe_permitted"] = live_probe_permitted
    return payload


def _missing_cache_report(repo_root: str | Path | None = None) -> dict[str, Any]:
    authority = load_authority(repo_root, authority_path=AUTHORITY_PATH)
    surface = canonical_surface(authority)
    host_alias = str(surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    alias_present = f"Host {host_alias}" in read_text(WINDOWS_SSH_CONFIG)
    status = "WARN"
    return {
        "status": status,
        "scope": "app-usability",
        "host_alias": host_alias,
        "windows_ssh_dir": str(WINDOWS_SSH_CONFIG.parent),
        "windows_ssh_config": str(WINDOWS_SSH_CONFIG),
        "wsl_user_ssh_config": str(WSL_SSH_CONFIG),
        "wsl_managed_ssh_config": str(WSL_SSH_MANAGED_CONFIG),
        "alias_present": alias_present,
        "identity_file": choose_identity_file(),
        "ssh_exe_version": {},
        "probe": {"ok": False, "exit_code": None, "stdout": "", "stderr": "cache missing", "command": ""},
        "applied": False,
        "backups": [],
        "repairable_user_level": True,
        "system_config_modified": False,
        "windows_path_modified": False,
        "simple_user_instruction": simple_user_instruction(status, host_alias),
        "user_action_required": [],
        "warnings": [],
    }


def _persist_cache(report: dict[str, Any], cache_path: Path) -> None:
    save_json(cache_path, report)
    cache_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")


def evaluate_windows_app_ssh_readiness(
    repo_root: str | Path | None = None,
    *,
    apply_user_level: bool = False,
    refresh_windows_ssh: bool = False,
    windows_ssh_readiness_report: str | Path | None = None,
    no_live_windows_ssh_probe: bool = False,
    allow_cache_miss_live_probe: bool = False,
    injected_readiness: dict[str, Any] | None = None,
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    cache_path = Path(windows_ssh_readiness_report).expanduser().resolve() if windows_ssh_readiness_report else DEFAULT_CACHE_PATH
    live_probe_permitted = (refresh_windows_ssh or allow_cache_miss_live_probe) and not no_live_windows_ssh_probe
    if injected_readiness is not None:
        return _decorate_report(
            injected_readiness,
            probe_source="injected",
            cache_path=cache_path,
            cache_status="fresh",
            cache_age_seconds=0.0,
            live_probe_permitted=False,
        )

    if refresh_windows_ssh and no_live_windows_ssh_probe:
        raise ValueError("--refresh-windows-ssh cannot be combined with --no-live-windows-ssh-probe")

    if refresh_windows_ssh:
        live = build_live_report(repo_root, apply_user_level=apply_user_level)
        report = _decorate_report(
            live,
            probe_source="live_probe",
            cache_path=cache_path,
            cache_status="fresh",
            cache_age_seconds=0.0,
            live_probe_permitted=True,
        )
        _persist_cache(report, cache_path)
        return report

    metadata = _cache_metadata(cache_path)
    if metadata["exists"]:
        cached = load_json(cache_path, default={})
        cache_status = "fresh" if float(metadata["cache_age_seconds"] or 0.0) <= float(cache_ttl_seconds) else "stale"
        return _decorate_report(
            cached if isinstance(cached, dict) else {},
            probe_source="cached_report",
            cache_path=cache_path,
            cache_status=cache_status,
            cache_age_seconds=metadata["cache_age_seconds"],
            live_probe_permitted=live_probe_permitted,
        )

    if live_probe_permitted:
        live = build_live_report(repo_root, apply_user_level=apply_user_level)
        report = _decorate_report(
            live,
            probe_source="live_probe",
            cache_path=cache_path,
            cache_status="fresh",
            cache_age_seconds=0.0,
            live_probe_permitted=True,
        )
        _persist_cache(report, cache_path)
        return report

    return _decorate_report(
        _missing_cache_report(repo_root),
        probe_source="cached_report",
        cache_path=cache_path,
        cache_status="missing",
        cache_age_seconds=None,
        live_probe_permitted=False,
    )


def render_markdown(report: dict[str, Any]) -> str:
    probe = report.get("probe", {}) if isinstance(report.get("probe"), dict) else {}
    ssh_version = report.get("ssh_exe_version", {}) if isinstance(report.get("ssh_exe_version"), dict) else {}
    lines = [
        "# Windows App SSH Readiness",
        "",
        f"- Status: {report['status']}",
        f"- Probe source: {report.get('probe_source', 'live_probe')}",
        f"- Cache status: {report.get('cache_status', 'fresh')}",
        f"- Cache path: {report.get('cache_path', str(DEFAULT_CACHE_PATH))}",
        f"- Alias present: {str(report.get('alias_present', False)).lower()}",
        f"- Identity file: {report.get('identity_file', '~/.ssh/devmgmt_wsl_ed25519')}",
        f"- Probe ok: {str(probe.get('ok', False)).lower()}",
        f"- Windows ssh.exe version probe ok: {str(ssh_version.get('ok', False)).lower()}",
        f"- User action: {report.get('simple_user_instruction', '')}",
    ]
    for item in report.get("warnings", []):
        lines.append(f"- Warning: {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check and optionally repair Windows user SSH config for Codex App remote discovery.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply-user-level", action="store_true")
    parser.add_argument("--refresh-windows-ssh", action="store_true")
    parser.add_argument("--windows-ssh-readiness-report", default=str(DEFAULT_CACHE_PATH))
    parser.add_argument("--no-live-windows-ssh-probe", action="store_true")
    args = parser.parse_args()

    report = evaluate_windows_app_ssh_readiness(
        args.repo_root,
        apply_user_level=args.apply_user_level,
        refresh_windows_ssh=bool(args.refresh_windows_ssh),
        windows_ssh_readiness_report=args.windows_ssh_readiness_report,
        no_live_windows_ssh_probe=bool(args.no_live_windows_ssh_probe),
        allow_cache_miss_live_probe=True,
    )
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    cache_path = Path(args.windows_ssh_readiness_report).expanduser().resolve()
    if output_path != cache_path:
        save_json(cache_path, report)
        cache_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
