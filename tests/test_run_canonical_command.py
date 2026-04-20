from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_canonical_command.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("run_canonical_command", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load run_canonical_command.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunCanonicalCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_build_remote_command_quotes_args(self) -> None:
        command = self.module.build_remote_command("/home/andy4917/Dev-Management", ["python3", "-c", "print('a b')"])
        self.assertIn("cd /home/andy4917/Dev-Management", command)
        self.assertIn("python3 -c", command)
        self.assertIn("a b", command)
        self.assertIn("exec python3 -c", command)

    def test_ssh_unavailable_returns_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value={"canonical_execution_status": "BLOCKED"}), patch.object(
            self.module.subprocess, "run"
        ) as run:
            with patch.object(sys, "argv", ["run_canonical_command.py", "--", "pwd"]):
                exit_code = self.module.main()
        self.assertEqual(exit_code, 2)
        run.assert_not_called()

    def test_command_is_routed_through_canonical_host(self) -> None:
        runtime = {
            "canonical_execution_status": "PASS",
            "canonical_execution_surface": {"host_alias": "devmgmt-wsl", "repo_root": "/home/andy4917/Dev-Management"},
        }
        with patch.object(self.module, "evaluate_global_runtime", return_value=runtime), patch.object(
            self.module.subprocess, "run"
        ) as run:
            run.return_value.returncode = 0
            with patch.object(sys, "argv", ["run_canonical_command.py", "--", "pwd"]):
                exit_code = self.module.main()
        self.assertEqual(exit_code, 0)
        argv = run.call_args[0][0]
        self.assertEqual(argv[0], "ssh")
        self.assertIn("devmgmt-wsl", argv)


if __name__ == "__main__":
    unittest.main()
