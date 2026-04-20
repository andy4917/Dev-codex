from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "repair_serena_startup.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("repair_serena_startup", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load repair_serena_startup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepairSerenaStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_missing_serena_cli_is_report_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            self.module, "cli_probe", return_value={"available": False, "binary": "", "project_index_available": False}
        ), patch.object(
            self.module, "evaluate_startup_workflow", return_value={"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        ):
            report = self.module.repair_serena(apply_serena=False, repo_root=Path(tmpdir))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["actions_applied"])

    def test_missing_metadata_without_deterministic_cli_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            self.module, "cli_probe", return_value={"available": True, "binary": "/usr/bin/serena", "project_index_available": False}
        ), patch.object(
            self.module, "evaluate_startup_workflow", return_value={"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        ):
            repo_root = Path(tmpdir)
            report = self.module.repair_serena(apply_serena=False, repo_root=repo_root)
        self.assertFalse((repo_root / ".serena" / "project.yml").exists())
        self.assertFalse(report["actions_applied"])

    def test_deterministic_cli_proposes_index_repair(self) -> None:
        before = {"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        after = {"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            self.module, "cli_probe", return_value={"available": True, "binary": "/usr/bin/serena", "project_index_available": True}
        ), patch.object(
            self.module, "evaluate_startup_workflow", side_effect=[before, after]
        ):
            report = self.module.repair_serena(apply_serena=False, repo_root=Path(tmpdir))
        self.assertTrue(report["actions_planned"])
        self.assertFalse(report["actions_applied"])

    def test_apply_uses_serena_cli_without_forging_files(self) -> None:
        before = {"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        after = {"status": "BLOCKED", "serena": {"activation": {"status": "BLOCKED"}, "runtime": {"linux": {"onboarding_performed": False}}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            project_yml = repo_root / ".serena" / "project.yml"

            def fake_run(argv, cwd=None):
                if argv[:3] == ["serena", "project", "index"]:
                    project_yml.parent.mkdir(parents=True, exist_ok=True)
                    project_yml.write_text("project_name: demo\n", encoding="utf-8")
                    return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "argv": argv}
                return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "unexpected", "argv": argv}

            with patch.object(self.module, "cli_probe", return_value={"available": True, "binary": "/usr/bin/serena", "project_index_available": True}), patch.object(
                self.module, "evaluate_startup_workflow", side_effect=[before, after]
            ), patch.object(self.module, "run", side_effect=fake_run):
                report = self.module.repair_serena(apply_serena=True, repo_root=repo_root)
        self.assertEqual(report["actions_applied"], ["serena project index"])
        self.assertEqual(report["project_yml_path"], str(project_yml))
        self.assertFalse(report["repair_boundary"]["arbitrary_serena_file_forging_allowed"])


if __name__ == "__main__":
    unittest.main()
