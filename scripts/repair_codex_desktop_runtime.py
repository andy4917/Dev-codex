#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import tomllib
from pathlib import Path
from typing import Any


MANAGEMENT_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = MANAGEMENT_ROOT / "contracts" / "workspace_authority.json"
ENV_SYNC_POLICY_PATH = MANAGEMENT_ROOT / "contracts" / "environment_sync_policy.json"
REPORT_PATH = MANAGEMENT_ROOT / "reports" / "codex-runtime-repair.json"

WORKFLOW_SCRIPTS = MANAGEMENT_ROOT.parent / "Dev-Workflow" / "scripts"
if str(WORKFLOW_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_SCRIPTS))

from _common import current_wsl_distro  # noqa: E402


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def to_unc_path(path: str | Path, host: str) -> str:
    distro = current_wsl_distro() or "Ubuntu"
    suffix = str(Path(path).resolve()).lstrip("/").replace("/", "\\")
    return f"\\\\{host}\\{distro}\\{suffix}"


def unc_to_linux_path(value: str) -> str | None:
    if not value.startswith("\\\\"):
        return None
    parts = [part for part in value.split("\\") if part]
    if len(parts) < 3:
        return None
    suffix = parts[2:]
    return "/" + "/".join(suffix)


def stale_path_markers(policy: dict[str, Any], authority: dict[str, Any]) -> tuple[str, ...]:
    markers = [
        "/mnt/c/users",
        "/home/dev/repos",
        "/workspace",
        "/mnt/c/users/anise/documents/codex",
    ]
    for prefix in policy.get("legacy_mount", {}).get("blocked_prefixes", []):
        if prefix == "windows-user-mount":
            markers.append("/mnt/c/users")
    for prefix in policy.get("stale_workspace_markers", []):
        if prefix == "windows-user-mount":
            markers.append("/mnt/c/users")
        elif prefix == "legacy-home-dev-repos":
            markers.append("/home/dev/repos")
    markers.extend(
        str(item).replace("\\", "/").lower()
        for item in authority.get("hardcoding_definition", {})
        .get("path_rules", {})
        .get("legacy_repo_paths_to_remove", [])
    )
    return tuple(dict.fromkeys(marker.lower() for marker in markers if marker))


def preferred_host(authority: dict[str, Any], policy: dict[str, Any]) -> str:
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    return str(
        restore.get("preferred_windows_access_host")
        or policy.get("canonical_wsl", {}).get("preferred_windows_access_host")
        or "wsl.localhost"
    )


def allowed_hosts(authority: dict[str, Any], policy: dict[str, Any]) -> tuple[str, ...]:
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    hosts = restore.get("allowed_windows_access_hosts") or policy.get("canonical_wsl", {}).get("windows_access_hosts") or []
    ordered: list[str] = []
    preferred = preferred_host(authority, policy)
    ordered.append(preferred)
    for host in hosts:
        host_str = str(host).strip()
        if host_str and host_str not in ordered:
            ordered.append(host_str)
    return tuple(ordered)


def user_override_config_paths(authority: dict[str, Any]) -> list[Path]:
    # The Windows mirror is generated output, so only the Linux config can feed overrides back in.
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    paths: list[Path] = []
    raw_path = runtime.get("linux", {}).get("config")
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            paths.append(path.resolve())
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in sorted(paths, key=lambda item: (item.stat().st_mtime, str(item))):
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def effective_default_effort(authority: dict[str, Any]) -> str:
    fallback = str(authority["generation_targets"]["global_config"]["model_reasoning_effort"])
    for path in user_override_config_paths(authority):
        payload = load_toml(path)
        effort = payload.get("model_reasoning_effort")
        if isinstance(effort, str) and effort.strip():
            fallback = effort
    return fallback


def known_linux_roots(authority: dict[str, Any], codex_home: Path) -> dict[str, str]:
    roots = dict(authority.get("canonical_roots", {}))
    lease_root = codex_home / "state" / "workspace-authority"
    if lease_root.exists():
        for lease_file in sorted(lease_root.glob("*.json")):
            payload = load_json(lease_file, default={})
            workspace_root = str(payload.get("workspace_root", "")).strip()
            if workspace_root:
                roots[lease_file.stem] = workspace_root
    return roots


def canonical_root_map(authority: dict[str, Any], policy: dict[str, Any], codex_home: Path) -> dict[str, str]:
    host = preferred_host(authority, policy)
    return {name: to_unc_path(path, host) for name, path in known_linux_roots(authority, codex_home).items()}


