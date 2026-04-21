#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
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
from _scorecard_common import codex_home as resolve_codex_home  # noqa: E402
from render_codex_runtime import launcher_paths as runtime_launcher_paths  # noqa: E402
from render_codex_runtime import preview_linux_launcher_path, render_linux_launcher, sync_generated_executable_text  # noqa: E402
from check_global_runtime import evaluate_global_runtime  # noqa: E402
from devmgmt_runtime.path_authority import forbidden_primary_paths, load_path_policy  # noqa: E402


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


def extract_launcher_target(text: str) -> str:
    for line in str(text).splitlines():
        stripped = line.strip()
        if not stripped.startswith("target="):
            continue
        value = stripped.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            return value[1:-1]
        return value
    return ""


def collapse_gate_status(statuses: list[str]) -> str:
    filtered = [value for value in statuses if value]
    if any(value == "BLOCKED" for value in filtered):
        return "BLOCKED"
    if any(value == "WARN" for value in filtered):
        return "WARN"
    return "PASS"


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
    # Generated mirrors are outputs only. The dedicated user override path is
    # the only allowed optional override source for runtime-derived defaults.
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    paths: list[Path] = []
    raw_path = runtime.get("linux", {}).get("user_override_config")
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


def runtime_restore_homes(authority: dict[str, Any]) -> list[Path]:
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    paths: list[Path] = []
    linux = runtime.get("linux", {})
    if isinstance(linux, dict):
        for key in ("agents", "config", "hooks_config"):
            raw_path = linux.get(key)
            if not raw_path:
                continue
            paths.append(Path(str(raw_path)).expanduser().resolve().parent)
    windows_state = authority.get("windows_app_state", {})
    if isinstance(windows_state, dict):
        raw_home = windows_state.get("codex_home")
        if raw_home:
            paths.append(Path(str(raw_home)).expanduser().resolve())
    fallback = resolve_codex_home()
    if fallback not in paths:
        paths.append(fallback)
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def runtime_restore_codex_home(authority: dict[str, Any]) -> Path:
    candidates = runtime_restore_homes(authority)
    for path in candidates:
        if (path / ".codex-global-state.json").exists() or (path / "state_5.sqlite").exists() or (path / "sessions").exists():
            return path
    return candidates[0]


def known_linux_roots(authority: dict[str, Any], codex_homes: list[Path]) -> dict[str, str]:
    roots = dict(authority.get("canonical_roots", {}))
    for codex_home in codex_homes:
        lease_root = codex_home / "state" / "workspace-authority"
        if not lease_root.exists():
            continue
        for lease_file in sorted(lease_root.glob("*.json")):
            payload = load_json(lease_file, default={})
            workspace_root = str(payload.get("workspace_root", "")).strip()
            if workspace_root:
                roots[lease_file.stem] = workspace_root
    return roots


def canonical_root_map(authority: dict[str, Any], policy: dict[str, Any], codex_homes: list[Path]) -> dict[str, str]:
    host = preferred_host(authority, policy)
    return {name: to_unc_path(path, host) for name, path in known_linux_roots(authority, codex_homes).items()}


def canonical_root_name_for_path(
    value: str,
    *,
    linux_roots: dict[str, str],
    root_map: dict[str, str],
    allowed_unc_hosts: tuple[str, ...],
    stale_markers: tuple[str, ...],
) -> str | None:
    repaired = canonicalize_root_value(
        value,
        linux_roots=linux_roots,
        root_map=root_map,
        allowed_unc_hosts=allowed_unc_hosts,
        stale_markers=stale_markers,
    )
    if not repaired:
        return None
    normalized = repaired.replace("\\", "/").replace("\\", "/").lower()
    for name, linux_root in linux_roots.items():
        candidates = {
            str(Path(linux_root).resolve()).replace("\\", "/").lower(),
        }
        unc_root = root_map.get(name)
        if unc_root:
            candidates.add(unc_root.replace("\\", "/").lower())
        for host in allowed_unc_hosts:
            candidates.add(to_unc_path(linux_root, host).replace("\\", "/").lower())
        if normalized in candidates:
            return name
    return None


