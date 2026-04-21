#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.path_authority import load_path_policy, windows_codex_home
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
WINDOWS_CODEX_HOME = windows_codex_home(load_path_policy())
WINDOWS_APP_CONFIG = WINDOWS_CODEX_HOME / "config.toml"
WINDOWS_APP_AGENTS = WINDOWS_CODEX_HOME / "AGENTS.md"
REQUIRED_BOOTSTRAP_FEATURES = ("remote_control", "remote_connections")
MARKER_BEGIN = "# BEGIN DEV-MANAGEMENT devmgmt-wsl"
MARKER_END = "# END DEV-MANAGEMENT devmgmt-wsl"
DEFAULT_CACHE_TTL_SECONDS = 3600


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def run_windows_ssh_version() -> dict[str, Any]:
    return run_powershell('& "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -V', set_userprofile=False)


def run_windows_ssh_resolve(host_alias: str) -> dict[str, Any]:
    command = (
        '$cfg = Join-Path $env:USERPROFILE ".ssh\\config"; '
        f'$out = & "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -F "$cfg" -G {host_alias}; '
        '$out | Select-String "hostname|user|port|identityfile"'
    )
    return run_powershell(command, set_userprofile=False)


def run_windows_ssh(host_alias: str) -> dict[str, Any]:
    command = (
        '$cfg = Join-Path $env:USERPROFILE ".ssh\\config"; '
        f'& "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -F "$cfg" -o BatchMode=yes -o ConnectTimeout=5 {host_alias} hostname'
    )
    return run_powershell(command, set_userprofile=False)


def concrete_top_level_host_aliases(text: str) -> list[str]:
    aliases: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "host":
            continue
        try:
            patterns = shlex.split(parts[1], comments=False, posix=True)
        except ValueError:
            patterns = parts[1].split()
        for pattern in patterns:
            candidate = pattern.strip()
            if not candidate or any(token in candidate for token in ("*", "?", "!")):
                continue
            if candidate not in aliases:
                aliases.append(candidate)
    return aliases


def coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "pass", "passed", "listed", "worked", "success"}:
        return True
    if text in {"0", "false", "no", "n", "fail", "failed", "blocked", "not_listed"}:
        return False
    return None


def app_connections_status(*, app_host_listed_in_connections: bool | None, manual_add_host_worked: bool | None) -> str:
    if app_host_listed_in_connections is True:
        return "PASS"
    if manual_add_host_worked is False:
        return "BLOCKED"
    return "WARN"


def app_remote_project_status(
    *,
    app_remote_project_opened: bool | None = None,
    app_remote_project_not_opened: bool | None = None,
    app_remote_project_unobserved: bool | None = None,
) -> str:
    if app_remote_project_opened is True:
        return "OPENED"
    if app_remote_project_not_opened is True:
        return "NOT_OPENED"
    if app_remote_project_unobserved is True:
        return "UNOBSERVED"
    return "UNOBSERVED"


def bootstrap_status() -> dict[str, Any]:
    config_exists = WINDOWS_APP_CONFIG.exists()
    config_text = read_text(WINDOWS_APP_CONFIG)
    config_payload: dict[str, Any] = {}
    if config_exists:
        try:
            with WINDOWS_APP_CONFIG.open("rb") as handle:
                loaded = tomllib.load(handle)
                config_payload = loaded if isinstance(loaded, dict) else {}
        except (tomllib.TOMLDecodeError, OSError):
            config_payload = {}
    features = config_payload.get("features", {}) if isinstance(config_payload.get("features"), dict) else {}
    meaningful_lines = [line.rstrip() for line in config_text.splitlines() if line.strip()]
    minimal_bootstrap_lines = ["[features]", "remote_control = true", "remote_connections = true"]
    minimal_bootstrap = meaningful_lines == minimal_bootstrap_lines
    extra_lines_present = bool(meaningful_lines) and meaningful_lines != minimal_bootstrap_lines
    agents_size = WINDOWS_APP_AGENTS.stat().st_size if WINDOWS_APP_AGENTS.exists() else 0
    agents_is_inert_empty = WINDOWS_APP_AGENTS.exists() and agents_size == 0
    remote_control_enabled = features.get("remote_control") is True
    remote_connections_enabled = features.get("remote_connections") is True
    required_features_ready = remote_control_enabled and remote_connections_enabled
    status = (
        "PASS"
        if required_features_ready or not config_exists
        else "BLOCKED"
    )
    return {
        "status": status,
        "config_path": str(WINDOWS_APP_CONFIG),
        "config_exists": config_exists,
        "remote_control_enabled": remote_control_enabled,
        "remote_connections_enabled": remote_connections_enabled,
        "bootstrap_features_ready": required_features_ready,
        "minimal_bootstrap": minimal_bootstrap,
        "extra_lines_present": extra_lines_present,
        "observed_features": sorted(str(key) for key in features.keys()),
        "agents_path": str(WINDOWS_APP_AGENTS),
        "agents_exists": WINDOWS_APP_AGENTS.exists(),
        "agents_size_bytes": agents_size,
        "agents_is_inert_empty": agents_is_inert_empty,
    }