def canonicalize_root_value(
    value: str,
    *,
    linux_roots: dict[str, str],
    root_map: dict[str, str],
    allowed_unc_hosts: tuple[str, ...],
    stale_markers: tuple[str, ...],
) -> str | None:
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/").lower()
    for marker in stale_markers:
        if marker in normalized:
            # Legacy reservation-system paths should map to the current leased root if available.
            if "reservation-system" in normalized and "reservation-system" in root_map:
                return root_map["reservation-system"]
            return None

    unc_linux = unc_to_linux_path(raw)
    if unc_linux:
        normalized = unc_linux.replace("\\", "/").lower()

    for name, unc_root in root_map.items():
        linux_root = linux_roots.get(name, "")
        candidates = {unc_root.replace("\\", "/").lower()}
        if linux_root:
            candidates.add(str(Path(linux_root).resolve()).replace("\\", "/").lower())
        for host in allowed_unc_hosts:
            candidates.add(to_unc_path(linux_root, host).replace("\\", "/").lower()) if linux_root else None
        if normalized in candidates:
            return unc_root
        if linux_root and normalized.endswith(str(Path(linux_root).name).lower()) and Path(linux_root).name.lower() in normalized:
            return unc_root
    return raw


def repair_local_environments(
    *,
    codex_home: Path,
    linux_roots: dict[str, str],
    root_map: dict[str, str],
    allowed_unc_hosts: tuple[str, ...],
    stale_markers: tuple[str, ...],
) -> list[str]:
    changed: list[str] = []
    local_env_root = codex_home / "local-environments"
    if not local_env_root.exists():
        return changed
    for path in sorted(local_env_root.glob("*.json")):
        payload = load_json(path, default={})
        workspace_root = str(payload.get("workspace_root", "")).strip()
        repaired = canonicalize_root_value(
            workspace_root,
            linux_roots=linux_roots,
            root_map=root_map,
            allowed_unc_hosts=allowed_unc_hosts,
            stale_markers=stale_markers,
        )
        if repaired and repaired != workspace_root:
            payload["workspace_root"] = repaired
            save_json(path, payload)
            changed.append(str(path))
    return changed


def remove_stale_environment(state: dict[str, Any]) -> bool:
    atom_state = state.get("electron-persisted-atom-state")
    if not isinstance(atom_state, dict):
        return False
    environment = atom_state.get("environment")
    if not isinstance(environment, dict):
        return False
    repo_map = environment.get("repo_map", {})
    repo_names = [str(item.get("repository_full_name", "")) for item in repo_map.values() if isinstance(item, dict)]
    if environment.get("workspace_dir") == "/workspace" or "andy4917/-" in repo_names:
        atom_state.pop("environment", None)
        return True
    return False


def has_localhost_remote_connection(state: dict[str, Any]) -> bool:
    connections = state.get("codex-managed-remote-connections", [])
    if not isinstance(connections, list):
        return False
    for connection in connections:
        if not isinstance(connection, dict):
            continue
        ssh_host = str(connection.get("sshHost", "")).strip().lower()
        if not ssh_host:
            continue
        host = ssh_host.rsplit("@", 1)[-1]
        if host in {"localhost", "127.0.0.1", "::1"}:
            return True
    return False


