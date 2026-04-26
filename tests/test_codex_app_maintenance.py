from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from devmgmt_runtime.codex_app_maintenance import (
    archive_desktop_log_files,
    archive_live_thread_overflow,
    archive_session_files,
    archive_stale_threads,
    compact_logs_sqlite,
    cleanup_render_cache_dirs,
    default_paths,
    run_maintenance,
    sanitize_cap_sid_payload,
    sanitize_global_state_payload,
)


class CodexAppMaintenanceTests(unittest.TestCase):
    def _fake_dispose(self, path: Path) -> dict[str, object]:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"path": str(path), "status": "RECYCLED", "method": "test", "recycle_bin": True}

    def test_global_state_sanitizer_removes_legacy_remote_and_workspace_refs(self) -> None:
        payload = {
            "remote-connection-auto-connect-by-host-id": {
                "remote-ssh-codex-managed:devmgmt-wsl": True,
                "local": True,
            },
            "remote-projects": [{"path": "/home/andy4917/Dev-Management"}],
            "electron-saved-workspace-roots": [
                "C:\\Users\\anise\\code\\Dev-Management",
                "\\\\wsl.localhost\\Ubuntu\\home\\andy4917\\Dev-Management",
            ],
            "electron-persisted-atom-state": {
                "prompt-history": [
                    "open C:\\Users\\anise\\code\\Dev-Management",
                    "open /home/andy4917/Dev-Management",
                ],
                "sidebar-collapsed-groups": {
                    "/home/andy4917/Dev-Management": True,
                    "C:\\Users\\anise\\code\\Dev-Management": False,
                },
            },
            "projectless-thread-ids": ["current", "legacy"],
        }

        cleaned, changes = sanitize_global_state_payload(payload, stale_thread_ids={"legacy"})

        self.assertEqual(cleaned["remote-connection-auto-connect-by-host-id"], {"local": True})
        self.assertEqual(cleaned["remote-projects"], [])
        self.assertEqual(cleaned["electron-saved-workspace-roots"], ["C:\\Users\\anise\\code\\Dev-Management"])
        self.assertEqual(cleaned["electron-persisted-atom-state"]["prompt-history"], ["open C:\\Users\\anise\\code\\Dev-Management"])
        self.assertEqual(
            cleaned["electron-persisted-atom-state"]["sidebar-collapsed-groups"],
            {"C:\\Users\\anise\\code\\Dev-Management": False},
        )
        self.assertEqual(cleaned["projectless-thread-ids"], ["current"])
        self.assertEqual(changes["removed_prompt_history_items"], 1)
        self.assertEqual(changes["removed_projectless_thread_ids"], ["legacy"])
        self.assertEqual(changes["removed_sidebar_collapsed_groups"], ["/home/andy4917/Dev-Management"])

    def test_cap_sid_sanitizer_removes_legacy_workspace_mapping(self) -> None:
        payload = {
            "workspace": "sid",
            "workspace_by_cwd": {
                "c:/users/anise/code/dev-management": "keep",
                "//?/unc/wsl.localhost/ubuntu/home/andy4917/dev-management": "drop",
            },
        }

        cleaned, changes = sanitize_cap_sid_payload(payload)

        self.assertEqual(cleaned["workspace_by_cwd"], {"c:/users/anise/code/dev-management": "keep"})
        self.assertEqual(changes["removed_workspace_by_cwd"], ["//?/unc/wsl.localhost/ubuntu/home/andy4917/dev-management"])

    def test_archive_stale_threads_marks_legacy_cwd_inactive(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = root / "state_5.sqlite"
            con = sqlite3.connect(db)
            con.execute("create table threads (id text primary key, cwd text not null, archived integer not null, archived_at integer)")
            con.executemany(
                "insert into threads (id, cwd, archived, archived_at) values (?, ?, ?, ?)",
                [
                    ("current", "C:\\Users\\anise\\code\\Dev-Management", 0, None),
                    ("legacy", "/home/andy4917/Dev-Management", 0, None),
                ],
            )
            con.commit()
            con.close()

            report = archive_stale_threads(db, root / "backup", apply=True, now=now)

            self.assertEqual(report["stale_count"], 1)
            verify = sqlite3.connect(db)
            try:
                rows = dict(verify.execute("select id, archived from threads").fetchall())
            finally:
                verify.close()
            self.assertEqual(rows, {"current": 0, "legacy": 1})
            self.assertIsNone(report["backup"])
            self.assertEqual(report["backup_policy"], "disabled_by_policy")

    def test_archive_live_thread_overflow_keeps_newest_threads(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = root / "state_5.sqlite"
            con = sqlite3.connect(db)
            con.execute(
                "create table threads (id text primary key, title text, cwd text not null, archived integer not null, archived_at integer, updated_at integer, updated_at_ms integer, tokens_used integer not null default 0)"
            )
            con.executemany(
                "insert into threads (id, title, cwd, archived, archived_at, updated_at, updated_at_ms, tokens_used) values (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("newest", "Newest", "C:\\Users\\anise\\code\\Dev-Management", 0, None, 30, 30000, 3),
                    ("middle", "Middle", "C:\\Users\\anise\\code\\Dev-Management", 0, None, 20, 20000, 2),
                    ("oldest", "Oldest", "C:\\Users\\anise\\code\\Dev-Management", 0, None, 10, 10000, 1),
                ],
            )
            con.commit()
            con.close()

            report = archive_live_thread_overflow(db, root / "backup", max_live_threads=2, apply=True, now=now)

            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["candidate_thread_ids"], ["oldest"])
            self.assertEqual(report["live_threads_after"], 2)
            verify = sqlite3.connect(db)
            try:
                rows = dict(verify.execute("select id, archived from threads").fetchall())
            finally:
                verify.close()
            self.assertEqual(rows, {"newest": 0, "middle": 0, "oldest": 1})

    def test_archive_desktop_log_files_zips_old_logs(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_root = root / "logs"
            old_dir = log_root / "2026" / "04" / "20"
            old_dir.mkdir(parents=True)
            old_log = old_dir / "old.log"
            old_log.write_text("old", encoding="utf-8")
            old_time = datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp()
            old_log.touch()
            import os

            os.utime(old_log, (old_time, old_time))

            with patch("devmgmt_runtime.codex_app_maintenance.dispose_path", side_effect=self._fake_dispose):
                report = archive_desktop_log_files(log_root, root / "archive", retention_days=2, apply=True, now=now)

            self.assertEqual(report["candidate_count"], 1)
            self.assertFalse(old_log.exists())
            self.assertTrue(Path(str(report["archive_path"])).exists())
            self.assertEqual(report["disposal_policy"], "recycle_bin_after_archive")
            self.assertTrue(report["disposed"][0]["recycle_bin"])

    def test_cleanup_render_cache_dirs_recycles_only_disposable_cache_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_cache = root / "LocalCache"
            cache = package_cache / "Roaming" / "Codex" / "Cache"
            gpu_cache = package_cache / "Roaming" / "Codex" / "GPUCache"
            local_storage = package_cache / "Roaming" / "Codex" / "Local Storage"
            cache.mkdir(parents=True)
            gpu_cache.mkdir(parents=True)
            local_storage.mkdir(parents=True)
            (cache / "data_1").write_text("cache", encoding="utf-8")
            (gpu_cache / "data_2").write_text("gpu", encoding="utf-8")
            (local_storage / "keep").write_text("state", encoding="utf-8")

            with patch("devmgmt_runtime.codex_app_maintenance.dispose_path", side_effect=self._fake_dispose):
                report = cleanup_render_cache_dirs(package_cache, apply=True)

            self.assertEqual(report["candidate_count"], 2)
            self.assertFalse(cache.exists())
            self.assertFalse(gpu_cache.exists())
            self.assertTrue(local_storage.exists())
            self.assertEqual(report["disposal_policy"], "recycle_bin_cache_only")

    def test_archive_session_files_compresses_archived_and_over_limit_sessions(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions = root / "sessions" / "2026" / "04" / "20"
            sessions.mkdir(parents=True)
            archived = sessions / "rollout-2026-04-20T00-00-00-019dabcd-0000-7000-8000-000000000001.jsonl"
            old = sessions / "rollout-2026-04-20T00-00-00-019dabcd-0000-7000-8000-000000000002.jsonl"
            keep = sessions / "rollout-2026-04-20T00-00-00-019dabcd-0000-7000-8000-000000000003.jsonl"
            for item in (archived, old, keep):
                item.write_text(item.name, encoding="utf-8")

            with patch("devmgmt_runtime.codex_app_maintenance.dispose_path", side_effect=self._fake_dispose):
                report = archive_session_files(
                    root / "sessions",
                    root / "archive",
                    archived_ids={"019dabcd-0000-7000-8000-000000000001"},
                    max_session_files=1,
                    apply=True,
                    now=now,
                )

            self.assertEqual(report["candidate_count"], 2)
            self.assertFalse(archived.exists())
            self.assertFalse(old.exists())
            self.assertTrue(keep.exists())
            self.assertTrue(Path(str(report["archive_path"])).exists())
            self.assertEqual(report["disposal_policy"], "recycle_bin_after_archive")

    def test_run_maintenance_does_not_create_backups_by_default(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_home = root / ".codex"
            codex_home.mkdir()
            (codex_home / ".codex-global-state.json").write_text(
                json.dumps(
                    {
                        "remote-connection-auto-connect-by-host-id": {
                            "remote-ssh-codex-managed:devmgmt-wsl": True
                        }
                    }
                ),
                encoding="utf-8",
            )
            con = sqlite3.connect(codex_home / "state_5.sqlite")
            con.execute("create table threads (id text primary key, cwd text not null, archived integer not null, archived_at integer)")
            con.commit()
            con.close()
            con = sqlite3.connect(codex_home / "logs_2.sqlite")
            con.execute("create table logs (id integer primary key, ts integer, level text, target text, feedback_log_body text)")
            con.commit()
            con.close()

            paths = default_paths(codex_home, root / "LocalCache")
            report = run_maintenance(
                paths=paths,
                apply=True,
                retention_days=3,
                max_log_rows=50000,
                max_session_files=80,
                cleanup_render_cache=False,
                now=now,
            )

            self.assertEqual(report["backup_policy"], "disabled_by_policy_recycle_bin_required")
            self.assertIsNone(report["backup_dir"])
            self.assertFalse((codex_home / "maintenance-backups").exists())
            self.assertEqual(report["temporary_artifact_disposal"], "recycle_bin")

    def test_compact_logs_sqlite_exports_and_deletes_old_rows(self) -> None:
        now = datetime(2026, 4, 26, tzinfo=timezone.utc)
        old_ts = int(datetime(2026, 4, 20, tzinfo=timezone.utc).timestamp())
        new_ts = int(datetime(2026, 4, 26, tzinfo=timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = root / "logs_2.sqlite"
            con = sqlite3.connect(db)
            con.execute("create table logs (id integer primary key, ts integer, level text, target text, feedback_log_body text)")
            con.executemany(
                "insert into logs (id, ts, level, target, feedback_log_body) values (?, ?, ?, ?, ?)",
                [(1, old_ts, "TRACE", "old", "old body"), (2, new_ts, "INFO", "new", "new body")],
            )
            con.commit()
            con.close()

            report = compact_logs_sqlite(
                db,
                root / "backup",
                root / "archive",
                retention_days=2,
                max_rows=50,
                apply=True,
                now=now,
            )

            self.assertEqual(report["candidate_rows"], 1)
            self.assertEqual(report["total_rows_after"], 1)
            self.assertIsNone(report["backup"])
            self.assertEqual(report["backup_policy"], "disabled_by_policy")
            archive_path = Path(str(report["archive_path"]))
            with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
                exported = [json.loads(line) for line in handle]
            self.assertEqual(exported[0]["id"], 1)


if __name__ == "__main__":
    unittest.main()
