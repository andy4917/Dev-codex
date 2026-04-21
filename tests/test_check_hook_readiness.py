from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_hook_readiness.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_hook_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_hook_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckHookReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self, tmp: Path) -> dict[str, object]:
        return {
            "generation_targets": {
                "global_runtime": {
                    "linux": {"hooks_config": str(tmp / "linux-hooks.json")},
                    "windows_mirror": {"hooks_config": str(tmp / "windows-hooks.json")},
                },
                "scorecard": {
                    "runtime_hook": {
                        "script": "/home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py",
                        "linux_command_prefix": "python3",
                        "windows_command_prefix": "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File",
                        "windows_wrapper_path": str(tmp / "wrapper.ps1"),
                        "windows_wrapper_generated_header": "GENERATED - DO NOT EDIT",
                        "events": {"UserPromptSubmit": {"matcher": ".*"}},
                    }
                },
            }
        }

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_generated_hooks_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                (tmp / "windows-hooks.json").write_text(self.module.render_hooks(authority, windows=True), encoding="utf-8")
                (tmp / "wrapper.ps1").write_text(self.module.render_windows_hook_wrapper(authority), encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["trigger_only"])

    def test_hook_mismatch_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text("{}\n", encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "WARN")

    def test_missing_wrapper_path_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority["generation_targets"]["scorecard"]["runtime_hook"].pop("windows_wrapper_path")
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                (tmp / "windows-hooks.json").write_text(self.module.render_hooks(authority, windows=True), encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["windows_wrapper"]["configured"])

    def test_non_trigger_only_hook_role_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority["generation_targets"]["scorecard"]["runtime_hook"]["role"] = "enforcement"
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                (tmp / "windows-hooks.json").write_text(self.module.render_hooks(authority, windows=True), encoding="utf-8")
                (tmp / "wrapper.ps1").write_text(self.module.render_windows_hook_wrapper(authority), encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["hook_only_enforcement_claim"])

    def test_windows_hooks_can_be_intentionally_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority["generation_targets"]["scorecard"]["runtime_hook"]["windows_generation_enabled"] = False
            authority["generation_targets"]["scorecard"]["runtime_hook"]["windows_generation_reason"] = "disabled for terminal churn"
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "WARN")
        self.assertFalse(report["windows_generation_enabled"])


if __name__ == "__main__":
    unittest.main()