def summarize_blocking_domain(
    *,
    host_alias_visible_to_codex_app_discovery: bool,
    probe_ok: bool,
    app_host_listed_in_connections: bool | None,
    manual_add_host_worked: bool | None,
    app_remote_project_state: str,
    bootstrap: dict[str, Any] | None = None,
) -> str:
    if not host_alias_visible_to_codex_app_discovery:
        return "ssh_config"
    if not probe_ok:
        return "ssh_transport"
    if manual_add_host_worked is False and app_host_listed_in_connections is not True:
        if isinstance(bootstrap, dict) and str(bootstrap.get("status", "PASS")) != "PASS":
            return "app_bootstrap"
        return "app_discovery"
    if app_remote_project_state == "NOT_OPENED":
        return "app_remote_project"
    if app_remote_project_state == "UNOBSERVED":
        return "ui_evidence"
    return "none"


def summarize_readiness(
    *,
    host_alias: str,
    host_alias_visible_to_codex_app_discovery: bool,
    probe_ok: bool,
    app_host_listed_in_connections: bool | None,
    manual_add_host_worked: bool | None,
    app_remote_project_state: str,
    app_remote_project_path: str,
    bootstrap: dict[str, Any] | None = None,
) -> tuple[str, list[str], list[str]]:
    blocking_reasons: list[str] = []
    warning_reasons: list[str] = []
    if not host_alias_visible_to_codex_app_discovery:
        blocking_reasons.append(
            f"Host {host_alias} must exist directly in {WINDOWS_SSH_CONFIG}; Include-only aliases are not sufficient for Codex App discovery."
        )
    if not probe_ok:
        blocking_reasons.append(f"Windows ssh.exe cannot connect to {host_alias}.")
    if app_host_listed_in_connections is True:
        pass
    elif manual_add_host_worked is False:
        blocking_reasons.append(
            f"Codex App still cannot use {host_alias} after Connections > Add host > {host_alias}."
        )
    elif manual_add_host_worked is True:
        warning_reasons.append(
            f"Codex App did not auto-list {host_alias}, but Connections > Add host > {host_alias} worked."
        )
    else:
        warning_reasons.append(
            f"Do not assume {host_alias} appears automatically in Connections; verify it in the app or use Connections > Add host > {host_alias}."
        )
    if app_remote_project_state == "OPENED":
        pass
    elif app_remote_project_state == "NOT_OPENED":
        blocking_reasons.append(
            f"Codex App did not open remote project {app_remote_project_path} on {host_alias}."
        )
    else:
        warning_reasons.append(
            f"Remote project {app_remote_project_path} has not been observed open in Codex App yet."
        )
    status = collapse_status(
        [
            "BLOCKED" if blocking_reasons else "",
            "WARN" if warning_reasons else "",
        ]
    )
    return status, blocking_reasons, warning_reasons


