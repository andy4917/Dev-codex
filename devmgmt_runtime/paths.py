from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .authority import canonical_repo_root as authority_canonical_repo_root
from .path_authority import (
    codex_user_home,
    forbidden_primary_paths,
    load_path_policy,
    runtime_paths as path_runtime_paths,
    windows_codex_home,
)

WINDOWS_POLICY_RELATIVE_PATHS = {
    "config": Path("config.toml"),
    "agents": Path("AGENTS.md"),
    "hooks": Path("hooks.json"),
    "skills": Path("skills") / "dev-workflow",
    "wsl_launcher": Path("bin") / "wsl" / "codex",
}


def _path_policy_for_authority(authority: dict[str, Any] | None) -> dict[str, Any]:
    payload = authority if isinstance(authority, dict) else {}
    policy_path = str(payload.get("_path_policy_path", "")).strip()
    if not policy_path:
        return {}
    try:
        return load_path_policy(policy_path=policy_path, workspace_authority=payload)
    except ValueError:
        return {}


def windows_policy_paths(authority: dict[str, Any] | None = None) -> dict[str, Path]:
    payload = authority if isinstance(authority, dict) else {}
    windows_state = payload.get("windows_app_state", {}) if isinstance(payload.get("windows_app_state"), dict) else {}
    policy = _path_policy_for_authority(payload)
    codex_home = windows_codex_home(policy, authority=payload)
    configured_home = str(windows_state.get("codex_home", "")).strip()
    if configured_home:
        codex_home = Path(configured_home).expanduser().resolve()
    return {
        "codex_home": codex_home,
        "config": (codex_home / WINDOWS_POLICY_RELATIVE_PATHS["config"]).resolve(),
        "agents": (codex_home / WINDOWS_POLICY_RELATIVE_PATHS["agents"]).resolve(),
        "hooks": (codex_home / WINDOWS_POLICY_RELATIVE_PATHS["hooks"]).resolve(),
        "skills": (codex_home / WINDOWS_POLICY_RELATIVE_PATHS["skills"]).resolve(),
        "wsl_launcher": (codex_home / WINDOWS_POLICY_RELATIVE_PATHS["wsl_launcher"]).resolve(),
    }


def runtime_paths(authority: dict[str, Any]) -> dict[str, Path]:
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    linux = runtime.get("linux", {})
    policy = _path_policy_for_authority(authority)
    authority_runtime = path_runtime_paths(policy)
    codex_home = codex_user_home(policy)
    windows_policy = windows_policy_paths(authority)
    return {
        "linux_config": Path(str(linux.get("config", codex_home / "config.toml"))).expanduser().resolve(),
        "linux_agents": Path(str(linux.get("agents", codex_home / "AGENTS.md"))).expanduser().resolve(),
        "linux_hooks": Path(str(linux.get("hooks_config", codex_home / "hooks.json"))).expanduser().resolve(),
        "linux_user_override": Path(str(linux.get("user_override_config", codex_home / "user-config.toml"))).expanduser().resolve(),
        "linux_launcher": Path(str(linux.get("launcher", Path.home() / ".local" / "bin" / "codex"))).expanduser().resolve(),
        "linux_native_codex_cli": authority_runtime.get("codex_cli_bin", Path.home() / ".local" / "bin" / "codex"),
        "observed_windows_codex_home": windows_policy["codex_home"],
        "observed_windows_policy_config": windows_policy["config"],
        "observed_windows_policy_agents": windows_policy["agents"],
        "observed_windows_policy_hooks": windows_policy["hooks"],
        "observed_windows_policy_skills": windows_policy["skills"],
        "observed_windows_wsl_launcher": windows_policy["wsl_launcher"],
    }


def canonical_surface(authority: dict[str, Any]) -> dict[str, Any]:
    payload = authority.get("canonical_remote_execution_surface", authority.get("canonical_execution_surface", {}))
    return payload if isinstance(payload, dict) else {}


