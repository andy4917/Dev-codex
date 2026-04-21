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
            "windows_app_state": {"codex_home": str(tmp / "windows-home" / ".codex")},
            "generation_targets": {
                "global_runtime": {
                    "linux": {"hooks_config": str(tmp / "linux-hooks.json")},
                },
                "scorecard": {
                    "runtime_hook": {
                        "script": "/home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py",
                        "linux_command_prefix": "python3",
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
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["trigger_only"])
        self.assertFalse(report["windows_generation_enabled"])

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

    def test_windows_policy_hooks_present_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                windows_hooks = tmp / "windows-home" / ".codex" / "hooks.json"
                windows_hooks.parent.mkdir(parents=True, exist_ok=True)
                windows_hooks.write_text('{"hooks": {}}\n', encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["windows_policy_hooks"]["present"])

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
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["hook_only_enforcement_claim"])

    def test_windows_generation_reports_disabled_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = self._authority(tmp)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, authority)
            with patch.object(self.module, "AUTHORITY_PATH", authority_path):
                (tmp / "linux-hooks.json").write_text(self.module.render_hooks(authority, windows=False), encoding="utf-8")
                report = self.module.evaluate_hook_readiness(tmp / "repo")
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["windows_generation_enabled"])


if __name__ == "__main__":
    unittest.main()
