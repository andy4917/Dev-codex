from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_app_local_readiness.py"


def _toml_key_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\")


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_app_local_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_app_local_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsAppLocalReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_app_ready_when_config_and_local_projects_are_windows_native(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            codex_home = tmp / ".codex"
            devmgmt = tmp / "code" / "Dev-Management"
            workflow = tmp / "code" / "Dev-Workflow"
            product = tmp / "code" / "Dev-Product"
            for path in (codex_home, devmgmt, workflow, product):
                path.mkdir(parents=True, exist_ok=True)
            (codex_home / "config.toml").write_text(
                f'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "high"\n[windows]\nsandbox = "elevated"\n[projects."{_toml_key_path(devmgmt)}"]\ntrust_level = "trusted"\n[projects."{_toml_key_path(workflow)}"]\ntrust_level = "trusted"\n[projects."{_toml_key_path(product)}"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )
            policy = {
                "canonical_roots": {
                    "dev_management": str(devmgmt),
                    "dev_workflow": str(workflow),
                    "dev_product": str(product),
                },
                "runtime_paths": {"windows_codex_home": str(codex_home)},
            }
            with patch.object(self.module, "PATH_POLICY", policy), patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home), patch.object(self.module, "WINDOWS_APP_CONFIG", codex_home / "config.toml"), patch.object(self.module.shutil, "which", return_value="tool"):
                report = self.module.evaluate_windows_app_local_readiness(devmgmt)
        self.assertEqual(report["status"], "APP_READY")

    def test_legacy_project_reference_blocks_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            codex_home = tmp / ".codex"
            devmgmt = tmp / "code" / "Dev-Management"
            workflow = tmp / "code" / "Dev-Workflow"
            product = tmp / "code" / "Dev-Product"
            for path in (codex_home, devmgmt, workflow, product):
                path.mkdir(parents=True, exist_ok=True)
            (codex_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "low"\n[windows]\nsandbox = "elevated"\n[projects."legacy-remote://Dev-Management"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )
            policy = {
                "canonical_roots": {
                    "dev_management": str(devmgmt),
                    "dev_workflow": str(workflow),
                    "dev_product": str(product),
                },
                "runtime_paths": {"windows_codex_home": str(codex_home)},
            }
            with patch.object(self.module, "PATH_POLICY", policy), patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home), patch.object(self.module, "WINDOWS_APP_CONFIG", codex_home / "config.toml"), patch.object(self.module.shutil, "which", return_value="tool"):
                report = self.module.evaluate_windows_app_local_readiness(devmgmt)
        self.assertEqual(report["status"], "APP_NOT_READY")
        self.assertIn("legacy Linux/remote project references", " ".join(report["blocking_reasons"]))


if __name__ == "__main__":
    unittest.main()
