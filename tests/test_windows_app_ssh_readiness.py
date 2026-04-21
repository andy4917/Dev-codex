from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_app_ssh_readiness.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_app_ssh_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_app_ssh_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsAppSshReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self) -> dict[str, object]:
        return {"canonical_remote_execution_surface": {"host_alias": "devmgmt-wsl"}}

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_windows_side_alias_missing_warns_with_refresh_guidance_when_cache_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            cache_path = tmp / "reports" / "windows.json"
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    windows_ssh_readiness_report=cache_path,
                )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["probe_source"], "cached_report")
        self.assertEqual(report["cache_status"], "missing")
        self.assertIn("devmgmt-wsl", report["simple_user_instruction"])

    def test_explicit_refresh_runs_live_probe_once_and_updates_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            ssh_dir = tmp / "ssh"
            ssh_dir.mkdir()
            config = ssh_dir / "config"
            config.write_text("Host wsl-ubuntu\n  HostName localhost\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "run_powershell", side_effect=[version, probe]) as powershell:
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    apply_user_level=True,
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                )
                updated = config.read_text(encoding="utf-8")
                cache_exists = cache_path.exists()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "live_probe")
        self.assertEqual(report["cache_status"], "fresh")
        self.assertTrue(cache_exists)
        self.assertEqual(powershell.call_count, 2)
        self.assertIn("Host wsl-ubuntu", updated)
        self.assertIn("Host devmgmt-wsl", updated)

    def test_cached_report_is_reused_without_live_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            cache_path = tmp / "reports" / "windows.json"
            self._write_json(
                cache_path,
                {
                    "status": "PASS",
                    "host_alias": "devmgmt-wsl",
                    "windows_ssh_config": str(config),
                    "warnings": [],
                    "user_action_required": [],
                },
            )
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "build_live_report") as live:
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    windows_ssh_readiness_report=cache_path,
                )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "cached_report")
        self.assertEqual(report["cache_status"], "fresh")
        live.assert_not_called()

    def test_injected_readiness_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report = self.module.evaluate_windows_app_ssh_readiness(
                tmp / "repo",
                injected_readiness={
                    "status": "PASS",
                    "host_alias": "devmgmt-wsl",
                    "windows_ssh_config": str(tmp / "config"),
                    "warnings": [],
                    "user_action_required": [],
                },
            )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "injected")
        self.assertEqual(report["cache_status"], "fresh")


if __name__ == "__main__":
    unittest.main()
