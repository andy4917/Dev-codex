from __future__ import annotations

import gzip
import json
import re
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devmgmt_runtime.trash import recycle_path


LEGACY_RUNTIME_MARKERS = (
    "/home/andy4917",
    "\\home\\andy4917",
    "c:\\home\\andy4917",
    "\\mnt\\c\\users\\anise",
    "wsl.localhost",
    "devmgmt-wsl",
    "wsl-ubuntu",
    "legacy-linux",
    "legacy-remote",
)
LEGACY_GIT_ORIGIN_MARKERS = (
    "github.com/andy4917/dev-codex",
)
STALE_CLOUD_ENVIRONMENT_MARKERS = (
    "wham-public/",
    "\"workspace_dir\": \"/workspace\"",
    "github.com/andy4917/-.git",
)
STALE_WORKSPACE_MARKERS = (
    "c:\\users\\anise\\documents\\codex",
    "\\\\?\\c:\\users\\anise\\documents\\codex",
    "c:\\users\\anise\\.codex\\worktrees\\",
    "\\\\?\\c:\\users\\anise\\.codex\\worktrees\\",
)
REMOTE_STATE_KEYS = {
    "codex-managed-remote-connections",
    "remote-projects",
}
WORKSPACE_LIST_KEYS = (
    "active-workspace-roots",
    "electron-saved-workspace-roots",
    "project-order",
)
RENDER_CACHE_RELATIVE_DIRS = (
    "Roaming/Codex/Cache",
    "Roaming/Codex/Code Cache",
    "Roaming/Codex/GPUCache",
    "Roaming/Codex/DawnCache",
    "Roaming/Codex/ShaderCache",
    "Roaming/Codex/GrShaderCache",
)
THREAD_ID_RE = re.compile(r"(019[0-9a-f]{5}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


@dataclass(frozen=True)
class MaintenancePaths:
    codex_home: Path
    package_local_cache: Path
    backup_root: Path | None
    archive_root: Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(now: datetime | None = None) -> str:
    return (now or utc_now()).astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def normalize_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return text.replace("/", "\\")


def normalized_marker_text(value: Any) -> str:
    text = str(value or "").strip().replace("/", "\\").lower()
    if text.startswith("\\\\?\\unc\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return text


def contains_legacy_marker(value: Any) -> bool:
    text = normalized_marker_text(value)
    slash_text = str(value or "").strip().replace("\\", "/").lower()
    return any(marker in text or marker.replace("\\", "/") in slash_text for marker in LEGACY_RUNTIME_MARKERS)


def contains_stale_workspace_marker(value: Any) -> bool:
    text = normalized_marker_text(value)
    return any(marker in text for marker in STALE_WORKSPACE_MARKERS)


def contains_legacy_git_origin(value: Any) -> bool:
    text = str(value or "").strip().replace("\\", "/").lower()
    return any(marker in text for marker in LEGACY_GIT_ORIGIN_MARKERS)


def contains_stale_cloud_environment(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    text = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    if any(marker in text for marker in STALE_CLOUD_ENVIRONMENT_MARKERS):
        return True
    return bool(value.get("task_count")) and (
        value.get("workspace_dir") == "/workspace"
        or isinstance(value.get("repo_map"), dict)
        or isinstance(value.get("repos"), list)
    )


def looks_like_windows_path(value: Any) -> bool:
    text = normalize_path_text(value)
    return len(text) >= 3 and text[1:3] == ":\\"


def path_exists(value: Any) -> bool:
    if not looks_like_windows_path(value):
        return False
    return Path(normalize_path_text(value)).exists()


def should_remove_workspace_ref(value: Any, *, remove_missing_paths: bool = True) -> bool:
    if contains_legacy_marker(value) or contains_stale_workspace_marker(value):
        return True
    if remove_missing_paths and looks_like_windows_path(value) and not path_exists(value):
        return True
    return False


def copy_file_backup(path: Path, backup_dir: Path | None) -> Path | None:
    if backup_dir is None:
        return None
    if not path.exists() or not path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / path.name
    shutil.copy2(path, target)
    return target


def backup_sqlite(path: Path, backup_dir: Path | None) -> Path | None:
    if backup_dir is None:
        return None
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / path.name
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return target


def dispose_path(path: Path) -> dict[str, Any]:
    return recycle_path(path)


def sanitize_global_state_payload(
    payload: dict[str, Any],
    *,
    stale_thread_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = json.loads(json.dumps(payload))
    stale_thread_ids = stale_thread_ids or set()
    changes: dict[str, Any] = {
        "removed_remote_auto_connect": [],
        "cleared_remote_state_keys": [],
        "removed_workspace_refs": {},
        "removed_prompt_history_items": 0,
        "removed_projectless_thread_ids": [],
        "removed_sidebar_collapsed_groups": [],
        "removed_workspace_root_labels": [],
        "removed_cloud_task_state_keys": [],
    }

    remote_auto = cleaned.get("remote-connection-auto-connect-by-host-id")
    if isinstance(remote_auto, dict):
        for key in list(remote_auto):
            if contains_legacy_marker(key) or key.lower().startswith("remote-ssh-"):
                changes["removed_remote_auto_connect"].append(key)
                remote_auto.pop(key, None)

    for key in REMOTE_STATE_KEYS:
        value = cleaned.get(key)
        if isinstance(value, list) and value:
            cleaned[key] = []
            changes["cleared_remote_state_keys"].append(key)

    for key in WORKSPACE_LIST_KEYS:
        value = cleaned.get(key)
        if not isinstance(value, list):
            continue
        kept = [item for item in value if not should_remove_workspace_ref(item)]
        removed = [item for item in value if item not in kept]
        if removed:
            cleaned[key] = kept
            changes["removed_workspace_refs"][key] = removed

    atoms = cleaned.get("electron-persisted-atom-state")
    if isinstance(atoms, dict):
        cloud_environment_removed = False
        if contains_stale_cloud_environment(atoms.get("environment")):
            atoms.pop("environment", None)
            cloud_environment_removed = True
            changes["removed_cloud_task_state_keys"].append("electron-persisted-atom-state.environment")
        if cloud_environment_removed and atoms.get("codexCloudAccess") == "enabled":
            atoms.pop("codexCloudAccess", None)
            changes["removed_cloud_task_state_keys"].append("electron-persisted-atom-state.codexCloudAccess")
        history = atoms.get("prompt-history")
        if isinstance(history, list):
            kept_history = [item for item in history if not contains_legacy_marker(item)]
            changes["removed_prompt_history_items"] = len(history) - len(kept_history)
            atoms["prompt-history"] = kept_history
        collapsed = atoms.get("sidebar-collapsed-groups")
        if isinstance(collapsed, dict):
            for key in list(collapsed):
                if contains_legacy_marker(key) or contains_stale_workspace_marker(key):
                    changes["removed_sidebar_collapsed_groups"].append(key)
                    collapsed.pop(key, None)

    projectless = cleaned.get("projectless-thread-ids")
    if stale_thread_ids and isinstance(projectless, list):
        kept_projectless = [item for item in projectless if str(item) not in stale_thread_ids]
        changes["removed_projectless_thread_ids"] = [item for item in projectless if str(item) in stale_thread_ids]
        cleaned["projectless-thread-ids"] = kept_projectless

    root_labels = cleaned.get("electron-workspace-root-labels")
    if isinstance(root_labels, dict):
        for key in list(root_labels):
            if should_remove_workspace_ref(key):
                changes["removed_workspace_root_labels"].append(key)
                root_labels.pop(key, None)

    return cleaned, changes


def sanitize_global_state(
    path: Path,
    backup_dir: Path | None,
    *,
    apply: bool,
    stale_thread_ids: set[str] | None = None,
) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cleaned, changes = sanitize_global_state_payload(payload, stale_thread_ids=stale_thread_ids)
    changed = cleaned != payload
    backup = None
    if apply and changed:
        backup = copy_file_backup(path, backup_dir)
        path.write_text(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "path": str(path),
        "exists": True,
        "changed": changed,
        "applied": bool(apply and changed),
        "backup": str(backup) if backup else None,
        "changes": changes,
    }


def sanitize_cap_sid_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = json.loads(json.dumps(payload))
    changes = {"removed_workspace_by_cwd": []}
    by_cwd = cleaned.get("workspace_by_cwd")
    if isinstance(by_cwd, dict):
        for cwd in list(by_cwd):
            if contains_legacy_marker(cwd) or contains_stale_workspace_marker(cwd):
                changes["removed_workspace_by_cwd"].append(cwd)
                by_cwd.pop(cwd, None)
    return cleaned, changes


def sanitize_cap_sid(path: Path, backup_dir: Path | None, *, apply: bool) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "changed": False}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {"path": str(path), "exists": True, "changed": False, "reason": "empty"}
    payload = json.loads(text)
    cleaned, changes = sanitize_cap_sid_payload(payload)
    changed = cleaned != payload
    backup = None
    if apply and changed:
        backup = copy_file_backup(path, backup_dir)
        path.write_text(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {
        "path": str(path),
        "exists": True,
        "changed": changed,
        "applied": bool(apply and changed),
        "backup": str(backup) if backup else None,
        "changes": changes,
    }


def ambient_suggestion_project_root(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(payload.get("projectRoot") or "")


def inspect_ambient_suggestions(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    findings: list[dict[str, Any]] = []
    for payload_path in sorted(root.glob("*/ambient-suggestions.json")):
        project_root = ambient_suggestion_project_root(payload_path)
        stale = should_remove_workspace_ref(project_root)
        findings.append(
            {
                "path": str(payload_path.parent),
                "project_root": project_root,
                "stale": stale,
                "reason": "legacy_or_missing_project_root" if stale else "",
            }
        )
    return findings


def archive_stale_ambient_suggestions(root: Path, archive_root: Path, *, apply: bool) -> dict[str, Any]:
    findings = inspect_ambient_suggestions(root)
    stale = [item for item in findings if item["stale"]]
    archived: list[dict[str, str]] = []
    disposed: list[dict[str, Any]] = []
    if apply and stale:
        for item in stale:
            source = Path(item["path"])
            disposed_item = dispose_path(source)
            disposed.append(disposed_item)
            archived.append({"source": str(source), "target": "Recycle Bin"})
    return {
        "path": str(root),
        "count": len(findings),
        "stale_count": len(stale),
        "applied": bool(apply and stale),
        "archived": archived,
        "disposed": disposed,
        "disposal_policy": "recycle_bin",
        "stale": stale,
    }


def thread_cwd_is_stale(cwd: str) -> bool:
    if contains_legacy_marker(cwd) or contains_stale_workspace_marker(cwd):
        return True
    if looks_like_windows_path(cwd) and not path_exists(cwd):
        return True
    return False


def thread_is_stale(cwd: str, git_origin_url: str = "") -> tuple[bool, str]:
    if thread_cwd_is_stale(cwd):
        return True, "legacy_or_missing_cwd"
    if contains_legacy_git_origin(git_origin_url):
        return True, "legacy_git_origin"
    return False, ""


def sqlite_table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"pragma table_info({table})").fetchall()}


def inspect_stale_threads(sqlite_path: Path) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {"path": str(sqlite_path), "exists": False, "stale_count": 0}
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=30)
    try:
        columns = sqlite_table_columns(con, "threads")
        git_origin_expr = "git_origin_url" if "git_origin_url" in columns else "'' as git_origin_url"
        rows = con.execute(f"select id, cwd, archived, {git_origin_expr} from threads").fetchall()
    finally:
        con.close()
    stale = []
    for row in rows:
        stale_match, reason = thread_is_stale(str(row[1] or ""), str(row[3] or ""))
        if not int(row[2] or 0) and stale_match:
            stale.append({"id": row[0], "cwd": row[1], "archived": row[2], "git_origin_url": row[3], "reason": reason})
    summary: dict[str, int] = {}
    reason_summary: dict[str, int] = {}
    for row in stale:
        summary[row["cwd"]] = summary.get(row["cwd"], 0) + 1
        reason_summary[row["reason"]] = reason_summary.get(row["reason"], 0) + 1
    return {
        "path": str(sqlite_path),
        "exists": True,
        "thread_count": len(rows),
        "stale_count": len(stale),
        "stale_cwd_summary": summary,
        "stale_reason_summary": reason_summary,
        "stale_thread_ids": [row["id"] for row in stale],
        "stale_threads": stale,
    }


def archive_stale_threads(sqlite_path: Path, backup_dir: Path | None, *, apply: bool, now: datetime | None = None) -> dict[str, Any]:
    report = inspect_stale_threads(sqlite_path)
    if not report.get("exists") or not report.get("stale_count"):
        report["applied"] = False
        return report
    backup = None
    if apply:
        archived_at = int((now or utc_now()).timestamp())
        con = sqlite3.connect(sqlite_path, timeout=30)
        try:
            ids = list(report["stale_thread_ids"])
            con.executemany(
                "update threads set archived = 1, archived_at = ? where id = ? and archived = 0",
                [(archived_at, item) for item in ids],
            )
            con.commit()
        finally:
            con.close()
    report["applied"] = bool(apply)
    report["backup"] = str(backup) if backup else None
    report["backup_policy"] = "disabled_by_policy"
    return report


def inspect_live_thread_overflow(sqlite_path: Path, *, max_live_threads: int) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {"path": str(sqlite_path), "exists": False, "candidate_count": 0}
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select id, title, cwd, archived, updated_at, updated_at_ms, tokens_used
            from threads
            where archived = 0
            order by coalesce(updated_at_ms, updated_at * 1000, 0) desc
            """
        ).fetchall()
    finally:
        con.close()
    keep = rows[:max_live_threads]
    candidates = rows[max_live_threads:]
    return {
        "path": str(sqlite_path),
        "exists": True,
        "max_live_threads": max_live_threads,
        "live_threads_before": len(rows),
        "candidate_count": len(candidates),
        "candidate_thread_ids": [str(row["id"]) for row in candidates],
        "kept_thread_ids": [str(row["id"]) for row in keep],
        "candidate_titles": [
            {
                "id": str(row["id"]),
                "title": str(row["title"] or ""),
                "cwd": str(row["cwd"] or ""),
                "tokens_used": int(row["tokens_used"] or 0),
            }
            for row in candidates
        ],
    }


def archive_live_thread_overflow(
    sqlite_path: Path,
    backup_dir: Path | None,
    *,
    max_live_threads: int,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    report = inspect_live_thread_overflow(sqlite_path, max_live_threads=max_live_threads)
    if not report.get("exists") or not report.get("candidate_count"):
        report["applied"] = False
        return report
    backup = None
    if apply:
        archived_at = int((now or utc_now()).timestamp())
        con = sqlite3.connect(sqlite_path, timeout=30)
        try:
            ids = list(report["candidate_thread_ids"])
            con.executemany(
                "update threads set archived = 1, archived_at = ? where id = ? and archived = 0",
                [(archived_at, item) for item in ids],
            )
            con.commit()
            report["live_threads_after"] = int(con.execute("select count(*) from threads where archived = 0").fetchone()[0])
        finally:
            con.close()
    report["applied"] = bool(apply)
    report["backup"] = str(backup) if backup else None
    report["backup_policy"] = "disabled_by_policy"
    return report


def archived_thread_ids(sqlite_path: Path) -> set[str]:
    if not sqlite_path.exists():
        return set()
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=30)
    try:
        return {
            str(row[0])
            for row in con.execute("select id from threads where archived = 1").fetchall()
        }
    finally:
        con.close()


def session_thread_id(path: Path) -> str | None:
    match = THREAD_ID_RE.search(path.name)
    return match.group(1) if match else None


def remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def archive_session_files(
    sessions_root: Path,
    archive_root: Path,
    *,
    archived_ids: set[str],
    max_session_files: int,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    files = sorted(sessions_root.rglob("*.jsonl")) if sessions_root.exists() else []
    selected: dict[Path, str] = {}
    for path in files:
        thread_id = session_thread_id(path)
        if thread_id and thread_id in archived_ids:
            selected[path] = "archived_thread"
    remaining = [path for path in files if path not in selected]
    overflow_count = max(0, len(remaining) - max_session_files)
    if overflow_count:
        for path in sorted(remaining, key=lambda item: item.stat().st_mtime)[:overflow_count]:
            selected[path] = "exceeds_max_session_files"

    archive_path = None
    total_bytes = sum(path.stat().st_size for path in selected)
    disposed: list[dict[str, Any]] = []
    if apply and selected:
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / f"codex-sessions-{stamp(now)}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(selected):
                zf.write(path, path.relative_to(sessions_root))
        for path in selected:
            disposed.append(dispose_path(path))
        remove_empty_dirs(sessions_root)

    return {
        "path": str(sessions_root),
        "max_session_files": max_session_files,
        "total_files_before": len(files),
        "candidate_count": len(selected),
        "candidate_mb": round(total_bytes / 1024 / 1024, 2),
        "candidate_reasons": {str(path): reason for path, reason in sorted(selected.items())},
        "applied": bool(apply and selected),
        "archive_path": str(archive_path) if archive_path else None,
        "disposed": disposed,
        "disposal_policy": "recycle_bin_after_archive",
        "total_files_after": max_session_files if apply and overflow_count else len(files) - (len(selected) if apply else 0),
    }


def archive_desktop_log_files(log_root: Path, archive_root: Path, *, retention_days: int, apply: bool, now: datetime | None = None) -> dict[str, Any]:
    now = now or utc_now()
    cutoff = now.timestamp() - retention_days * 86400
    files = [
        path
        for path in sorted(log_root.rglob("*"))
        if path.is_file() and path.stat().st_mtime <= cutoff
    ] if log_root.exists() else []
    total_bytes = sum(path.stat().st_size for path in files)
    archive_path = None
    disposed: list[dict[str, Any]] = []
    if apply and files:
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / f"codex-desktop-logs-{stamp(now)}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                zf.write(path, path.relative_to(log_root))
        for path in files:
            disposed.append(dispose_path(path))
    return {
        "path": str(log_root),
        "retention_days": retention_days,
        "candidate_count": len(files),
        "candidate_mb": round(total_bytes / 1024 / 1024, 2),
        "applied": bool(apply and files),
        "archive_path": str(archive_path) if archive_path else None,
        "disposed": disposed,
        "disposal_policy": "recycle_bin_after_archive",
    }


def _tree_size(path: Path) -> tuple[int, int]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    return len(files), sum(item.stat().st_size for item in files)


def cleanup_render_cache_dirs(package_local_cache: Path, *, apply: bool) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    disposed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for relative in RENDER_CACHE_RELATIVE_DIRS:
        path = package_local_cache / Path(relative)
        if not path.exists():
            continue
        file_count, total_bytes = _tree_size(path)
        if file_count <= 0:
            continue
        findings.append(
            {
                "path": str(path),
                "relative_path": relative,
                "file_count": file_count,
                "mb": round(total_bytes / 1024 / 1024, 2),
            }
        )
    if apply:
        for item in findings:
            path = Path(str(item["path"]))
            try:
                disposed.append(dispose_path(path))
            except OSError as exc:
                failed.append({"path": str(path), "status": "FAILED", "error": str(exc)})
    return {
        "path": str(package_local_cache),
        "candidate_count": len(findings),
        "candidate_mb": round(sum(float(item["mb"]) for item in findings), 2),
        "candidates": findings,
        "applied": bool(apply and findings and not failed),
        "disposed": disposed,
        "failed": failed,
        "disposal_policy": "recycle_bin_cache_only",
    }


def export_rows_to_gzip(rows: list[sqlite3.Row], columns: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({key: row[key] for key in columns}, ensure_ascii=False) + "\n")


def compact_logs_sqlite(
    sqlite_path: Path,
    backup_dir: Path | None,
    archive_root: Path,
    *,
    retention_days: int,
    max_rows: int,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {"path": str(sqlite_path), "exists": False, "applied": False}
    now = now or utc_now()
    cutoff_ts = int(now.timestamp()) - retention_days * 86400
    con = sqlite3.connect(sqlite_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        total_rows = int(con.execute("select count(*) from logs").fetchone()[0])
        old_rows_count = int(con.execute("select count(*) from logs where ts <= ?", (cutoff_ts,)).fetchone()[0])
        overflow_count = max(0, total_rows - old_rows_count - max_rows)
        candidates = old_rows_count + overflow_count
        result = {
            "path": str(sqlite_path),
            "exists": True,
            "retention_days": retention_days,
            "max_rows": max_rows,
            "total_rows_before": total_rows,
            "old_rows_count": old_rows_count,
            "overflow_count": overflow_count,
            "candidate_rows": candidates,
            "applied": False,
            "archive_path": None,
            "backup": None,
            "vacuum": "not_run",
        }
        if not apply or candidates == 0:
            return result
        backup = None
        rows = con.execute("select * from logs where ts <= ? order by ts, id", (cutoff_ts,)).fetchall()
        columns = [item[0] for item in con.execute("select * from logs limit 0").description]
        if overflow_count:
            overflow_rows = con.execute(
                "select * from logs where ts >= ? order by ts, id limit ?",
                (cutoff_ts, overflow_count),
            ).fetchall()
            rows.extend(overflow_rows)
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_path = archive_root / f"codex-logs-sqlite-{stamp(now)}.jsonl.gz"
        export_rows_to_gzip(rows, columns, archive_path)
        ids = [row["id"] for row in rows]
        con.executemany("delete from logs where id = ?", [(item,) for item in ids])
        con.commit()
        try:
            con.execute("pragma wal_checkpoint(truncate)")
            con.execute("vacuum")
            result["vacuum"] = "ok"
        except sqlite3.Error as exc:
            result["vacuum"] = f"failed: {exc}"
        result["applied"] = True
        result["archive_path"] = str(archive_path)
        result["backup"] = str(backup) if backup else None
        result["backup_policy"] = "disabled_by_policy"
        result["total_rows_after"] = int(con.execute("select count(*) from logs").fetchone()[0])
        return result
    finally:
        con.close()


def default_paths(codex_home: Path | None = None, package_local_cache: Path | None = None) -> MaintenancePaths:
    home = codex_home or Path.home() / ".codex"
    cache = package_local_cache or Path.home() / "AppData" / "Local" / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0" / "LocalCache"
    return MaintenancePaths(
        codex_home=home,
        package_local_cache=cache,
        backup_root=None,
        archive_root=home / "maintenance-archives",
    )


def run_maintenance(
    *,
    paths: MaintenancePaths,
    apply: bool,
    retention_days: int,
    max_log_rows: int,
    max_session_files: int,
    max_live_threads: int = 12,
    cleanup_render_cache: bool = False,
    keep_backups: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utc_now()
    run_id = stamp(now)
    backup_dir = None
    archive_dir = paths.archive_root / run_id
    report = {
        "status": "PASS",
        "checked_at": now.isoformat(),
        "applied": apply,
        "backup_policy": "disabled_by_policy_recycle_bin_required",
        "backup_dir": str(backup_dir) if backup_dir else None,
        "archive_dir": str(archive_dir),
        "temporary_artifact_disposal": "recycle_bin",
        "keep_backups_requested": bool(keep_backups),
        "actions": {},
        "warnings": [],
    }
    if keep_backups:
        report["warnings"].append("--keep-backups was requested but ignored; backup and temporary cleanup artifacts must use Recycle Bin disposal.")
    try:
        stale_thread_preview = inspect_stale_threads(paths.codex_home / "state_5.sqlite")
        stale_thread_ids = {str(item) for item in stale_thread_preview.get("stale_thread_ids", [])}
        report["actions"]["global_state"] = sanitize_global_state(
            paths.codex_home / ".codex-global-state.json",
            backup_dir,
            apply=apply,
            stale_thread_ids=stale_thread_ids,
        )
        report["actions"]["cap_sid"] = sanitize_cap_sid(paths.codex_home / "cap_sid", backup_dir, apply=apply)
        report["actions"]["ambient_suggestions"] = archive_stale_ambient_suggestions(
            paths.codex_home / "ambient-suggestions",
            archive_dir,
            apply=apply,
        )
        report["actions"]["threads"] = archive_stale_threads(
            paths.codex_home / "state_5.sqlite",
            backup_dir,
            apply=apply,
            now=now,
        )
        report["actions"]["live_threads"] = archive_live_thread_overflow(
            paths.codex_home / "state_5.sqlite",
            backup_dir,
            max_live_threads=max_live_threads,
            apply=apply,
            now=now,
        )
        report["actions"]["sessions"] = archive_session_files(
            paths.codex_home / "sessions",
            archive_dir,
            archived_ids=archived_thread_ids(paths.codex_home / "state_5.sqlite") | stale_thread_ids,
            max_session_files=max_session_files,
            apply=apply,
            now=now,
        )
        report["actions"]["desktop_logs"] = archive_desktop_log_files(
            paths.package_local_cache / "Local" / "Codex" / "Logs",
            archive_dir,
            retention_days=retention_days,
            apply=apply,
            now=now,
        )
        report["actions"]["render_cache"] = cleanup_render_cache_dirs(
            paths.package_local_cache,
            apply=apply and cleanup_render_cache,
        )
        report["actions"]["logs_sqlite"] = compact_logs_sqlite(
            paths.codex_home / "logs_2.sqlite",
            backup_dir,
            archive_dir,
            retention_days=retention_days,
            max_rows=max_log_rows,
            apply=apply,
            now=now,
        )
    except Exception as exc:  # pragma: no cover - defensive report boundary
        report["status"] = "WARN"
        report["warnings"].append(f"maintenance failed before completion: {type(exc).__name__}: {exc}")
    for action in report["actions"].values():
        if isinstance(action, dict) and action.get("vacuum", "").startswith("failed:"):
            report["status"] = "WARN"
            report["warnings"].append(str(action["vacuum"]))
        if isinstance(action, dict) and action.get("failed"):
            report["status"] = "WARN"
            report["warnings"].append(f"maintenance action failed: {action['failed']}")
    return report
