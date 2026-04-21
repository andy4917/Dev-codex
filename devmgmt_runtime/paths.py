from __future__ import annotations

from pathlib import Path
from typing import Any


WINDOWS_CODEX_HOME = Path("/mnt/c/Users/anise/.codex")


def runtime_paths(authority: dict[str, Any]) -> dict[str, Path]:
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    linux = runtime.get("linux", {})
    windows = runtime.get("windows_mirror", {})
    return {
        "linux_config": Path(str(linux.get("config", Path.home() / ".codex" / "config.toml"))).expanduser().resolve(),
        "linux_agents": Path(str(linux.get("agents", Path.home() / ".codex" / "AGENTS.md"))).expanduser().resolve(),
        "linux_hooks": Path(str(linux.get("hooks_config", Path.home() / ".codex" / "hooks.json"))).expanduser().resolve(),
        "linux_user_override": Path(str(linux.get("user_override_config", Path.home() / ".codex" / "user-config.toml"))).expanduser().resolve(),
        "linux_launcher": Path(str(linux.get("launcher", Path.home() / ".local" / "bin" / "codex"))).expanduser().resolve(),
        "windows_config": Path(str(windows.get("config", WINDOWS_CODEX_HOME / "config.toml"))).expanduser().resolve(),
        "windows_agents": Path(str(windows.get("agents", WINDOWS_CODEX_HOME / "AGENTS.md"))).expanduser().resolve(),
        "windows_hooks": Path(str(windows.get("hooks_config", WINDOWS_CODEX_HOME / "hooks.json"))).expanduser().resolve(),
        "windows_wsl_launcher": Path(str(windows.get("wsl_launcher", WINDOWS_CODEX_HOME / "bin" / "wsl" / "codex"))).expanduser().resolve(),
    }


def canonical_surface(authority: dict[str, Any]) -> dict[str, Any]:
    payload = authority.get("canonical_remote_execution_surface", authority.get("canonical_execution_surface", {}))
    return payload if isinstance(payload, dict) else {}


def forbidden_runtime_paths(authority: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in authority.get("forbidden_primary_runtime_paths", []) if str(item).strip()]


def is_forbidden_runtime_value(value: str, authority: dict[str, Any]) -> bool:
    normalized = str(value).replace("\\\\", "/").strip().lower()
    if not normalized:
        return False
    for raw in forbidden_runtime_paths(authority):
        marker = raw.replace("\\\\", "/").strip().lower()
        if marker == ".codex/bin/wsl/codex" and normalized.endswith(marker):
            return True
        if marker and marker in normalized:
            return True
    return False