def forbidden_runtime_paths(authority: dict[str, Any]) -> list[str]:
    if authority:
        configured = [str(item).strip() for item in authority.get("forbidden_primary_runtime_paths", []) if str(item).strip()]
        if configured:
            return configured
        try:
            return forbidden_primary_paths(_path_policy_for_authority(authority))
        except ValueError:
            return configured
    return []


def is_forbidden_runtime_value(value: str, authority: dict[str, Any]) -> bool:
    normalized = str(value).replace("\\", "/").strip().lower()
    if not normalized:
        return False
    for raw in forbidden_runtime_paths(authority):
        marker = raw.replace("\\", "/").strip().lower()
        if marker == ".codex/bin/wsl/codex" and normalized.endswith(marker):
            return True
        if marker and marker in normalized:
            return True
    return False


def canonical_repo_root(authority: dict[str, Any], fallback_repo_root: str | Path | None = None) -> Path:
    return authority_canonical_repo_root(authority, fallback_repo_root)


def run_git(repo_root: str | Path, *args: str) -> dict[str, Any]:
    cwd = Path(repo_root).expanduser().resolve()
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc), "exit_code": None}
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }


def parse_git_worktree_list(output: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, rest = line.partition(" ")
        value = rest.strip()
        if key == "worktree":
            current["worktree"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value
        elif key == "locked":
            current["locked"] = True
            if value:
                current["locked_reason"] = value
        elif key == "prunable":
            current["prunable"] = True
            if value:
                current["prunable_reason"] = value
        elif key == "detached":
            current["detached"] = True
        elif key == "bare":
            current["bare"] = True
    if current:
        entries.append(current)
    return entries


def git_worktree_inventory(repo_root: str | Path, authority: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_root = Path(repo_root).expanduser().resolve()
    authority = authority or {}
    canonical_root = canonical_repo_root(authority, resolved_root)
    top_level = run_git(resolved_root, "rev-parse", "--show-toplevel")
    active_worktree_root = Path(str(top_level.get("stdout", "")).strip() or str(resolved_root)).expanduser().resolve()
    branch = run_git(resolved_root, "branch", "--show-current")
    current_branch = str(branch.get("stdout", "")).strip()
    common_dir = run_git(resolved_root, "rev-parse", "--git-common-dir")
    worktree_list = run_git(resolved_root, "worktree", "list", "--porcelain")
    entries = parse_git_worktree_list(str(worktree_list.get("stdout", "")))
    branch_map: dict[str, list[str]] = {}
    stale_entries: list[dict[str, Any]] = []
    for entry in entries:
        branch_name = str(entry.get("branch", "")).strip()
        worktree_path = str(entry.get("worktree", "")).strip()
        if branch_name and worktree_path:
            branch_map.setdefault(branch_name, []).append(worktree_path)
        worktree_exists = Path(worktree_path).expanduser().exists() if worktree_path else False
        if entry.get("prunable") or (worktree_path and not worktree_exists):
            stale_entries.append(
                {
                    "worktree": worktree_path,
                    "branch": branch_name,
                    "prunable": bool(entry.get("prunable")),
                    "locked": bool(entry.get("locked")),
                    "exists": worktree_exists,
                }
            )
    duplicate_branches = {
        branch_name: sorted(paths)
        for branch_name, paths in branch_map.items()
        if branch_name and len(paths) > 1
    }
    return {
        "canonical_repo_root": str(canonical_root),
        "active_worktree_root": str(active_worktree_root),
        "current_branch": current_branch,
        "git_common_dir": str(common_dir.get("stdout", "")).strip(),
        "is_linked_worktree": str(common_dir.get("stdout", "")).strip() not in {"", ".git"},
        "worktrees": entries,
        "stale_worktrees": stale_entries,
        "duplicate_branch_checkouts": duplicate_branches,
        "current_branch_conflict": bool(current_branch and current_branch in duplicate_branches),
    }