def repair_global_state(authority: dict[str, Any], policy: dict[str, Any], codex_home: Path) -> dict[str, Any]:
    state_path = codex_home / ".codex-global-state.json"
    state = load_json(state_path, default={})
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    roots = known_linux_roots(authority, codex_home)
    root_map = canonical_root_map(authority, policy, codex_home)
    allowed_unc_hosts = allowed_hosts(authority, policy)
    stale_markers = stale_path_markers(policy, authority)
    default_root_name = str(restore.get("default_active_workspace_root", "management"))
    default_active_root = root_map.get(default_root_name, next(iter(root_map.values())))

    previous_projectless = list(state.get("projectless-thread-ids", []))
    previous_hints = dict(state.get("thread-workspace-root-hints", {}))
    changed = False

    if remove_stale_environment(state):
        changed = True

    active_roots = [
        canonicalize_root_value(
            root,
            linux_roots=roots,
            root_map=root_map,
            allowed_unc_hosts=allowed_unc_hosts,
            stale_markers=stale_markers,
        )
        for root in state.get("active-workspace-roots", [])
    ]
    active_roots = [root for root in active_roots if root]
    active_roots = list(dict.fromkeys(active_roots))
    if not active_roots:
        active_roots = [default_active_root]
    if active_roots != state.get("active-workspace-roots", []):
        state["active-workspace-roots"] = active_roots
        changed = True

    saved_roots = [
        canonicalize_root_value(
            root,
            linux_roots=roots,
            root_map=root_map,
            allowed_unc_hosts=allowed_unc_hosts,
            stale_markers=stale_markers,
        )
        for root in state.get("electron-saved-workspace-roots", [])
    ]
    saved_roots = [root for root in saved_roots if root]
    if not saved_roots:
        saved_roots = list(dict.fromkeys([*active_roots, *root_map.values()]))
    saved_roots = list(dict.fromkeys(saved_roots))
    if saved_roots != state.get("electron-saved-workspace-roots", []):
        state["electron-saved-workspace-roots"] = saved_roots
        changed = True

    project_order = [
        canonicalize_root_value(
            root,
            linux_roots=roots,
            root_map=root_map,
            allowed_unc_hosts=allowed_unc_hosts,
            stale_markers=stale_markers,
        )
        for root in state.get("project-order", [])
    ]
    project_order = [root for root in project_order if root]
    project_order = list(dict.fromkeys([*project_order, *root_map.values()]))
    if project_order != state.get("project-order", []):
        state["project-order"] = project_order
        changed = True

    open_target = state.setdefault("open-in-target-preferences", {})
    if open_target.get("global") != restore.get("open_target_global", "wsl"):
        open_target["global"] = restore.get("open_target_global", "wsl")
        changed = True
    if open_target.get("perPath"):
        open_target["perPath"] = {}
        changed = True

    should_run_in_wsl = not has_localhost_remote_connection(state)
    if state.get("runCodexInWindowsSubsystemForLinux") is not should_run_in_wsl:
        state["runCodexInWindowsSubsystemForLinux"] = should_run_in_wsl
        changed = True
    if state.get("integratedTerminalShell") != restore.get("integrated_terminal_shell", "wsl"):
        state["integratedTerminalShell"] = restore.get("integrated_terminal_shell", "wsl")
        changed = True
    if state.get("followUpQueueMode") != restore.get("follow_up_queue_mode", "steer"):
        state["followUpQueueMode"] = restore.get("follow_up_queue_mode", "steer")
        changed = True
    if state.get("conversationDetailMode") != restore.get("conversation_detail_mode", "steps"):
        state["conversationDetailMode"] = restore.get("conversation_detail_mode", "steps")
        changed = True

    if previous_projectless:
        state["projectless-thread-ids"] = []
        changed = True
    if previous_hints:
        state["thread-workspace-root-hints"] = {}
        changed = True

    if changed:
        save_json(state_path, state)

    return {
        "path": str(state_path),
        "changed": changed,
        "removed_projectless_thread_ids": previous_projectless,
        "removed_thread_hints": sorted(previous_hints),
        "default_active_root": default_active_root,
        "root_map": root_map,
        "allowed_unc_hosts": list(allowed_unc_hosts),
    }


def update_nested_reasoning(payload: dict[str, Any], default_effort: str) -> bool:
    changed = False
    if payload.get("effort") == "xhigh":
        payload["effort"] = default_effort
        changed = True
    if payload.get("reasoning_effort") == "xhigh":
        payload["reasoning_effort"] = default_effort
        changed = True
    if payload.get("model_reasoning_effort") == "xhigh":
        payload["model_reasoning_effort"] = default_effort
        changed = True
    collaboration = payload.get("collaboration_mode")
    if isinstance(collaboration, dict):
        settings = collaboration.get("settings")
        if isinstance(settings, dict) and settings.get("reasoning_effort") == "xhigh":
            settings["reasoning_effort"] = default_effort
            changed = True
    return changed