def build_simple_user_instruction(report: dict[str, Any]) -> str:
    host_alias = str(report.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    remote_project = str(report.get("app_remote_project_path", str(ROOT))).strip() or str(ROOT)
    if not bool(report.get("host_alias_visible_to_codex_app_discovery")):
        return (
            f"Add or repair a direct Host {host_alias} entry in Windows {WINDOWS_SSH_CONFIG}, "
            f"then reopen Codex App and use Connections > Add host > {host_alias}."
        )
    probe = report.get("probe", {}) if isinstance(report.get("probe"), dict) else {}
    if not bool(probe.get("ok")):
        return f"Repair Windows ssh.exe connectivity for {host_alias}, then retry Connections > Add host > {host_alias} in Codex App."
    if report.get("app_remote_project_status") == "OPENED":
        return f"Codex App already opened {remote_project} on {host_alias}."
    if report.get("app_host_listed_in_connections") is True:
        return f"Restart Codex App, open Settings > Connections, select {host_alias}, and open {remote_project}."
    if report.get("manual_add_host_worked") is False:
        return (
            f"Restart Codex App, open Settings > Connections, use Connections > Add host > {host_alias}, "
            f"then open {remote_project}. If the app still cannot connect, record the app failure as an external blocker."
        )
    return (
        f"Restart Codex App, open Settings > Connections. Do not assume {host_alias} is already listed; "
        f"use Connections > Add host > {host_alias}, then open {remote_project}."
    )


def choose_identity_file() -> str:
    candidates = [
        ("codex_wsl_ed25519", "~/.ssh/codex_wsl_ed25519"),
        ("devmgmt_wsl_ed25519", "~/.ssh/devmgmt_wsl_ed25519"),
    ]
    for name, rendered in candidates:
        if (WINDOWS_SSH_CONFIG.parent / name).exists():
            return rendered
    return candidates[0][1]


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def readiness_fingerprint(host_alias: str) -> dict[str, Any]:
    windows_config_text = read_text(WINDOWS_SSH_CONFIG)
    aliases = concrete_top_level_host_aliases(windows_config_text)
    bootstrap = bootstrap_status()
    app_config_text = read_text(WINDOWS_APP_CONFIG)
    return {
        "host_alias": host_alias,
        "windows_ssh_config": str(WINDOWS_SSH_CONFIG),
        "windows_ssh_config_sha256": _sha256_text(windows_config_text),
        "concrete_top_level_host_aliases": aliases,
        "host_alias_visible_to_codex_app_discovery": host_alias in aliases,
        "identity_file": choose_identity_file(),
        "windows_app_config": str(WINDOWS_APP_CONFIG),
        "windows_app_config_sha256": _sha256_text(app_config_text),
        "bootstrap_features_ready": bool(bootstrap.get("bootstrap_features_ready")),
        "remote_control_enabled": bool(bootstrap.get("remote_control_enabled")),
        "remote_connections_enabled": bool(bootstrap.get("remote_connections_enabled")),
        "agents_is_inert_empty": bool(bootstrap.get("agents_is_inert_empty")),
    }


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
    rendered = render_alias(host_alias)
    if MARKER_BEGIN in text and MARKER_END in text:
        existing = text[text.index(MARKER_BEGIN) : text.index(MARKER_END) + len(MARKER_END)]
        if existing.strip() == rendered.strip():
            return False, []
    elif host_alias in concrete_top_level_host_aliases(text):
        return False, []
    backups: list[str] = []
    if apply:
        WINDOWS_SSH_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if WINDOWS_SSH_CONFIG.exists():
            backup = WINDOWS_SSH_CONFIG.with_suffix(f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(WINDOWS_SSH_CONFIG, backup)
            backups.append(str(backup))
        if MARKER_BEGIN in text and MARKER_END in text:
            prefix, remainder = text.split(MARKER_BEGIN, 1)
            _, suffix = remainder.split(MARKER_END, 1)
            updated = prefix.rstrip() + ("\n\n" if prefix.strip() else "") + rendered + suffix.lstrip("\n")
        else:
            updated = text.rstrip() + ("\n\n" if text.strip() else "") + rendered
        WINDOWS_SSH_CONFIG.write_text(updated, encoding="utf-8")
    return True, backups


def build_live_report(
    repo_root: str | Path | None = None,
    *,
    apply_user_level: bool = False,
    app_host_listed_in_connections: bool | None = None,
    manual_add_host_worked: bool | None = None,
    app_remote_project_opened: bool | None = None,
    app_remote_project_not_opened: bool | None = None,
    app_remote_project_unobserved: bool | None = None,
    app_remote_project_path: str | None = None,
) -> dict[str, Any]:
    authority = load_authority(repo_root, authority_path=AUTHORITY_PATH)
    surface = canonical_surface(authority)
    host_alias = str(surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    remote_project_path = str(app_remote_project_path or repo_root or ROOT).strip() or str(ROOT)
    windows_config_text = read_text(WINDOWS_SSH_CONFIG)
    top_level_aliases = concrete_top_level_host_aliases(windows_config_text)
    alias_present = host_alias in top_level_aliases
    backups: list[str] = []
    changed = False
    if apply_user_level:
        changed, backups = ensure_alias(host_alias, apply=True)
        windows_config_text = read_text(WINDOWS_SSH_CONFIG)
        top_level_aliases = concrete_top_level_host_aliases(windows_config_text)
        alias_present = host_alias in top_level_aliases
    ssh_version = run_windows_ssh_version()
    ssh_resolve = run_windows_ssh_resolve(host_alias)
    probe = run_windows_ssh(host_alias)
    bootstrap = bootstrap_status()
    app_host_listed = coerce_optional_bool(app_host_listed_in_connections)
    manual_add_worked = coerce_optional_bool(manual_add_host_worked)
    project_state = app_remote_project_status(
        app_remote_project_opened=app_remote_project_opened,
        app_remote_project_not_opened=app_remote_project_not_opened,
        app_remote_project_unobserved=app_remote_project_unobserved,
    )
    status, blocking_reasons, warning_reasons = summarize_readiness(
        host_alias=host_alias,
        host_alias_visible_to_codex_app_discovery=alias_present,
        probe_ok=bool(probe.get("ok")),
        app_host_listed_in_connections=app_host_listed,
        manual_add_host_worked=manual_add_worked,
        app_remote_project_state=project_state,
        app_remote_project_path=remote_project_path,
        bootstrap=bootstrap,
    )
    blocking_domain = summarize_blocking_domain(
        host_alias_visible_to_codex_app_discovery=alias_present,
        probe_ok=bool(probe.get("ok")),
        app_host_listed_in_connections=app_host_listed,
        manual_add_host_worked=manual_add_worked,
        app_remote_project_state=project_state,
        bootstrap=bootstrap,
    )
    report = {
        "status": status,
        "scope": "app-usability",
        "host_alias": host_alias,
        "windows_ssh_dir": str(WINDOWS_SSH_CONFIG.parent),
        "windows_ssh_config": str(WINDOWS_SSH_CONFIG),
        "wsl_user_ssh_config": str(WSL_SSH_CONFIG),
        "wsl_managed_ssh_config": str(WSL_SSH_MANAGED_CONFIG),
        "alias_present": alias_present,
        "host_alias_defined_directly_in_windows_config": alias_present,
        "host_alias_visible_to_codex_app_discovery": alias_present,
        "concrete_top_level_host_aliases": top_level_aliases,
        "identity_file": choose_identity_file(),
        "ssh_exe_version": ssh_version,
        "ssh_config_resolve": ssh_resolve,
        "probe": probe,
        "top_level_host_alias_status": "PASS" if alias_present else "BLOCKED",
        "windows_ssh_probe_status": "PASS" if bool(probe.get("ok")) else "BLOCKED",
        "ssh_transport_status": "PASS" if bool(probe.get("ok")) else "BLOCKED",
        "app_connections_status": app_connections_status(
            app_host_listed_in_connections=app_host_listed,
            manual_add_host_worked=manual_add_worked,
        ),
        "app_host_discovery_status": app_connections_status(
            app_host_listed_in_connections=app_host_listed,
            manual_add_host_worked=manual_add_worked,
        ),
        "app_host_listed_in_connections": app_host_listed,
        "manual_add_host_worked": manual_add_worked,
        "app_remote_project_status": project_state,
        "app_remote_project_path": remote_project_path,
        "blocking_domain": blocking_domain,
        "windows_app_bootstrap": bootstrap,
        "readiness_fingerprint": readiness_fingerprint(host_alias),
        "hard_acceptance": {
            "codex_app_remote_project_opened": project_state == "OPENED",
            "remote_project_path": remote_project_path,
            "ssh_transport_ready": bool(probe.get("ok")),
            "status": "PASS" if project_state == "OPENED" and bool(probe.get("ok")) else "BLOCKED" if project_state == "NOT_OPENED" else "UNOBSERVED",
        },
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "applied": changed,
        "backups": backups,
        "repairable_user_level": True,
        "system_config_modified": False,
        "windows_path_modified": False,
        "simple_user_instruction": "",
        "user_action_required": [],
        "warnings": blocking_reasons + warning_reasons,
    }
    report["simple_user_instruction"] = build_simple_user_instruction(report)
    report["user_action_required"] = [] if status == "PASS" else [report["simple_user_instruction"]]
    return report


def hydrate_report_fields(report: dict[str, Any]) -> dict[str, Any]:
    payload = dict(report)
    host_alias = str(payload.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    top_level_aliases = concrete_top_level_host_aliases(read_text(WINDOWS_SSH_CONFIG))
    host_alias_visible = coerce_optional_bool(payload.get("host_alias_visible_to_codex_app_discovery"))
    if host_alias_visible is None:
        host_alias_visible = host_alias in top_level_aliases
    app_host_listed = coerce_optional_bool(payload.get("app_host_listed_in_connections"))
    manual_add_worked = coerce_optional_bool(payload.get("manual_add_host_worked"))
    payload["host_alias"] = host_alias
    aliases_value = payload.get("concrete_top_level_host_aliases", top_level_aliases)
    payload["concrete_top_level_host_aliases"] = list(aliases_value) if isinstance(aliases_value, list) else top_level_aliases
    payload["host_alias_visible_to_codex_app_discovery"] = host_alias_visible
    payload["host_alias_defined_directly_in_windows_config"] = host_alias_visible
    payload["alias_present"] = host_alias_visible
    payload["app_host_listed_in_connections"] = app_host_listed
    payload["manual_add_host_worked"] = manual_add_worked
    payload["app_remote_project_path"] = str(payload.get("app_remote_project_path", str(ROOT))).strip() or str(ROOT)
    payload["app_remote_project_status"] = str(payload.get("app_remote_project_status", "UNOBSERVED")).strip() or "UNOBSERVED"
    payload["app_connections_status"] = payload.get(
        "app_connections_status",
        app_connections_status(
            app_host_listed_in_connections=app_host_listed,
            manual_add_host_worked=manual_add_worked,
        ),
    )
    payload["app_host_discovery_status"] = payload.get("app_host_discovery_status", payload["app_connections_status"])
    payload["top_level_host_alias_status"] = payload.get(
        "top_level_host_alias_status",
        "PASS" if host_alias_visible else "BLOCKED",
    )
    probe = payload.get("probe", {}) if isinstance(payload.get("probe"), dict) else {}
    payload["windows_ssh_probe_status"] = payload.get(
        "windows_ssh_probe_status",
        "PASS" if bool(probe.get("ok")) else "BLOCKED",
    )
    payload["ssh_transport_status"] = payload.get("ssh_transport_status", payload["windows_ssh_probe_status"])
    payload["warning_reasons"] = list(payload.get("warning_reasons", [])) if isinstance(payload.get("warning_reasons"), list) else []
    payload["blocking_reasons"] = list(payload.get("blocking_reasons", [])) if isinstance(payload.get("blocking_reasons"), list) else []
    bootstrap = payload.get("windows_app_bootstrap")
    if not isinstance(bootstrap, dict):
        bootstrap = bootstrap_status()
    payload["windows_app_bootstrap"] = bootstrap
    payload["blocking_domain"] = payload.get(
        "blocking_domain",
        summarize_blocking_domain(
            host_alias_visible_to_codex_app_discovery=bool(host_alias_visible),
            probe_ok=bool(probe.get("ok")),
            app_host_listed_in_connections=app_host_listed,
            manual_add_host_worked=manual_add_worked,
            app_remote_project_state=payload["app_remote_project_status"],
            bootstrap=bootstrap,
        ),
    )
    payload["hard_acceptance"] = payload.get(
        "hard_acceptance",
        {
            "codex_app_remote_project_opened": payload["app_remote_project_status"] == "OPENED",
            "remote_project_path": payload["app_remote_project_path"],
            "ssh_transport_ready": bool(probe.get("ok")),
            "status": "PASS"
            if payload["app_remote_project_status"] == "OPENED" and bool(probe.get("ok"))
            else "BLOCKED"
            if payload["app_remote_project_status"] == "NOT_OPENED"
            else "UNOBSERVED",
        },
    )
    return payload


def reassess_report(payload: dict[str, Any]) -> dict[str, Any]:
    report = hydrate_report_fields(payload)
    probe = report.get("probe", {}) if isinstance(report.get("probe"), dict) else {}
    bootstrap = bootstrap_status()
    report["windows_app_bootstrap"] = bootstrap
    status, blocking_reasons, warning_reasons = summarize_readiness(
        host_alias=str(report.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl",
        host_alias_visible_to_codex_app_discovery=bool(report.get("host_alias_visible_to_codex_app_discovery")),
        probe_ok=bool(probe.get("ok")),
        app_host_listed_in_connections=coerce_optional_bool(report.get("app_host_listed_in_connections")),
        manual_add_host_worked=coerce_optional_bool(report.get("manual_add_host_worked")),
        app_remote_project_state=str(report.get("app_remote_project_status", "UNOBSERVED")),
        app_remote_project_path=str(report.get("app_remote_project_path", str(ROOT))),
        bootstrap=bootstrap,
    )
    report["status"] = status
    report["blocking_reasons"] = blocking_reasons
    report["warning_reasons"] = warning_reasons
    report["warnings"] = blocking_reasons + warning_reasons
    report["blocking_domain"] = summarize_blocking_domain(
        host_alias_visible_to_codex_app_discovery=bool(report.get("host_alias_visible_to_codex_app_discovery")),
        probe_ok=bool(probe.get("ok")),
        app_host_listed_in_connections=coerce_optional_bool(report.get("app_host_listed_in_connections")),
        manual_add_host_worked=coerce_optional_bool(report.get("manual_add_host_worked")),
        app_remote_project_state=str(report.get("app_remote_project_status", "UNOBSERVED")),
        bootstrap=bootstrap,
    )
    report["simple_user_instruction"] = build_simple_user_instruction(report)
    report["user_action_required"] = [] if status == "PASS" else [report["simple_user_instruction"]]
    return report


def cache_validation(report: dict[str, Any]) -> dict[str, Any]:
    host_alias = str(report.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    current = readiness_fingerprint(host_alias)
    cached = report.get("readiness_fingerprint")
    if not isinstance(cached, dict):
        return {
            "status": "MISSING_FINGERPRINT",
            "current": current,
            "cached": cached,
            "mismatched_fields": [],
        }
    tracked_fields = [
        "host_alias",
        "windows_ssh_config",
        "windows_ssh_config_sha256",
        "concrete_top_level_host_aliases",
        "host_alias_visible_to_codex_app_discovery",
        "identity_file",
        "windows_app_config",
        "windows_app_config_sha256",
        "bootstrap_features_ready",
        "remote_control_enabled",
        "remote_connections_enabled",
        "agents_is_inert_empty",
    ]
    mismatched_fields = [field for field in tracked_fields if cached.get(field) != current.get(field)]
    return {
        "status": "PASS" if not mismatched_fields else "MISMATCH",
        "current": current,
        "cached": cached,
        "mismatched_fields": mismatched_fields,
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
    payload = hydrate_report_fields(report)
    warnings = list(payload.get("warnings", [])) if isinstance(payload.get("warnings"), list) else []
    user_actions = list(payload.get("user_action_required", [])) if isinstance(payload.get("user_action_required"), list) else []
    validation = cache_validation(payload)
    refresh_action = (
        "Run `python3 scripts/check_windows_app_ssh_readiness.py --refresh-windows-ssh --json` to refresh Windows SSH readiness."
    )
    if not (probe_source == "cached_report" and cache_status == "missing"):
        payload = reassess_report(payload)
        warnings = list(payload.get("warnings", [])) if isinstance(payload.get("warnings"), list) else []
        user_actions = list(payload.get("user_action_required", [])) if isinstance(payload.get("user_action_required"), list) else []
    if "host_alias_visible_to_codex_app_discovery" not in report or "app_connections_status" not in report:
        warnings.append("Cached Windows SSH readiness predates direct Host alias discovery checks; run an explicit refresh.")
        if refresh_action not in user_actions:
            user_actions.append(refresh_action)
        payload["status"] = "WARN"
    if probe_source == "cached_report" and validation["status"] == "MISSING_FINGERPRINT":
        warnings.append("Cached Windows SSH readiness is missing a state fingerprint; run an explicit refresh before trusting it.")
        if refresh_action not in user_actions:
            user_actions.append(refresh_action)
        payload["status"] = "WARN"
    elif probe_source == "cached_report" and validation["status"] == "MISMATCH":
        mismatched = ", ".join(validation["mismatched_fields"]) or "unknown fields"
        warnings.append(
            f"Cached Windows SSH readiness no longer matches the current Windows SSH/bootstrap state ({mismatched}); run an explicit refresh."
        )
        if refresh_action not in user_actions:
            user_actions.append(refresh_action)
        payload["status"] = "WARN"
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
    payload["warnings"] = warnings
    payload["blocking_reasons"] = list(payload.get("blocking_reasons", [])) if isinstance(payload.get("blocking_reasons"), list) else []
    payload["warning_reasons"] = list(payload.get("warning_reasons", [])) if isinstance(payload.get("warning_reasons"), list) else []
    payload["simple_user_instruction"] = build_simple_user_instruction(payload)
    if payload["status"] == "PASS":
        payload["user_action_required"] = user_actions
    else:
        if payload["simple_user_instruction"] and payload["simple_user_instruction"] not in user_actions:
            user_actions.insert(0, payload["simple_user_instruction"])
        payload["user_action_required"] = user_actions
    payload["warnings"] = warnings
    payload["probe_source"] = probe_source
    payload["cache_status"] = cache_status
    payload["cache_validation"] = validation
    payload["cache_path"] = str(cache_path)
    payload["cache_age_seconds"] = cache_age_seconds
    payload["live_probe_permitted"] = live_probe_permitted
    return payload


def _missing_cache_report(repo_root: str | Path | None = None) -> dict[str, Any]:
    authority = load_authority(repo_root, authority_path=AUTHORITY_PATH)
    surface = canonical_surface(authority)
    host_alias = str(surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    top_level_aliases = concrete_top_level_host_aliases(read_text(WINDOWS_SSH_CONFIG))
    alias_present = host_alias in top_level_aliases
    status = "WARN"
    report = {
        "status": status,
        "scope": "app-usability",
        "host_alias": host_alias,
        "windows_ssh_dir": str(WINDOWS_SSH_CONFIG.parent),
        "windows_ssh_config": str(WINDOWS_SSH_CONFIG),
        "wsl_user_ssh_config": str(WSL_SSH_CONFIG),
        "wsl_managed_ssh_config": str(WSL_SSH_MANAGED_CONFIG),
        "alias_present": alias_present,
        "host_alias_defined_directly_in_windows_config": alias_present,
        "host_alias_visible_to_codex_app_discovery": alias_present,
        "concrete_top_level_host_aliases": top_level_aliases,
        "identity_file": choose_identity_file(),
        "ssh_exe_version": {},
        "probe": {"ok": False, "exit_code": None, "stdout": "", "stderr": "cache missing", "command": ""},
        "top_level_host_alias_status": "PASS" if alias_present else "BLOCKED",
        "windows_ssh_probe_status": "WARN",
        "ssh_transport_status": "WARN",
        "app_connections_status": "WARN",
        "app_host_discovery_status": "WARN",
        "app_host_listed_in_connections": None,
        "manual_add_host_worked": None,
        "app_remote_project_status": "UNOBSERVED",
        "app_remote_project_path": str(repo_root or ROOT),
        "blocking_domain": "ui_evidence",
        "windows_app_bootstrap": bootstrap_status(),
        "readiness_fingerprint": readiness_fingerprint(host_alias),
        "hard_acceptance": {
            "codex_app_remote_project_opened": False,
            "remote_project_path": str(repo_root or ROOT),
            "ssh_transport_ready": False,
            "status": "UNOBSERVED",
        },
        "blocking_reasons": [],
        "warning_reasons": [
            f"Do not assume {host_alias} appears automatically in Connections; verify it in the app or use Connections > Add host > {host_alias}."
        ],
        "applied": False,
        "backups": [],
        "repairable_user_level": True,
        "system_config_modified": False,
        "windows_path_modified": False,
        "simple_user_instruction": "",
        "user_action_required": [],
        "warnings": [],
    }
    report["simple_user_instruction"] = build_simple_user_instruction(report)
    return report


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
    app_host_listed_in_connections: bool | None = None,
    manual_add_host_worked: bool | None = None,
    app_remote_project_opened: bool | None = None,
    app_remote_project_not_opened: bool | None = None,
    app_remote_project_unobserved: bool | None = None,
    app_remote_project_path: str | None = None,
) -> dict[str, Any]:
    cache_path = Path(windows_ssh_readiness_report).expanduser().resolve() if windows_ssh_readiness_report else DEFAULT_CACHE_PATH
    live_probe_permitted = (refresh_windows_ssh or allow_cache_miss_live_probe) and not no_live_windows_ssh_probe
    if injected_readiness is not None:
        injected = dict(injected_readiness)
        if app_host_listed_in_connections is not None:
            injected["app_host_listed_in_connections"] = app_host_listed_in_connections
        if manual_add_host_worked is not None:
            injected["manual_add_host_worked"] = manual_add_host_worked
        if app_remote_project_opened is True:
            injected["app_remote_project_status"] = "OPENED"
        elif app_remote_project_not_opened is True:
            injected["app_remote_project_status"] = "NOT_OPENED"
        elif app_remote_project_unobserved is True:
            injected["app_remote_project_status"] = "UNOBSERVED"
        if app_remote_project_path:
            injected["app_remote_project_path"] = app_remote_project_path
        return _decorate_report(
            injected,
            probe_source="injected",
            cache_path=cache_path,
            cache_status="fresh",
            cache_age_seconds=0.0,
            live_probe_permitted=False,
        )

    if refresh_windows_ssh and no_live_windows_ssh_probe:
        raise ValueError("--refresh-windows-ssh cannot be combined with --no-live-windows-ssh-probe")

    if refresh_windows_ssh:
        live = build_live_report(
            repo_root,
            apply_user_level=apply_user_level,
            app_host_listed_in_connections=app_host_listed_in_connections,
            manual_add_host_worked=manual_add_host_worked,
            app_remote_project_opened=app_remote_project_opened,
            app_remote_project_not_opened=app_remote_project_not_opened,
            app_remote_project_unobserved=app_remote_project_unobserved,
            app_remote_project_path=app_remote_project_path,
        )
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
        cached_report = cached if isinstance(cached, dict) else {}
        if app_host_listed_in_connections is not None:
            cached_report["app_host_listed_in_connections"] = app_host_listed_in_connections
        if manual_add_host_worked is not None:
            cached_report["manual_add_host_worked"] = manual_add_host_worked
        if app_remote_project_opened is True:
            cached_report["app_remote_project_status"] = "OPENED"
        elif app_remote_project_not_opened is True:
            cached_report["app_remote_project_status"] = "NOT_OPENED"
        elif app_remote_project_unobserved is True:
            cached_report["app_remote_project_status"] = "UNOBSERVED"
        if app_remote_project_path:
            cached_report["app_remote_project_path"] = app_remote_project_path
        cache_status = "fresh" if float(metadata["cache_age_seconds"] or 0.0) <= float(cache_ttl_seconds) else "stale"
        decorated = _decorate_report(
            cached_report,
            probe_source="cached_report",
            cache_path=cache_path,
            cache_status=cache_status,
            cache_age_seconds=metadata["cache_age_seconds"],
            live_probe_permitted=live_probe_permitted,
        )
        if live_probe_permitted and str(decorated.get("cache_validation", {}).get("status", "PASS")) != "PASS":
            live = build_live_report(
                repo_root,
                apply_user_level=apply_user_level,
                app_host_listed_in_connections=app_host_listed_in_connections,
                manual_add_host_worked=manual_add_host_worked,
                app_remote_project_opened=app_remote_project_opened,
                app_remote_project_not_opened=app_remote_project_not_opened,
                app_remote_project_unobserved=app_remote_project_unobserved,
                app_remote_project_path=app_remote_project_path,
            )
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
        return decorated

    if live_probe_permitted:
        live = build_live_report(
            repo_root,
            apply_user_level=apply_user_level,
            app_host_listed_in_connections=app_host_listed_in_connections,
            manual_add_host_worked=manual_add_host_worked,
            app_remote_project_opened=app_remote_project_opened,
            app_remote_project_not_opened=app_remote_project_not_opened,
            app_remote_project_unobserved=app_remote_project_unobserved,
            app_remote_project_path=app_remote_project_path,
        )
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
        f"- Top-level aliases: {', '.join(report.get('concrete_top_level_host_aliases', [])) or '(none)'}",
        f"- Host visible to Codex App discovery: {str(report.get('host_alias_visible_to_codex_app_discovery', False)).lower()}",
        f"- App Connections listing verified: {json.dumps(report.get('app_host_listed_in_connections'))}",
        f"- Manual Add host worked: {json.dumps(report.get('manual_add_host_worked'))}",
        f"- App host discovery status: {report.get('app_host_discovery_status', report.get('app_connections_status', 'WARN'))}",
        f"- App remote project status: {report.get('app_remote_project_status', 'UNOBSERVED')}",
        f"- App remote project path: {report.get('app_remote_project_path', str(ROOT))}",
        f"- Blocking domain: {report.get('blocking_domain', 'ui_evidence')}",
        f"- Identity file: {report.get('identity_file', '~/.ssh/devmgmt_wsl_ed25519')}",
        f"- Probe ok: {str(probe.get('ok', False)).lower()}",
        f"- Windows ssh.exe version probe ok: {str(ssh_version.get('ok', False)).lower()}",
        f"- User action: {report.get('simple_user_instruction', '')}",
    ]
    for item in report.get("blocking_reasons", []):
        lines.append(f"- Blocker: {item}")
    for item in report.get("warning_reasons", []):
        lines.append(f"- Warning detail: {item}")
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
    app_listing = parser.add_mutually_exclusive_group()
    app_listing.add_argument("--app-host-listed", action="store_true")
    app_listing.add_argument("--app-host-not-listed", action="store_true")
    manual_add = parser.add_mutually_exclusive_group()
    manual_add.add_argument("--manual-add-host-worked", action="store_true")
    manual_add.add_argument("--manual-add-host-failed", action="store_true")
    remote_project = parser.add_mutually_exclusive_group()
    remote_project.add_argument("--app-remote-project-opened", action="store_true")
    remote_project.add_argument("--app-remote-project-not-opened", action="store_true")
    remote_project.add_argument("--app-remote-project-unobserved", action="store_true")
    parser.add_argument("--app-remote-project-path", default=str(ROOT))
    args = parser.parse_args()

    report = evaluate_windows_app_ssh_readiness(
        args.repo_root,
        apply_user_level=args.apply_user_level,
        refresh_windows_ssh=bool(args.refresh_windows_ssh),
        windows_ssh_readiness_report=args.windows_ssh_readiness_report,
        no_live_windows_ssh_probe=bool(args.no_live_windows_ssh_probe),
        allow_cache_miss_live_probe=True,
        app_host_listed_in_connections=True if args.app_host_listed else False if args.app_host_not_listed else None,
        manual_add_host_worked=True if args.manual_add_host_worked else False if args.manual_add_host_failed else None,
        app_remote_project_opened=True if args.app_remote_project_opened else None,
        app_remote_project_not_opened=True if args.app_remote_project_not_opened else None,
        app_remote_project_unobserved=True if args.app_remote_project_unobserved else None,
        app_remote_project_path=args.app_remote_project_path,
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
