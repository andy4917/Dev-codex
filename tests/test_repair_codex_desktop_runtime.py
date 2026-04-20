from __future__ import annotations

import importlib.util
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "repair_codex_desktop_runtime.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("repair_codex_desktop_runtime", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load repair_codex_desktop_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def _create_threads_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                title TEXT,
                cwd TEXT,
                first_user_message TEXT,
                updated_at INTEGER,
                updated_at_ms INTEGER,
                archived INTEGER,
                reasoning_effort TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class RepairCodexDesktopRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.original_distro = self.module.current_wsl_distro
        self.original_resolve_codex_home = self.module.resolve_codex_home
        self.original_management_root = self.module.MANAGEMENT_ROOT
        self.original_authority_path = self.module.AUTHORITY_PATH
        self.original_env_sync_policy_path = self.module.ENV_SYNC_POLICY_PATH
        self.original_report_path = self.module.REPORT_PATH
        self.module.current_wsl_distro = lambda: "Ubuntu"
        self.addCleanup(setattr, self.module, "current_wsl_distro", self.original_distro)
        self.addCleanup(setattr, self.module, "resolve_codex_home", self.original_resolve_codex_home)
        self.addCleanup(setattr, self.module, "MANAGEMENT_ROOT", self.original_management_root)
        self.addCleanup(setattr, self.module, "AUTHORITY_PATH", self.original_authority_path)
        self.addCleanup(setattr, self.module, "ENV_SYNC_POLICY_PATH", self.original_env_sync_policy_path)
        self.addCleanup(setattr, self.module, "REPORT_PATH", self.original_report_path)

    def _configure_runtime_fixture(self, tmp: Path) -> dict[str, Path]:
        management_root = tmp / "Dev-Management"
        linux_codex = tmp / "linux" / ".codex"
        windows_codex = tmp / "windows" / ".codex"
        linux_launcher = tmp / "linux-home" / ".local" / "bin" / "codex"
        windows_launcher = windows_codex / "bin" / "wsl" / "codex"
        product_root = tmp / "Dev-Product"
        reservation_root = product_root / "reservation-system"
        management_root.mkdir(parents=True)
        reservation_root.mkdir(parents=True)
        (management_root / "reports").mkdir(parents=True, exist_ok=True)
        (linux_codex / "state" / "workspace-authority").mkdir(parents=True, exist_ok=True)
        _write_json(
            linux_codex / "state" / "workspace-authority" / "reservation-system.json",
            {"workspace_root": str(reservation_root)},
        )
        (linux_codex / "config.toml").parent.mkdir(parents=True, exist_ok=True)
        (linux_codex / "config.toml").write_text('model_reasoning_effort = "high"\n', encoding="utf-8")

        authority = {
            "canonical_roots": {
                "management": str(management_root),
                "product": str(product_root),
                "reservation-system": str(reservation_root),
            },
            "canonical_execution_surface": {
                "id": "ssh-devmgmt-wsl",
                "host_alias": "devmgmt-wsl",
                "repo_root": str(management_root),
                "forbidden_primary_resolution": "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            },
            "forbidden_primary_runtime_paths": [
                "/mnt/c/Users/anise/.codex/bin/wsl",
                "/mnt/c/Users/anise/.codex/tmp/arg0",
                ".codex/bin/wsl/codex",
            ],
            "generation_targets": {
                "global_config": {"model_reasoning_effort": "high"},
                    "global_runtime": {
                        "linux": {
                            "agents": str(linux_codex / "AGENTS.md"),
                            "config": str(linux_codex / "config.toml"),
                            "hooks_config": str(linux_codex / "hooks.json"),
                            "launcher": str(linux_launcher),
                        },
                        "windows_mirror": {
                            "agents": str(windows_codex / "AGENTS.md"),
                            "config": str(windows_codex / "config.toml"),
                            "hooks_config": str(windows_codex / "hooks.json"),
                            "wsl_launcher": str(windows_launcher),
                        },
                    },
                },
            "runtime_layering": {
                "restore_seed_policy": {
                    "preferred_windows_access_host": "wsl.localhost",
                    "allowed_windows_access_hosts": ["wsl.localhost", "wsl$"],
                    "default_active_workspace_root": "management",
                    "open_target_global": "wsl",
                    "integrated_terminal_shell": "wsl",
                    "follow_up_queue_mode": "steer",
                    "conversation_detail_mode": "steps",
                    "terminal_restore_policy": "background",
                }
            },
            "hardcoding_definition": {
                "path_rules": {
                    "legacy_repo_paths_to_remove": [],
                }
            },
        }
        policy = {
            "canonical_wsl": {"preferred_windows_access_host": "wsl.localhost", "windows_access_hosts": ["wsl.localhost", "wsl$"]},
            "legacy_mount": {"blocked_prefixes": []},
            "stale_workspace_markers": ["windows-user-mount"],
        }
        _write_json(management_root / "contracts" / "workspace_authority.json", authority)
        _write_json(management_root / "contracts" / "environment_sync_policy.json", policy)
        _write_json(
            management_root / "reports" / "audit.final.json",
            {
                "status": "PASS",
                "windows_runtime_mirror_check": {"status": "PASS"},
                "wsl_launcher_check": {"status": "PASS"},
                "runtime_restore_seed_violations": [],
            },
        )
        _write_json(
            management_root / "reports" / "global-runtime.json",
            {
                "status": "PASS",
                "canonical_execution_status": "PASS",
                "remote_repo_root_status": {"status": "PASS"},
                "remote_codex_resolution_status": {"status": "PASS"},
                "remote_native_codex_status": {"status": "PASS", "selected_path": "/usr/local/bin/codex"},
                "remote_path_contamination_status": {"status": "PASS"},
                "local_path_precedence_status": {"status": "PASS"},
                "wrapper_target_safety_status": {"status": "PASS"},
                "ssh_canonical_runtime": {
                    "canonical_ssh_runtime_status": {"status": "PASS"},
                    "remote_repo_root_status": {"status": "PASS"},
                    "remote_codex_resolution_status": {"status": "PASS"},
                    "remote_native_codex_status": {"status": "PASS", "selected_path": "/usr/local/bin/codex"},
                    "remote_path_contamination_status": {"status": "PASS"},
                },
                "local_runtime_surface": {
                    "local_path_precedence_status": {"status": "PASS"},
                },
            },
        )

        self.module.MANAGEMENT_ROOT = management_root
        self.module.AUTHORITY_PATH = management_root / "contracts" / "workspace_authority.json"
        self.module.ENV_SYNC_POLICY_PATH = management_root / "contracts" / "environment_sync_policy.json"
        self.module.REPORT_PATH = management_root / "reports" / "codex-runtime-repair.json"
        self.module.resolve_codex_home = lambda: linux_codex
        windows_launcher.parent.mkdir(parents=True, exist_ok=True)
        windows_launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        windows_launcher.chmod(0o755)
        linux_launcher.parent.mkdir(parents=True, exist_ok=True)
        linux_launcher.write_text(self.module.render_linux_launcher(authority), encoding="utf-8")
        linux_launcher.chmod(0o755)

        return {
            "management_root": management_root,
            "linux_codex": linux_codex,
            "linux_launcher": linux_launcher,
            "windows_codex": windows_codex,
            "windows_launcher": windows_launcher,
            "product_root": product_root,
            "reservation_root": reservation_root,
            "report_path": self.module.REPORT_PATH,
        }

    def _seed_runtime_drift(self, fixture: dict[str, Path]) -> None:
        windows_codex = fixture["windows_codex"]
        management_root = fixture["management_root"]
        reservation_root = fixture["reservation_root"]
        stale_launcher_target = windows_codex / "bin" / "wsl" / "old-codex"
        fixture["linux_launcher"].write_text(
            "#!/usr/bin/env bash\n"
            f'target="{stale_launcher_target}"\n'
            'exec "$target" "$@"\n',
            encoding="utf-8",
        )
        fixture["linux_launcher"].chmod(0o755)
        _write_json(
            windows_codex / ".codex-global-state.json",
            {
                "projectless-thread-ids": ["thread-1"],
                "thread-workspace-root-hints": {"thread-1": "/mnt/c/Users/anise/Documents/Codex"},
                "active-workspace-roots": [],
                "electron-saved-workspace-roots": [],
                "project-order": [],
            },
        )
        _write_json(
            windows_codex / "local-environments" / "reservation.json",
            {"workspace_root": "/mnt/c/Users/anise/Documents/Codex"},
        )
        session_path = windows_codex / "sessions" / "2026" / "04" / "17" / "rollout-thread-1.jsonl"
        _write_jsonl(
            session_path,
            [
                {"type": "session_meta", "payload": {"id": "thread-1", "cwd": str(management_root), "reasoning_effort": "xhigh"}},
                {"type": "turn_context", "payload": {"cwd": "/mnt/c/Users/anise/Documents/Codex", "reasoning_effort": "xhigh"}},
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "content": [
                            {
                                "text": (
                                    "실무적으로 보면, 다시 시작할 위치는 이렇게 잡는 게 맞습니다.\n"
                                    f"- UI/화면 기준 마지막 작업 위치: {reservation_root / 'ui-workbench' / 'public' / 'stitch-recovery'}\n"
                                    "- 현재 남은 진짜 일: 운영 환경 재검증과 수동 close-out 확인."
                                )
                            }
                        ],
                    },
                },
            ],
        )

        db_path = windows_codex / "state_5.sqlite"
        _create_threads_db(db_path)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO threads (id, title, cwd, first_user_message, updated_at, updated_at_ms, archived, reasoning_effort)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("thread-1", "resume", str(management_root), "", 1, 1, 0, "xhigh"),
            )
            conn.commit()
        finally:
            conn.close()

    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        previous_argv = sys.argv[:]
        try:
            sys.argv = ["repair_codex_desktop_runtime.py", *argv]
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = self.module.main()
        finally:
            sys.argv = previous_argv
        return exit_code, stdout.getvalue() + stderr.getvalue()

    def test_runtime_restore_codex_home_prefers_authority_windows_mirror_when_restore_state_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_codex = tmp / "linux" / ".codex"
            windows_codex = tmp / "windows" / ".codex"
            self.module.resolve_codex_home = lambda: linux_codex
            _write_json(windows_codex / ".codex-global-state.json", {})

            authority = {
                "generation_targets": {
                    "global_runtime": {
                        "linux": {"agents": str(linux_codex / "AGENTS.md")},
                        "windows_mirror": {"agents": str(windows_codex / "AGENTS.md")},
                    }
                }
            }

            resolved = self.module.runtime_restore_codex_home(authority)

        self.assertEqual(resolved, windows_codex)

    def test_recover_thread_resume_candidates_prefers_session_evidence_and_extracts_briefing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            windows_codex = tmp / "windows" / ".codex"
            management_root = tmp / "Dev-Management"
            product_root = tmp / "Dev-Product"
            reservation_root = product_root / "reservation-system"
            management_root.mkdir(parents=True)
            reservation_root.mkdir(parents=True)

            db_path = windows_codex / "state_5.sqlite"
            _create_threads_db(db_path)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO threads (id, title, cwd, first_user_message, updated_at, updated_at_ms, archived, reasoning_effort)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "thread-1",
                        "작업관리자 진행 위치 불러오고 브리핑",
                        str(management_root),
                        "UH 작업관리자 마지막 진행 위치 불러오고 어떤게 남았는지 브리핑",
                        1_776_444_263,
                        1_776_444_263_000,
                        0,
                        "high",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            session_path = windows_codex / "sessions" / "2026" / "04" / "17" / "rollout-thread-1.jsonl"
            _write_jsonl(
                session_path,
                [
                    {"type": "session_meta", "payload": {"id": "thread-1", "cwd": str(management_root)}},
                    {"type": "event_msg", "payload": {"type": "user_message", "text": "UH 작업관리자 마지막 진행 위치 불러오고 어떤게 남았는지 브리핑"}},
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "output": str(reservation_root / "ui-workbench" / "public" / "stitch-recovery" / "manifest.json"),
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "content": [
                                {
                                    "text": (
                                        "실무적으로 보면, 다시 시작할 위치는 이렇게 잡는 게 맞습니다.\n"
                                        f"- UI/화면 기준 마지막 작업 위치: {reservation_root / 'ui-workbench' / 'public' / 'stitch-recovery'} 와 stories/stitchRecovery.stories.js\n"
                                        "- 제품/운영 기준 마지막 완료 위치: GATE-VERIFY PASS까지 닫힌 상태.\n"
                                        "- 현재 남은 진짜 일: 운영 환경 재검증과 수동 close-out 확인, 그리고 필요하면 UH 작업관리자 복구 산출물을 실제 앱 화면으로 다시 연결하는 작업."
                                    )
                                }
                            ],
                        },
                    },
                ],
            )

            linux_roots = {
                "management": str(management_root),
                "product": str(product_root),
                "reservation-system": str(reservation_root),
            }
            root_map = {
                name: self.module.to_unc_path(path, "wsl.localhost")
                for name, path in linux_roots.items()
            }

            candidates = self.module.recover_thread_resume_candidates(
                codex_home=windows_codex,
                affected_thread_ids=["thread-1"],
                linux_roots=linux_roots,
                root_map=root_map,
                allowed_unc_hosts=("wsl.localhost", "wsl$"),
                stale_markers=("/mnt/c/users", "/workspace"),
                default_root_name="management",
            )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["workspace_root_name"], "reservation-system")
        self.assertEqual(candidate["workspace_root"], str(reservation_root))
        self.assertTrue(candidate["resume_position"])
        self.assertIn("운영 환경 재검증", candidate["remaining_work_briefing"])

    def test_repair_global_state_prunes_projectless_refs_and_prefers_latest_resume_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_codex = tmp / "linux" / ".codex"
            windows_codex = tmp / "windows" / ".codex"
            management_root = tmp / "Dev-Management"
            product_root = tmp / "Dev-Product"
            reservation_root = product_root / "reservation-system"
            management_root.mkdir(parents=True)
            reservation_root.mkdir(parents=True)
            self.module.resolve_codex_home = lambda: linux_codex

            authority = {
                "canonical_roots": {
                    "management": str(management_root),
                    "product": str(product_root),
                    "reservation-system": str(reservation_root),
                },
                "generation_targets": {
                    "global_runtime": {
                        "linux": {"agents": str(linux_codex / "AGENTS.md"), "config": str(linux_codex / "config.toml")},
                        "windows_mirror": {"agents": str(windows_codex / "AGENTS.md"), "config": str(windows_codex / "config.toml")},
                    },
                    "global_config": {"model_reasoning_effort": "high"},
                },
                "runtime_layering": {
                    "restore_seed_policy": {
                        "preferred_windows_access_host": "wsl.localhost",
                        "allowed_windows_access_hosts": ["wsl.localhost", "wsl$"],
                        "default_active_workspace_root": "management",
                        "open_target_global": "wsl",
                        "integrated_terminal_shell": "wsl",
                        "follow_up_queue_mode": "steer",
                        "conversation_detail_mode": "steps",
                    }
                },
            }
            policy = {
                "canonical_wsl": {"preferred_windows_access_host": "wsl.localhost", "windows_access_hosts": ["wsl.localhost", "wsl$"]},
                "legacy_mount": {"blocked_prefixes": []},
                "stale_workspace_markers": ["windows-user-mount"],
            }
            (linux_codex / "config.toml").parent.mkdir(parents=True, exist_ok=True)
            (linux_codex / "config.toml").write_text('model_reasoning_effort = "high"\n', encoding="utf-8")
            _write_json(
                linux_codex / "state" / "workspace-authority" / "reservation-system.json",
                {"workspace_root": str(reservation_root)},
            )
            _write_json(
                windows_codex / ".codex-global-state.json",
                {
                    "projectless-thread-ids": ["thread-1"],
                    "thread-workspace-root-hints": {"thread-1": "/mnt/c/Users/anise/Documents/Codex"},
                    "active-workspace-roots": [],
                    "electron-saved-workspace-roots": [],
                    "project-order": [],
                },
            )

            preferred_root = self.module.to_unc_path(reservation_root, "wsl.localhost")
            result = self.module.repair_global_state(authority, policy, windows_codex, preferred_active_root=preferred_root)
            repaired = self.module.load_json(windows_codex / ".codex-global-state.json", default={})

        self.assertTrue(result["changed"])
        self.assertEqual(repaired["projectless-thread-ids"], [])
        self.assertEqual(repaired["thread-workspace-root-hints"], {})
        self.assertEqual(repaired["active-workspace-roots"][0], preferred_root)
        self.assertEqual(repaired["project-order"][0], preferred_root)

    def test_repair_sessions_and_threads_db_use_recovered_thread_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            windows_codex = tmp / "windows" / ".codex"
            management_root = tmp / "Dev-Management"
            reservation_root = tmp / "Dev-Product" / "reservation-system"
            management_root.mkdir(parents=True)
            reservation_root.mkdir(parents=True)

            session_path = windows_codex / "sessions" / "2026" / "04" / "17" / "rollout-thread-1.jsonl"
            _write_jsonl(
                session_path,
                [
                    {"type": "session_meta", "payload": {"id": "thread-1", "cwd": str(management_root), "reasoning_effort": "xhigh"}},
                    {"type": "turn_context", "payload": {"cwd": str(management_root), "reasoning_effort": "xhigh"}},
                ],
            )

            db_path = windows_codex / "state_5.sqlite"
            _create_threads_db(db_path)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    INSERT INTO threads (id, title, cwd, first_user_message, updated_at, updated_at_ms, archived, reasoning_effort)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("thread-1", "resume", str(management_root), "", 1, 1, 0, "xhigh"),
                )
                conn.commit()
            finally:
                conn.close()

            changed = self.module.repair_sessions(
                codex_home=windows_codex,
                affected_thread_ids=["thread-1"],
                recovered_thread_roots={"thread-1": str(reservation_root)},
                default_linux_root=str(management_root),
                default_effort="high",
                stale_markers=("/mnt/c/users",),
            )
            threads_result = self.module.repair_threads_db(
                db_path=db_path,
                affected_thread_ids=["thread-1"],
                recovered_thread_roots={"thread-1": str(reservation_root)},
                default_linux_root=str(management_root),
                default_effort="high",
                reservation_root=str(reservation_root),
                legacy_linux_roots=(),
            )

            repaired_session = session_path.read_text(encoding="utf-8")
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute("SELECT cwd, reasoning_effort FROM threads WHERE id = 'thread-1'").fetchone()
            finally:
                conn.close()

        self.assertEqual(changed, [str(session_path)])
        self.assertIn(str(reservation_root), repaired_session)
        self.assertEqual(threads_result["changed_rows"], 1)
        self.assertEqual(row[0], str(reservation_root))
        self.assertEqual(row[1], "high")

    def test_help_no_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            state_path = fixture["windows_codex"] / ".codex-global-state.json"
            before = state_path.read_text(encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["repair_codex_desktop_runtime.py", "--help"]
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as exc:
                        self.module.main()
            finally:
                sys.argv = argv
            after = state_path.read_text(encoding="utf-8")
            help_output = stdout.getvalue()
            help_exit = exc.exception.code

        self.assertEqual(help_exit, 0)
        self.assertEqual(after, before)
        self.assertIn("Safely repair Codex desktop runtime restore state.", help_output)

    def test_default_is_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            state_path = fixture["windows_codex"] / ".codex-global-state.json"
            before = state_path.read_text(encoding="utf-8")

            exit_code, _output = self._run_main(["--runtime-codex-home", str(fixture["windows_codex"])])
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))
            after = state_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(after, before)
        self.assertEqual(report["mode"], "dry-run")
        self.assertTrue(report["predicted_changes"])
        self.assertEqual(report["applied_changes"], [])

    def test_dry_run_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            session_path = fixture["windows_codex"] / "sessions" / "2026" / "04" / "17" / "rollout-thread-1.jsonl"
            before = session_path.read_text(encoding="utf-8")

            exit_code, _output = self._run_main(["--dry-run", "--runtime-codex-home", str(fixture["windows_codex"])])
            after = session_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertEqual(after, before)

    def test_apply_required_for_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            state_path = fixture["windows_codex"] / ".codex-global-state.json"

            exit_code, _output = self._run_main(["--runtime-codex-home", str(fixture["windows_codex"])])
            repaired = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(repaired["projectless-thread-ids"], ["thread-1"])

    def test_apply_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            state_path = fixture["windows_codex"] / ".codex-global-state.json"

            exit_code, _output = self._run_main(["--apply", "--tests-status", "PASS", "--runtime-codex-home", str(fixture["windows_codex"])])
            repaired = json.loads(state_path.read_text(encoding="utf-8"))
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(repaired["projectless-thread-ids"], [])
        self.assertEqual(report["mode"], "apply")
        self.assertTrue(report["applied_changes"])
        self.assertTrue(report["backup"]["created"])

    def test_apply_repairs_linux_launcher_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)

            exit_code, _output = self._run_main(["--apply", "--tests-status", "PASS", "--runtime-codex-home", str(fixture["windows_codex"])])
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))
            launcher_text = fixture["linux_launcher"].read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn('host_alias="devmgmt-wsl"', launcher_text)
        self.assertEqual(report["launcher_shim"]["status"], "PASS")
        self.assertTrue(any(item["type"] == "linux_codex_launcher_shim_rewrite" for item in report["applied_changes"]))

    def test_runtime_codex_home_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)
            unrelated = Path(tmpdir) / "other" / ".codex"
            self.module.resolve_codex_home = lambda: unrelated

            exit_code, _output = self._run_main(["--runtime-codex-home", str(fixture["windows_codex"])])
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["runtime_codex_home"], str(fixture["windows_codex"]))

    def test_report_contains_mode_predicted_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            self._seed_runtime_drift(fixture)

            exit_code, _output = self._run_main(["--dry-run", "--runtime-codex-home", str(fixture["windows_codex"])])
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["mode"], "dry-run")
        self.assertIn("baseline", report)
        self.assertIn("predicted_changes", report)
        self.assertIn("applied_changes", report)

    def test_no_unexpected_resume_root_rewrite_after_green_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = self._configure_runtime_fixture(Path(tmpdir))
            _write_json(
                fixture["windows_codex"] / ".codex-global-state.json",
                {
                    "projectless-thread-ids": [],
                    "thread-workspace-root-hints": {},
                    "active-workspace-roots": [],
                    "electron-saved-workspace-roots": [],
                    "project-order": [],
                },
            )

            exit_code, _output = self._run_main(["--runtime-codex-home", str(fixture["windows_codex"])])
            report = json.loads(fixture["report_path"].read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(report["unexpected_resume_root_rewrites"], [])
        self.assertEqual(report["baseline"]["windows_runtime_mirror_check_status"], "PASS")
        self.assertEqual(report["baseline"]["wsl_launcher_check_status"], "PASS")
        self.assertEqual(report["baseline"]["runtime_restore_seed_violations_count"], 0)


if __name__ == "__main__":
    unittest.main()
