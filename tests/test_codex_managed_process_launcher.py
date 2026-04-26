from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "codex_managed_process_launcher.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("codex_managed_process_launcher", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load codex_managed_process_launcher.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexManagedProcessLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.profile = self.module.ManagedProfile(
            name="test-helper",
            signature="managed-helper --serve",
            process_names=frozenset({"python.exe", "node.exe", "uvx.exe"}),
            command=("python", "-c", "print('ok')"),
            orphan_markers=("orphan-language-server",),
            env_defaults={"PYTHONUTF8": "1"},
            lock_path=Path("unused.lock"),
        )

    def row(self, pid: int, parent: int, name: str, command: str):
        return self.module.ProcessRow(pid=pid, parent_pid=parent, name=name, command_line=command)

    def test_cleanup_roots_selects_only_top_level_profile_roots(self) -> None:
        rows = [
            self.row(10, 1, "uvx.exe", "uvx managed-helper --serve"),
            self.row(11, 10, "python.exe", "python managed-helper --serve"),
            self.row(12, 11, "node.exe", "node orphan-language-server"),
            self.row(20, 1, "node.exe", "node orphan-language-server"),
            self.row(30, 1, "python.exe", "python unrelated.py"),
        ]

        roots = self.module.cleanup_roots(rows, self.profile, current_pid=999)

        self.assertEqual(roots, [10, 20])

    def test_cleanup_roots_excludes_current_wrapper_pid(self) -> None:
        rows = [
            self.row(10, 1, "python.exe", "python launcher.py managed-helper --serve"),
            self.row(11, 10, "python.exe", "python managed-helper --serve"),
        ]

        roots = self.module.cleanup_roots(rows, self.profile, current_pid=10)

        self.assertEqual(roots, [11])

    def test_active_lock_exits_duplicate_launcher_without_starting_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "helper.lock"
            lock_path.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
            with (
                mock.patch.object(self.module, "process_exists", return_value=True),
                mock.patch.object(self.module, "cleanup_existing_profile_roots") as cleanup,
                mock.patch.object(self.module.subprocess, "Popen") as popen,
            ):
                result = self.module.run_profile(self.profile, lock_path=lock_path)

        self.assertEqual(result, 0)
        cleanup.assert_not_called()
        popen.assert_not_called()

    def test_stale_lock_is_replaced_and_removed_after_child_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "helper.lock"
            lock_path.write_text(json.dumps({"pid": 4242}), encoding="utf-8")
            fake_process = mock.Mock()
            fake_process.pid = 100
            fake_process.wait.return_value = 7
            fake_process.poll.return_value = 7
            with (
                mock.patch.object(self.module, "process_exists", return_value=False),
                mock.patch.object(self.module, "cleanup_existing_profile_roots", return_value=[]),
                mock.patch.object(self.module.subprocess, "Popen", return_value=fake_process) as popen,
            ):
                result = self.module.run_profile(self.profile, lock_path=lock_path)

            self.assertEqual(result, 7)
            self.assertFalse(lock_path.exists())
            popen.assert_called_once()

    def test_live_child_tree_is_stopped_when_wait_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "helper.lock"
            fake_process = mock.Mock()
            fake_process.pid = 100
            fake_process.wait.side_effect = KeyboardInterrupt()
            fake_process.poll.return_value = None
            with (
                mock.patch.object(self.module, "cleanup_existing_profile_roots", return_value=[]),
                mock.patch.object(self.module.subprocess, "Popen", return_value=fake_process),
                mock.patch.object(self.module, "stop_process_tree") as stop_tree,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    self.module.run_profile(self.profile, lock_path=lock_path)

            stop_tree.assert_called_once_with(100)
            self.assertFalse(lock_path.exists())

    def test_serena_profile_covers_python_node_uvx_and_orphan_markers(self) -> None:
        profile = self.module.build_serena_profile()

        self.assertIn("uvx.exe", profile.process_names)
        self.assertIn("node.exe", profile.process_names)
        self.assertIn("python3.14.exe", profile.process_names)
        self.assertIn("TypeScriptLanguageServer", profile.orphan_markers)
        self.assertIn("start-mcp-server --project-from-cwd --context=codex", profile.signature)


if __name__ == "__main__":
    unittest.main()