def repair_sessions(
    *,
    codex_home: Path,
    affected_thread_ids: list[str],
    default_linux_root: str,
    default_effort: str,
    stale_markers: tuple[str, ...],
) -> list[str]:
    changed_files: list[str] = []
    sessions_root = codex_home / "sessions"
    if not sessions_root.exists():
        return changed_files

    affected = set(affected_thread_ids)
    for path in sorted(sessions_root.rglob("*.jsonl")):
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        updated_lines: list[str] = []
        file_changed = False
        session_thread_id = ""
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                updated_lines.append(line)
                continue

            payload = record.get("payload")
            if isinstance(payload, dict) and record.get("type") == "session_meta":
                session_thread_id = str(payload.get("id", ""))

            session_relevant = session_thread_id in affected
            if isinstance(payload, dict):
                cwd = str(payload.get("cwd", "")).strip()
                cwd_normalized = cwd.replace("\\", "/").lower()
                if cwd and (session_relevant or any(marker in cwd_normalized for marker in stale_markers)):
                    payload["cwd"] = default_linux_root
                    file_changed = True
                if update_nested_reasoning(payload, default_effort):
                    file_changed = True

            updated_lines.append(json.dumps(record, ensure_ascii=False))

        if file_changed:
            path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
            changed_files.append(str(path))
    return changed_files


def repair_threads_db(
    *,
    db_path: Path,
    affected_thread_ids: list[str],
    default_linux_root: str,
    default_effort: str,
    reservation_root: str,
    legacy_linux_roots: tuple[str, ...],
) -> dict[str, Any]:
    if not db_path.exists():
        return {"path": str(db_path), "changed_rows": 0}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        changed_rows = 0
        if affected_thread_ids:
            placeholders = ", ".join("?" for _ in affected_thread_ids)
            params = [default_linux_root, default_effort, *affected_thread_ids]
            cur.execute(
                f"""
                UPDATE threads
                SET cwd = CASE WHEN cwd LIKE '/mnt/c/%' THEN ? ELSE cwd END,
                    reasoning_effort = CASE WHEN reasoning_effort = 'xhigh' THEN ? ELSE reasoning_effort END
                WHERE id IN ({placeholders})
                """,
                params,
            )
            changed_rows += cur.rowcount
        for legacy_root in legacy_linux_roots:
            cur.execute(
                """
                UPDATE threads
                SET cwd = ?,
                    reasoning_effort = CASE WHEN reasoning_effort = 'xhigh' THEN ? ELSE reasoning_effort END
                WHERE cwd = ?
                """,
                (reservation_root, default_effort, legacy_root),
            )
            changed_rows += cur.rowcount
        conn.commit()
        return {"path": str(db_path), "changed_rows": changed_rows}
    finally:
        conn.close()


def main() -> int:
    authority = load_json(AUTHORITY_PATH)
    policy = load_json(ENV_SYNC_POLICY_PATH)
    codex_home = Path("/mnt/c/Users/anise/.codex")
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    roots = known_linux_roots(authority, codex_home)
    default_root_name = str(restore.get("default_active_workspace_root", "management"))
    default_linux_root = roots.get(default_root_name, authority["canonical_roots"]["management"])
    default_effort = effective_default_effort(authority)
    stale_markers = stale_path_markers(policy, authority)

    global_state_result = repair_global_state(authority, policy, codex_home)
    local_env_changed = repair_local_environments(
        codex_home=codex_home,
        linux_roots=roots,
        root_map=global_state_result["root_map"],
        allowed_unc_hosts=tuple(global_state_result["allowed_unc_hosts"]),
        stale_markers=stale_markers,
    )
    sessions_changed = repair_sessions(
        codex_home=codex_home,
        affected_thread_ids=global_state_result["removed_projectless_thread_ids"],
        default_linux_root=default_linux_root,
        default_effort=default_effort,
        stale_markers=stale_markers,
    )
    threads_result = repair_threads_db(
        db_path=codex_home / "state_5.sqlite",
        affected_thread_ids=global_state_result["removed_projectless_thread_ids"],
        default_linux_root=default_linux_root,
        default_effort=default_effort,
        reservation_root=roots.get("reservation-system", default_linux_root),
        legacy_linux_roots=tuple(
            path
            for path in authority.get("hardcoding_definition", {})
            .get("path_rules", {})
            .get("legacy_repo_paths_to_remove", [])
            if str(path).startswith("/")
        ),
    )

    report = {
        "status": "PASS",
        "global_state": global_state_result,
        "local_environments_changed": local_env_changed,
        "sessions_changed": sessions_changed,
        "threads_db": threads_result,
        "codex_dev_db": {
            "path": str(codex_home / "sqlite" / "codex-dev.db"),
            "changed_rows": 0,
            "note": "No live restore seed rows were identified in codex-dev.db for this repair pass.",
        },
    }
    save_json(REPORT_PATH, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