def root_string_candidates(
    linux_roots: dict[str, str],
    root_map: dict[str, str],
    allowed_unc_hosts: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    candidates: dict[str, tuple[str, ...]] = {}
    for name, linux_root in linux_roots.items():
        values = {
            str(Path(linux_root).resolve()).replace("\\", "/").lower(),
        }
        unc_root = root_map.get(name)
        if unc_root:
            values.add(unc_root.replace("\\", "/").lower())
        for host in allowed_unc_hosts:
            values.add(to_unc_path(linux_root, host).replace("\\", "/").lower())
        candidates[name] = tuple(sorted((value for value in values if value), key=len, reverse=True))
    return candidates


def iter_session_text_items(path: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not path.exists():
        return items
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        payload = record.get("payload")
        record_type = str(record.get("type", "")).strip()
        kind = record_type
        text_value = ""
        if record_type == "session_meta" and isinstance(payload, dict):
            cwd = str(payload.get("cwd", "")).strip()
            if cwd:
                kind = "session_meta_cwd"
                text_value = cwd
        elif record_type == "turn_context" and isinstance(payload, dict):
            cwd = str(payload.get("cwd", "")).strip()
            if cwd:
                kind = "turn_context_cwd"
                text_value = cwd
        elif record_type == "event_msg" and isinstance(payload, dict):
            kind = str(payload.get("type", "")).strip() or "event_msg"
            for key in ("text", "message", "delta"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    text_value = value.strip()
                    break
        elif record_type == "response_item" and isinstance(payload, dict):
            item_type = str(payload.get("type", "")).strip()
            if item_type == "message":
                parts: list[str] = []
                for item in payload.get("content", []):
                    if isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("text", "").strip():
                        parts.append(item["text"].strip())
                if parts:
                    kind = "assistant_message"
                    text_value = "\n".join(parts)
            elif item_type == "function_call_output":
                output = payload.get("output")
                if isinstance(output, str) and output.strip():
                    kind = "function_output"
                    text_value = output.strip()
        if text_value:
            items.append({"kind": kind, "text": text_value})
    return items


def concise_text(value: str, *, limit: int = 280) -> str:
    collapsed = " ".join(str(value).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def extract_bullet_lines(message: str) -> list[str]:
    bullets: list[str] = []
    for line in str(message).splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullet = stripped[2:].strip()
            if bullet:
                bullets.append(bullet)
    return bullets


def extract_resume_position(message: str) -> list[str]:
    bullets = extract_bullet_lines(message)
    selected = [
        concise_text(bullet, limit=220)
        for bullet in bullets
        if any(token in bullet.lower() for token in ("resume", "위치", "작업 위치", "완료 위치"))
    ]
    if selected:
        return list(dict.fromkeys(selected[:3]))
    lines = [line.strip() for line in str(message).splitlines() if line.strip()]
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "다시 시작할 위치" not in lowered and "resume" not in lowered:
            continue
        follow_up: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.startswith("- "):
                if follow_up:
                    break
                continue
            follow_up.append(concise_text(candidate[2:].strip(), limit=220))
        if follow_up:
            return list(dict.fromkeys(follow_up[:3]))
    return []


def extract_remaining_work_briefing(message: str) -> str:
    bullets = extract_bullet_lines(message)
    for bullet in bullets:
        lowered = bullet.lower()
        if "남은" in bullet or "remaining" in lowered or "next step" in lowered:
            if ":" in bullet:
                return concise_text(bullet.split(":", 1)[1].strip(), limit=240)
            return concise_text(bullet, limit=240)
    for line in str(message).splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if "남은" in stripped or "remaining" in lowered:
            return concise_text(stripped.lstrip("- ").strip(), limit=240)
    sentences = [chunk.strip() for chunk in str(message).replace("\n", " ").split(".") if chunk.strip()]
    if sentences:
        return concise_text(sentences[-1], limit=240)
    return concise_text(message, limit=240)


def format_timestamp(value: int | None) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def recover_thread_resume_candidates(
    *,
    codex_home: Path,
    affected_thread_ids: list[str],
    linux_roots: dict[str, str],
    root_map: dict[str, str],
    allowed_unc_hosts: tuple[str, ...],
    stale_markers: tuple[str, ...],
    default_root_name: str,
) -> list[dict[str, Any]]:
    if not affected_thread_ids:
        return []
    db_path = codex_home / "state_5.sqlite"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ", ".join("?" for _ in affected_thread_ids)
        rows = conn.execute(
            f"""
            SELECT id, title, cwd, first_user_message, updated_at, updated_at_ms, archived
            FROM threads
            WHERE id IN ({placeholders})
            """,
            affected_thread_ids,
        ).fetchall()
    finally:
        conn.close()

    root_tokens = root_string_candidates(linux_roots, root_map, allowed_unc_hosts)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        thread_id = str(row["id"])
        session_paths = sorted((codex_home / "sessions").rglob(f"*{thread_id}.jsonl"))
        session_path = session_paths[-1] if session_paths else None
        session_items = iter_session_text_items(session_path) if session_path else []
        relevant_items = session_items[-80:] if len(session_items) > 80 else session_items
        scores: dict[str, float] = {name: 0.0 for name in linux_roots}

        def add_score(root_name: str | None, amount: float) -> None:
            if not root_name:
                return
            scores[root_name] = scores.get(root_name, 0.0) + amount

        add_score(
            canonical_root_name_for_path(
                str(row["cwd"] or ""),
                linux_roots=linux_roots,
                root_map=root_map,
                allowed_unc_hosts=allowed_unc_hosts,
                stale_markers=stale_markers,
            ),
            3.0,
        )
        for item in relevant_items:
            root_name = canonical_root_name_for_path(
                item["text"],
                linux_roots=linux_roots,
                root_map=root_map,
                allowed_unc_hosts=allowed_unc_hosts,
                stale_markers=stale_markers,
            )
            if root_name:
                add_score(root_name, 4.0 if item["kind"].endswith("_cwd") else 2.0)
                continue
            normalized = item["text"].replace("\\", "/").lower()
            for root_name, token_values in root_tokens.items():
                if any(token in normalized for token in token_values):
                    weight = 2.5 if item["kind"] in {"assistant_message", "function_output", "agent_message"} else 1.5
                    add_score(root_name, weight)
        ranked = sorted(
            scores.items(),
            key=lambda item: (
                item[1],
                len(Path(linux_roots.get(item[0], "/")).parts),
                item[0] == default_root_name,
            ),
            reverse=True,
        )
        root_name = ranked[0][0] if ranked and ranked[0][1] > 0 else default_root_name
        workspace_root = linux_roots.get(root_name, "")
        last_user_message = next(
            (item["text"] for item in reversed(relevant_items) if item["kind"] == "user_message"),
            str(row["first_user_message"] or "").strip(),
        )
        assistant_messages = [
            item["text"]
            for item in relevant_items
            if item["kind"] in {"assistant_message", "agent_message"} and item["text"].strip()
        ]
        last_assistant_message = assistant_messages[-1] if assistant_messages else ""
        resume_position = extract_resume_position(last_assistant_message)
        remaining_work = extract_remaining_work_briefing(last_assistant_message) if last_assistant_message else ""
        candidates.append(
            {
                "thread_id": thread_id,
                "title": str(row["title"] or "").strip(),
                "workspace_root_name": root_name,
                "workspace_root": workspace_root,
                "workspace_unc_root": root_map.get(root_name, ""),
                "updated_at": int(row["updated_at"] or 0),
                "updated_at_iso": format_timestamp(int(row["updated_at"] or 0)),
                "updated_at_ms": int(row["updated_at_ms"] or 0),
                "archived": bool(row["archived"]),
                "session_path": str(session_path) if session_path else "",
                "resume_position": resume_position,
                "remaining_work_briefing": remaining_work,
                "last_user_request": concise_text(last_user_message, limit=220),
                "last_agent_message_excerpt": concise_text(last_assistant_message, limit=320),
            }
        )
    return sorted(
        candidates,
        key=lambda item: (
            int(item.get("updated_at_ms") or 0),
            int(item.get("updated_at") or 0),
            bool(item.get("remaining_work_briefing")),
            bool(item.get("resume_position")),
        ),
        reverse=True,
    )


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
    apply: bool = True,
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
            if apply:
                save_json(path, payload)
            changed.append(str(path))
    return changed


def repair_linux_launcher_shim(authority: dict[str, Any], *, apply: bool = True) -> dict[str, Any]:
    paths = runtime_launcher_paths(authority)
    shim_path = paths["linux_launcher"].expanduser()
    preview_path = preview_linux_launcher_path(authority).expanduser()
    current_text = shim_path.read_text(encoding="utf-8") if shim_path.exists() else ""
    current_target = extract_launcher_target(current_text)
    changed = False
    reasons: list[str] = []
    path_policy = load_path_policy(policy_path=MANAGEMENT_ROOT / "contracts" / "path_authority_policy.json", workspace_authority=authority)

    if not shim_path.exists():
        reasons.append(f"Linux Codex launcher shim is missing: {shim_path}")
    if current_target and any(marker in current_target for marker in forbidden_primary_paths(path_policy)):
        reasons.append("Linux Codex launcher shim still points to the forbidden Windows-mounted launcher.")

    gate_report = load_json(MANAGEMENT_ROOT / "reports" / "global-runtime.json", default={})
    if not isinstance(gate_report, dict) or not gate_report:
        gate_report = evaluate_global_runtime(MANAGEMENT_ROOT, mode="auto")
    native_codex_path = (
        gate_report.get("remote_native_codex_status", {}).get("selected_path")
        or gate_report.get("wrapper_apply_readiness", {}).get("remote_native_codex_path")
        or ""
    )
    expected_text = render_linux_launcher(authority, remote_native_codex_path=str(native_codex_path)) or ""
    needs_repair = bool(expected_text) and (not shim_path.exists() or current_text != expected_text)
    sync_generated_executable_text(preview_path, expected_text)
    if needs_repair and not current_target and shim_path.exists():
        reasons.append(f"Linux Codex launcher shim does not declare a target path: {shim_path}")
    gate_statuses = {
        "canonical_execution_status": gate_report.get("canonical_execution_status", "BLOCKED"),
        "remote_repo_root_status": gate_report.get("remote_repo_root_status", {}).get("status", "BLOCKED"),
        "remote_codex_resolution_status": gate_report.get("remote_codex_resolution_status", {}).get("status", "BLOCKED"),
        "remote_native_codex_status": gate_report.get("remote_native_codex_status", {}).get("status", "BLOCKED"),
        "remote_path_contamination_status": gate_report.get("remote_path_contamination_status", {}).get("status", "BLOCKED"),
        "windows_app_ssh_readiness": gate_report.get("windows_app_ssh_readiness", {}).get("status", "BLOCKED"),
        "config_provenance": gate_report.get("config_provenance", {}).get("gate_status", gate_report.get("config_provenance", {}).get("status", "BLOCKED")),
        "wrapper_target_safety_status": gate_report.get("wrapper_target_safety_status", {}).get("status", "BLOCKED"),
    }
    live_write_allowed = all(value == "PASS" for name, value in gate_statuses.items() if name != "windows_app_ssh_readiness") and gate_statuses["windows_app_ssh_readiness"] in {"PASS", "WARN"}
    live_write_blockers = [name for name, value in gate_statuses.items() if value != "PASS"]
    if live_write_blockers:
        reasons.append("Live launcher overwrite remains blocked until canonical SSH, Windows App SSH readiness, config provenance, and remote codex safety gates pass.")

    if live_write_allowed and apply and needs_repair:
        sync_generated_executable_text(shim_path, expected_text)
        changed = True

    status = "PASS"
    if changed:
        status = "PASS"
    elif needs_repair and live_write_allowed:
        status = "REPAIRABLE"
    elif needs_repair and not live_write_allowed:
        status = "BLOCKED"

    return {
        "path": str(shim_path),
        "preview_path": str(preview_path),
        "exists": shim_path.exists(),
        "current_target": current_target,
        "expected_target": native_codex_path or "ssh-devmgmt-wsl:codex",
        "needs_repair": needs_repair,
        "repairable": live_write_allowed and needs_repair,
        "changed": changed,
        "live_write_allowed": live_write_allowed,
        "live_write_blockers": live_write_blockers,
        "apply_gates": gate_statuses,
        "status": status,
        "reasons": reasons,
    }


LOCALHOST_SSH_HOSTS = {"localhost", "127.0.0.1", "::1"}


def iter_nested_strings(value: Any) -> list[str]:
    strings: list[str] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            strings.append(current)
            continue
        if isinstance(current, dict):
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            stack.extend(current)
    return strings


def is_stale_environment_payload(environment: dict[str, Any], *, stale_markers: tuple[str, ...]) -> bool:
    repo_map = environment.get("repo_map", {})
    repo_names = [str(item.get("repository_full_name", "")) for item in repo_map.values() if isinstance(item, dict)]
    if environment.get("workspace_dir") == "/workspace" or "andy4917/-" in repo_names:
        return True
    for value in iter_nested_strings(environment):
        normalized = value.replace("\\", "/").lower()
        if any(marker in normalized for marker in stale_markers):
            return True
        if normalized.startswith("//wsl$/") or "//wsl$/" in normalized:
            return True
    return False


def remove_stale_environment(state: dict[str, Any], *, stale_markers: tuple[str, ...]) -> bool:
    atom_state = state.get("electron-persisted-atom-state")
    if not isinstance(atom_state, dict):
        return False
    environment = atom_state.get("environment")
    if not isinstance(environment, dict):
        return False
    if is_stale_environment_payload(environment, stale_markers=stale_markers):
        atom_state.pop("environment", None)
        return True
    return False


def split_ssh_host(value: Any) -> tuple[str, str]:
    text = str(value).strip()
    if not text:
        return "", ""
    if "@" in text:
        user, host = text.rsplit("@", 1)
    else:
        user, host = "", text
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return user.strip(), host.strip().lower()


def normalize_localhost_ssh_host(value: Any, *, fallback_host: str = "localhost") -> str:
    user, host = split_ssh_host(value)
    normalized_host = host or fallback_host
    if normalized_host in LOCALHOST_SSH_HOSTS:
        normalized_host = "localhost"
    return f"{user}@{normalized_host}" if user else normalized_host


def localhost_remote_host_id(host_alias: str) -> str:
    return f"remote-ssh-codex-managed:{host_alias}"


def is_localhost_remote_connection(connection: dict[str, Any], *, host_alias: str) -> bool:
    ssh_alias = str(connection.get("sshAlias", "")).strip().lower()
    display_name = str(connection.get("displayName", "")).strip().lower()
    host_id = str(connection.get("hostId", "")).strip().lower()
    _user, host = split_ssh_host(connection.get("sshHost", ""))
    alias = host_alias.strip().lower()
    if host in LOCALHOST_SSH_HOSTS:
        return True
    return any(
        (
            ssh_alias == alias,
            display_name == alias,
            host_id.endswith(f":{alias}"),
            ssh_alias in LOCALHOST_SSH_HOSTS,
            display_name in LOCALHOST_SSH_HOSTS,
            host_id.endswith(":localhost"),
        )
    )


def normalize_localhost_remote_connection(connection: dict[str, Any], *, host_alias: str) -> dict[str, Any]:
    normalized = dict(connection)
    normalized["hostId"] = localhost_remote_host_id(host_alias)
    normalized["displayName"] = host_alias
    normalized["source"] = "codex-managed"
    normalized["autoConnect"] = False
    normalized["sshAlias"] = host_alias
    normalized["sshHost"] = normalize_localhost_ssh_host(connection.get("sshHost", "localhost"))
    ssh_port = connection.get("sshPort", 22)
    try:
        normalized["sshPort"] = int(str(ssh_port).strip()) if str(ssh_port).strip() else 22
    except ValueError:
        normalized["sshPort"] = 22
    return normalized


def remote_connection_rank(connection: dict[str, Any]) -> int:
    score = 0
    for key in ("identity", "sshHost", "sshAlias", "displayName", "hostId"):
        if str(connection.get(key, "")).strip():
            score += 1
    if str(connection.get("source", "")).strip().lower() == "codex-managed":
        score += 2
    if connection.get("sshPort") not in (None, ""):
        score += 1
    return score


def normalize_codex_managed_remote_connections(
    state: dict[str, Any],
    authority: dict[str, Any],
) -> tuple[bool, set[str], set[str]]:
    connections = state.get("codex-managed-remote-connections", [])
    if not isinstance(connections, list):
        if "codex-managed-remote-connections" not in state:
            return False, set(), set()
        state["codex-managed-remote-connections"] = []
        return True, set(), set()

    canonical_surface = authority.get("canonical_execution_surface", {})
    canonical_alias = str(canonical_surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    changed = False
    ordered_host_ids: list[str] = []
    connections_by_host_id: dict[str, dict[str, Any]] = {}
    passthrough_connections: list[dict[str, Any]] = []
    localhost_host_ids: set[str] = set()

    for connection in connections:
        if not isinstance(connection, dict):
            changed = True
            continue
        normalized_connection = dict(connection)
        if is_localhost_remote_connection(connection, host_alias=canonical_alias):
            normalized_connection = normalize_localhost_remote_connection(connection, host_alias=canonical_alias)
            localhost_host_ids.add(str(normalized_connection.get("hostId", "")).strip())
        host_id = str(normalized_connection.get("hostId", "")).strip()
        if not host_id:
            passthrough_connections.append(normalized_connection)
            if normalized_connection != connection:
                changed = True
            continue
        if host_id not in connections_by_host_id:
            ordered_host_ids.append(host_id)
            connections_by_host_id[host_id] = normalized_connection
        elif remote_connection_rank(normalized_connection) >= remote_connection_rank(connections_by_host_id[host_id]):
            connections_by_host_id[host_id] = normalized_connection
        if normalized_connection != connection:
            changed = True

    normalized_connections = [connections_by_host_id[host_id] for host_id in ordered_host_ids]
    normalized_connections.extend(passthrough_connections)
    if normalized_connections != connections:
        state["codex-managed-remote-connections"] = normalized_connections
        changed = True
    return changed, set(ordered_host_ids), localhost_host_ids


def clear_stale_remote_selection_noise(
    state: dict[str, Any],
    *,
    known_host_ids: set[str],
    localhost_host_ids: set[str],
) -> bool:
    changed = False
    selected_host = str(state.get("selected-remote-host-id", "")).strip()
    if "selected-remote-host-id" in state and (not selected_host or selected_host in localhost_host_ids or selected_host not in known_host_ids):
        state.pop("selected-remote-host-id", None)
        changed = True

    auto_connect = state.get("remote-connection-auto-connect-by-host-id")
    if isinstance(auto_connect, dict):
        filtered = {
            str(host_id).strip(): value
            for host_id, value in auto_connect.items()
            if str(host_id).strip() and str(host_id).strip() in known_host_ids and str(host_id).strip() not in localhost_host_ids
        }
        if filtered:
            if filtered != auto_connect:
                state["remote-connection-auto-connect-by-host-id"] = filtered
                changed = True
        else:
            state.pop("remote-connection-auto-connect-by-host-id", None)
            changed = True
    elif "remote-connection-auto-connect-by-host-id" in state:
        state.pop("remote-connection-auto-connect-by-host-id", None)
        changed = True

    return changed


def has_localhost_remote_connection(state: dict[str, Any], authority: dict[str, Any]) -> bool:
    canonical_surface = authority.get("canonical_execution_surface", {})
    canonical_alias = str(canonical_surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    connections = state.get("codex-managed-remote-connections", [])
    if not isinstance(connections, list):
        return False
    for connection in connections:
        if isinstance(connection, dict) and is_localhost_remote_connection(connection, host_alias=canonical_alias):
            return True
    return False


def repair_global_state(
    authority: dict[str, Any],
    policy: dict[str, Any],
    codex_home: Path,
    *,
    preferred_active_root: str | None = None,
    apply: bool = True,
) -> dict[str, Any]:
    state_path = codex_home / ".codex-global-state.json"
    state = load_json(state_path, default={})
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    roots = known_linux_roots(authority, runtime_restore_homes(authority))
    root_map = canonical_root_map(authority, policy, runtime_restore_homes(authority))
    allowed_unc_hosts = allowed_hosts(authority, policy)
    stale_markers = stale_path_markers(policy, authority)
    default_root_name = str(restore.get("default_active_workspace_root", "management"))
    default_active_root = root_map.get(default_root_name, next(iter(root_map.values())))
    normalized_preferred_active_root = canonicalize_root_value(
        preferred_active_root or "",
        linux_roots=roots,
        root_map=root_map,
        allowed_unc_hosts=allowed_unc_hosts,
        stale_markers=stale_markers,
    )

    previous_projectless = list(state.get("projectless-thread-ids", []))
    previous_hints = dict(state.get("thread-workspace-root-hints", {}))
    changed = False

    if remove_stale_environment(state, stale_markers=stale_markers):
        changed = True
    remote_connections_changed, remote_host_ids, localhost_host_ids = normalize_codex_managed_remote_connections(state, authority)
    if remote_connections_changed:
        changed = True
    if clear_stale_remote_selection_noise(
        state,
        known_host_ids=remote_host_ids,
        localhost_host_ids=localhost_host_ids,
    ):
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
        active_roots = [normalized_preferred_active_root or default_active_root]
    elif normalized_preferred_active_root and (previous_projectless or previous_hints):
        active_roots = list(dict.fromkeys([normalized_preferred_active_root, *active_roots]))
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
    elif normalized_preferred_active_root and (previous_projectless or previous_hints):
        saved_roots = list(dict.fromkeys([normalized_preferred_active_root, *saved_roots]))
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
    if normalized_preferred_active_root and (previous_projectless or previous_hints):
        project_order = list(dict.fromkeys([normalized_preferred_active_root, *project_order, *root_map.values()]))
    else:
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

    should_run_in_wsl = not has_localhost_remote_connection(state, authority)
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

    if changed and apply:
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
    recovered_thread_roots: dict[str, str],
    default_linux_root: str,
    default_effort: str,
    stale_markers: tuple[str, ...],
    apply: bool = True,
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
                repaired_root = recovered_thread_roots.get(session_thread_id, default_linux_root)
                if cwd and (session_relevant or any(marker in cwd_normalized for marker in stale_markers)):
                    payload["cwd"] = repaired_root
                    file_changed = True
                if update_nested_reasoning(payload, default_effort):
                    file_changed = True

            updated_lines.append(json.dumps(record, ensure_ascii=False))

        if file_changed:
            if apply:
                path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
            changed_files.append(str(path))
    return changed_files


def repair_threads_db(
    *,
    db_path: Path,
    affected_thread_ids: list[str],
    recovered_thread_roots: dict[str, str],
    default_linux_root: str,
    default_effort: str,
    reservation_root: str,
    legacy_linux_roots: tuple[str, ...],
    apply: bool = True,
) -> dict[str, Any]:
    if not db_path.exists():
        return {"path": str(db_path), "changed_rows": 0}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        changed_rows = 0
        if affected_thread_ids:
            placeholders = ", ".join("?" for _ in affected_thread_ids)
            cur.execute(
                f"""
                SELECT id, cwd, reasoning_effort
                FROM threads
                WHERE id IN ({placeholders})
                """,
                affected_thread_ids,
            )
            for thread_id, cwd, reasoning_effort in cur.fetchall():
                target_root = recovered_thread_roots.get(thread_id, default_linux_root)
                next_cwd = cwd
                if target_root and cwd != target_root:
                    next_cwd = target_root
                elif isinstance(cwd, str) and cwd.startswith("/mnt/c/"):
                    next_cwd = default_linux_root
                next_effort = default_effort if reasoning_effort == "xhigh" else reasoning_effort
                if next_cwd == cwd and next_effort == reasoning_effort:
                    continue
                if apply:
                    cur.execute(
                        "UPDATE threads SET cwd = ?, reasoning_effort = ? WHERE id = ?",
                        (next_cwd, next_effort, thread_id),
                    )
                    changed_rows += cur.rowcount
                else:
                    changed_rows += 1
        for legacy_root in legacy_linux_roots:
            if apply:
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
            else:
                cur.execute("SELECT COUNT(*) FROM threads WHERE cwd = ?", (legacy_root,))
                row = cur.fetchone()
                changed_rows += int(row[0] or 0) if row else 0
        if apply:
            conn.commit()
        return {"path": str(db_path), "changed_rows": changed_rows}
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely repair Codex desktop runtime restore state.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Preview runtime changes without mutating live state (default).")
    mode_group.add_argument("--apply", action="store_true", help="Apply runtime repairs after capturing backups.")
    parser.add_argument("--runtime-codex-home", default="", help="Override the target Codex home to inspect or repair.")
    parser.add_argument("--report-file", default=str(REPORT_PATH), help="Write the runtime repair report to this path.")
    parser.add_argument(
        "--tests-status",
        choices=["PASS", "WARN", "BLOCKED"],
        default="BLOCKED",
        help="Status of the related verification tests. Live launcher overwrite requires PASS.",
    )
    return parser.parse_args()


def git_diff_check_status() -> dict[str, Any]:
    if not (MANAGEMENT_ROOT / ".git").exists():
        return {"status": "PASS", "output": "", "reason": "fixture repo does not include .git"}
    result = subprocess.run(
        ["git", "-C", str(MANAGEMENT_ROOT), "diff", "--check"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (result.stdout or "") + (result.stderr or "")
    return {
        "status": "PASS" if result.returncode == 0 else "BLOCKED",
        "output": output.strip(),
        "reason": "" if result.returncode == 0 else "git diff --check reported problems",
    }


def resolve_runtime_codex_home(authority: dict[str, Any], override: str) -> Path:
    raw = str(override).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return runtime_restore_codex_home(authority)


def capture_baseline_snapshot() -> dict[str, Any]:
    audit_candidates = [
        MANAGEMENT_ROOT / "reports" / "audit.post-export.json",
        MANAGEMENT_ROOT / "reports" / "audit.final.json",
        MANAGEMENT_ROOT / "reports" / "audit.pre-export.json",
        MANAGEMENT_ROOT / "reports" / "audit.pre-gate.json",
    ]
    payload: dict[str, Any] = {}
    source = ""
    for path in audit_candidates:
        if not path.exists():
            continue
        candidate = load_json(path, default={})
        if isinstance(candidate, dict):
            payload = candidate
            source = str(path)
            break
    windows_check = payload.get("windows_policy_surface_check", {}) if isinstance(payload, dict) else {}
    launcher_check = payload.get("wsl_launcher_check", {}) if isinstance(payload, dict) else {}
    violations = payload.get("runtime_restore_seed_violations", []) if isinstance(payload, dict) else []
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "audit_report": source,
        "audit_status": str(payload.get("status", "UNKNOWN")).strip() if isinstance(payload, dict) else "UNKNOWN",
        "windows_policy_surface_status": str(windows_check.get("status", payload.get("windows_policy_surface_status", "UNKNOWN"))).strip() if isinstance(payload, dict) else "UNKNOWN",
        "wsl_launcher_check_status": str(launcher_check.get("status", "UNKNOWN")).strip() if isinstance(launcher_check, dict) else "UNKNOWN",
        "runtime_restore_seed_violations_count": len(violations) if isinstance(violations, list) else 0,
    }


def load_thread_rows(db_path: Path, thread_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not thread_ids or not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        placeholders = ", ".join("?" for _ in thread_ids)
        rows = conn.execute(
            f"""
            SELECT id, cwd, reasoning_effort
            FROM threads
            WHERE id IN ({placeholders})
            """,
            thread_ids,
        ).fetchall()
    finally:
        conn.close()
    return {
        str(row["id"]): {
            "cwd": str(row["cwd"] or ""),
            "reasoning_effort": str(row["reasoning_effort"] or ""),
        }
        for row in rows
    }


def build_change_entries(
    *,
    global_state_result: dict[str, Any],
    launcher_result: dict[str, Any],
    local_env_changed: list[str],
    sessions_changed: list[str],
    threads_result: dict[str, Any],
    threads_before: dict[str, dict[str, Any]],
    recovered_thread_roots: dict[str, str],
    default_linux_root: str,
    default_effort: str,
    known_roots: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changes: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    known_root_values = {str(Path(path).resolve()) for path in known_roots.values()}

    if global_state_result.get("changed"):
        changes.append(
            {
                "type": "global_state_restore_seed_repair",
                "path": str(global_state_result.get("path", "")).strip(),
                "projectless_thread_ids_removed": len(global_state_result.get("removed_projectless_thread_ids", [])),
                "thread_workspace_hints_removed": len(global_state_result.get("removed_thread_hints", [])),
            }
        )

    if launcher_result.get("needs_repair"):
        changes.append(
            {
                "type": "linux_codex_launcher_shim_rewrite",
                "path": str(launcher_result.get("path", "")).strip(),
                "from": str(launcher_result.get("current_target", "")).strip(),
                "to": str(launcher_result.get("expected_target", "")).strip(),
                "repairable": bool(launcher_result.get("repairable")),
                "live_write_allowed": bool(launcher_result.get("live_write_allowed")),
                "preview_path": str(launcher_result.get("preview_path", "")).strip(),
            }
        )

    for thread_id in global_state_result.get("removed_projectless_thread_ids", []):
        previous = threads_before.get(str(thread_id), {})
        before_cwd = str(previous.get("cwd", "")).strip()
        after_cwd = str(recovered_thread_roots.get(str(thread_id), default_linux_root)).strip()
        if before_cwd != after_cwd:
            entry = {
                "type": "thread_resume_root_recovery",
                "thread_id": str(thread_id),
                "from": before_cwd,
                "to": after_cwd,
            }
            changes.append(entry)
            if before_cwd in known_root_values and after_cwd in known_root_values and before_cwd != after_cwd:
                unexpected.append(dict(entry))
        if str(previous.get("reasoning_effort", "")).strip() == "xhigh":
            changes.append(
                {
                    "type": "thread_reasoning_effort_reset",
                    "thread_id": str(thread_id),
                    "from": "xhigh",
                    "to": default_effort,
                }
            )

    for path in local_env_changed:
        changes.append({"type": "local_environment_root_canonicalize", "path": str(path)})
    for path in sessions_changed:
        changes.append({"type": "session_restore_seed_rewrite", "path": str(path)})
    if int(threads_result.get("changed_rows", 0) or 0) > 0:
        changes.append(
            {
                "type": "threads_db_repair",
                "path": str(threads_result.get("path", "")).strip(),
                "changed_rows": int(threads_result.get("changed_rows", 0) or 0),
            }
        )
    return changes, unexpected


def collect_backup_targets(
    *,
    global_state_result: dict[str, Any],
    launcher_result: dict[str, Any],
    local_env_changed: list[str],
    sessions_changed: list[str],
    threads_result: dict[str, Any],
) -> list[Path]:
    targets: list[Path] = []
    if global_state_result.get("changed"):
        targets.append(Path(str(global_state_result.get("path", "")).strip()))
    if launcher_result.get("needs_repair") and launcher_result.get("live_write_allowed"):
        targets.append(Path(str(launcher_result.get("path", "")).strip()))
    targets.extend(Path(path) for path in local_env_changed if str(path).strip())
    targets.extend(Path(path) for path in sessions_changed if str(path).strip())
    if int(threads_result.get("changed_rows", 0) or 0) > 0:
        targets.append(Path(str(threads_result.get("path", "")).strip()))
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in targets:
        resolved = path.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return ordered


def backup_targets(targets: list[Path], codex_home: Path) -> dict[str, Any]:
    if not targets:
        return {"created": False, "root": "", "files": []}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_root = codex_home / "repair-backups" / timestamp
    files: list[dict[str, str]] = []
    for path in targets:
        try:
            relative = path.relative_to(codex_home)
        except ValueError:
            relative = Path(path.name)
        destination = backup_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        files.append({"source": str(path), "backup_path": str(destination)})
    save_json(
        backup_root / "backup-index.json",
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        },
    )
    return {"created": True, "root": str(backup_root), "files": files}


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_file).expanduser().resolve()
    authority = load_json(AUTHORITY_PATH)
    policy = load_json(ENV_SYNC_POLICY_PATH)
    codex_home = resolve_runtime_codex_home(authority, args.runtime_codex_home)
    lease_homes = runtime_restore_homes(authority)
    if codex_home not in lease_homes:
        lease_homes = [codex_home, *lease_homes]
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    roots = known_linux_roots(authority, lease_homes)
    default_root_name = str(restore.get("default_active_workspace_root", "management"))
    default_linux_root = roots.get(default_root_name, authority["canonical_roots"]["management"])
    default_effort = effective_default_effort(authority)
    stale_markers = stale_path_markers(policy, authority)
    root_map = canonical_root_map(authority, policy, lease_homes)
    allowed_unc_hosts = allowed_hosts(authority, policy)
    state_snapshot = load_json(codex_home / ".codex-global-state.json", default={})
    affected_thread_ids = list(state_snapshot.get("projectless-thread-ids", []))
    threads_before = load_thread_rows(codex_home / "state_5.sqlite", affected_thread_ids)
    resume_candidates = recover_thread_resume_candidates(
        codex_home=codex_home,
        affected_thread_ids=affected_thread_ids,
        linux_roots=roots,
        root_map=root_map,
        allowed_unc_hosts=allowed_unc_hosts,
        stale_markers=stale_markers,
        default_root_name=default_root_name,
    )
    recovered_thread_roots = {
        str(item["thread_id"]): str(item["workspace_root"])
        for item in resume_candidates
        if str(item.get("thread_id", "")).strip() and str(item.get("workspace_root", "")).strip()
    }
    latest_resume = resume_candidates[0] if resume_candidates else None
    preferred_active_root = str((latest_resume or {}).get("workspace_unc_root", "")).strip() or None
    mode = "apply" if args.apply else "dry-run"
    diff_check = git_diff_check_status()

    global_state_result = repair_global_state(
        authority,
        policy,
        codex_home,
        preferred_active_root=preferred_active_root,
        apply=False,
    )
    launcher_result = repair_linux_launcher_shim(authority, apply=False)
    launcher_result["tests_status"] = args.tests_status
    launcher_result["diff_check_status"] = diff_check["status"]
    if args.tests_status != "PASS" and "tests_status" not in launcher_result["live_write_blockers"]:
        launcher_result["live_write_blockers"].append("tests_status")
    if diff_check["status"] != "PASS" and "diff_check_status" not in launcher_result["live_write_blockers"]:
        launcher_result["live_write_blockers"].append("diff_check_status")
    launcher_result["live_write_allowed"] = bool(launcher_result.get("live_write_allowed")) and args.tests_status == "PASS" and diff_check["status"] == "PASS"
    launcher_result["repairable"] = launcher_result["live_write_allowed"] and bool(launcher_result.get("needs_repair"))
    launcher_result["live_write_status"] = "PASS" if launcher_result["live_write_allowed"] else "BLOCKED"
    local_env_changed = repair_local_environments(
        codex_home=codex_home,
        linux_roots=roots,
        root_map=root_map,
        allowed_unc_hosts=allowed_unc_hosts,
        stale_markers=stale_markers,
        apply=False,
    )
    sessions_changed = repair_sessions(
        codex_home=codex_home,
        affected_thread_ids=global_state_result["removed_projectless_thread_ids"],
        recovered_thread_roots=recovered_thread_roots,
        default_linux_root=default_linux_root,
        default_effort=default_effort,
        stale_markers=stale_markers,
        apply=False,
    )
    threads_result = repair_threads_db(
        db_path=codex_home / "state_5.sqlite",
        affected_thread_ids=global_state_result["removed_projectless_thread_ids"],
        recovered_thread_roots=recovered_thread_roots,
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
        apply=False,
    )
    predicted_changes, unexpected_resume_root_rewrites = build_change_entries(
        global_state_result=global_state_result,
        launcher_result=launcher_result,
        local_env_changed=local_env_changed,
        sessions_changed=sessions_changed,
        threads_result=threads_result,
        threads_before=threads_before,
        recovered_thread_roots=recovered_thread_roots,
        default_linux_root=default_linux_root,
        default_effort=default_effort,
        known_roots=roots,
    )

    applied_changes: list[dict[str, Any]] = []
    backup = {"created": False, "root": "", "files": []}
    if args.apply:
        backup = backup_targets(
            collect_backup_targets(
                global_state_result=global_state_result,
                launcher_result=launcher_result,
                local_env_changed=local_env_changed,
                sessions_changed=sessions_changed,
                threads_result=threads_result,
            ),
            codex_home,
        )
        applied_global_state_result = repair_global_state(
            authority,
            policy,
            codex_home,
            preferred_active_root=preferred_active_root,
            apply=True,
        )
        applied_launcher_result = repair_linux_launcher_shim(authority, apply=bool(launcher_result["live_write_allowed"]))
        applied_launcher_result["tests_status"] = args.tests_status
        applied_launcher_result["diff_check_status"] = diff_check["status"]
        applied_launcher_result["live_write_allowed"] = bool(launcher_result["live_write_allowed"])
        if not applied_launcher_result["live_write_allowed"]:
            applied_launcher_result["live_write_blockers"] = list(launcher_result["live_write_blockers"])
        applied_local_env_changed = repair_local_environments(
            codex_home=codex_home,
            linux_roots=roots,
            root_map=root_map,
            allowed_unc_hosts=allowed_unc_hosts,
            stale_markers=stale_markers,
            apply=True,
        )
        applied_sessions_changed = repair_sessions(
            codex_home=codex_home,
            affected_thread_ids=applied_global_state_result["removed_projectless_thread_ids"],
            recovered_thread_roots=recovered_thread_roots,
            default_linux_root=default_linux_root,
            default_effort=default_effort,
            stale_markers=stale_markers,
            apply=True,
        )
        applied_threads_result = repair_threads_db(
            db_path=codex_home / "state_5.sqlite",
            affected_thread_ids=applied_global_state_result["removed_projectless_thread_ids"],
            recovered_thread_roots=recovered_thread_roots,
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
            apply=True,
        )
        applied_changes, unexpected_resume_root_rewrites = build_change_entries(
            global_state_result=applied_global_state_result,
            launcher_result=applied_launcher_result,
            local_env_changed=applied_local_env_changed,
            sessions_changed=applied_sessions_changed,
            threads_result=applied_threads_result,
            threads_before=threads_before,
            recovered_thread_roots=recovered_thread_roots,
            default_linux_root=default_linux_root,
            default_effort=default_effort,
            known_roots=roots,
        )

    launcher_report = launcher_result if not args.apply else applied_launcher_result
    report = {
        "status": collapse_gate_status(
            [
                "BLOCKED" if launcher_report.get("status") in {"FAIL", "BLOCKED"} else "",
                "WARN" if launcher_report.get("status") == "REPAIRABLE" else "",
            ]
        ),
        "schema_version": 1,
        "mode": mode,
        "runtime_codex_home": str(codex_home),
        "baseline": capture_baseline_snapshot(),
        "diff_check": diff_check,
        "launcher_shim": launcher_report,
        "predicted_changes": predicted_changes,
        "applied_changes": applied_changes,
        "resume_candidates": resume_candidates,
        "latest_resume": latest_resume,
        "unexpected_resume_root_rewrites": unexpected_resume_root_rewrites,
        "backup": backup,
    }
    save_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Repair is a reporting and staging surface. Non-pass launcher readiness
    # must stay visible in the JSON report, but it should not be treated as a
    # process error when the script completed deterministically.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
