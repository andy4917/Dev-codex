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
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]) as powershell:
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    apply_user_level=True,
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                    app_host_listed_in_connections=True,
                    app_remote_project_opened=True,
                    app_remote_project_path=str(tmp / "repo"),
                )
                updated = config.read_text(encoding="utf-8")
                cache_exists = cache_path.exists()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "live_probe")
        self.assertEqual(report["cache_status"], "fresh")
        self.assertTrue(cache_exists)
        self.assertEqual(powershell.call_count, 3)
        self.assertIn("Host wsl-ubuntu", updated)
        self.assertIn("Host devmgmt-wsl", updated)
        self.assertTrue(report["host_alias_defined_directly_in_windows_config"])

    def test_explicit_refresh_defaults_to_warn_until_app_listing_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            app_config = tmp / "windows-home" / ".codex" / "config.toml"
            app_agents = tmp / "windows-home" / ".codex" / "AGENTS.md"
            app_config.parent.mkdir(parents=True)
            app_config.write_text("[features]\nremote_control = true\nremote_connections = true\n", encoding="utf-8")
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "WINDOWS_APP_CONFIG", app_config), patch.object(self.module, "WINDOWS_APP_AGENTS", app_agents), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                )
        self.assertEqual(report["status"], "WARN")
        self.assertIsNone(report["app_host_listed_in_connections"])
        self.assertEqual(report["app_connections_status"], "WARN")
        self.assertEqual(report["app_remote_project_status"], "UNOBSERVED")
        self.assertIn("Connections > Add host > devmgmt-wsl", report["simple_user_instruction"])

    def test_include_only_alias_is_blocked_even_when_windows_ssh_can_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Include ~/.ssh/config.d/*.conf\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                    app_host_listed_in_connections=True,
                    app_remote_project_opened=True,
                    app_remote_project_path=str(tmp / "repo"),
                )
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["host_alias_visible_to_codex_app_discovery"])
        self.assertIn("Include-only aliases", " ".join(report["blocking_reasons"]))

    def test_manual_add_host_success_yields_warn_when_app_does_not_auto_list_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                    app_host_listed_in_connections=False,
                    manual_add_host_worked=True,
                    app_remote_project_opened=True,
                    app_remote_project_path=str(tmp / "repo"),
                )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["app_connections_status"], "WARN")
        self.assertIn("Add host > devmgmt-wsl worked", " ".join(report["warning_reasons"]))

    def test_manual_add_host_failure_blocks_when_app_does_not_auto_list_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                    app_host_listed_in_connections=False,
                    manual_add_host_worked=False,
                    app_remote_project_not_opened=True,
                    app_remote_project_path=str(tmp / "repo"),
                )
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["app_connections_status"], "BLOCKED")
        self.assertIn(report["blocking_domain"], {"app_discovery", "app_bootstrap"})
        self.assertIn("still cannot use devmgmt-wsl after Connections > Add host > devmgmt-wsl", " ".join(report["blocking_reasons"]))

    def test_cached_report_is_reused_without_live_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            app_config = tmp / "windows-home" / ".codex" / "config.toml"
            app_agents = tmp / "windows-home" / ".codex" / "AGENTS.md"
            app_config.parent.mkdir(parents=True)
            app_config.write_text("[features]\nremote_control = true\nremote_connections = true\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "WINDOWS_APP_CONFIG", app_config), patch.object(self.module, "WINDOWS_APP_AGENTS", app_agents):
                fingerprint = self.module.readiness_fingerprint("devmgmt-wsl")
                self._write_json(
                    cache_path,
                    {
                        "status": "PASS",
                        "host_alias": "devmgmt-wsl",
                        "windows_ssh_config": str(config),
                        "probe": {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""},
                        "host_alias_visible_to_codex_app_discovery": True,
                        "app_connections_status": "PASS",
                        "app_host_listed_in_connections": True,
                        "app_remote_project_status": "OPENED",
                        "app_remote_project_path": str(tmp / "repo"),
                        "readiness_fingerprint": fingerprint,
                        "warnings": [],
                        "user_action_required": [],
                    },
                )
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "WINDOWS_APP_CONFIG", app_config), patch.object(self.module, "WINDOWS_APP_AGENTS", app_agents), patch.object(self.module, "build_live_report") as live:
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    windows_ssh_readiness_report=cache_path,
                )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "cached_report")
        self.assertEqual(report["cache_status"], "fresh")
        self.assertEqual(report["cache_validation"]["status"], "PASS")
        live.assert_not_called()

    def test_cached_report_is_warned_when_fingerprint_mismatches_current_windows_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            app_config = tmp / "windows-home" / ".codex" / "config.toml"
            app_agents = tmp / "windows-home" / ".codex" / "AGENTS.md"
            app_config.parent.mkdir(parents=True)
            app_config.write_text("[features]\nremote_control = true\nremote_connections = true\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            self._write_json(
                cache_path,
                {
                    "status": "PASS",
                    "host_alias": "devmgmt-wsl",
                    "windows_ssh_config": str(config),
                    "probe": {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""},
                    "host_alias_visible_to_codex_app_discovery": True,
                    "app_connections_status": "PASS",
                    "app_host_listed_in_connections": True,
                    "app_remote_project_status": "OPENED",
                    "app_remote_project_path": str(tmp / "repo"),
                    "readiness_fingerprint": {
                        "host_alias": "devmgmt-wsl",
                        "windows_ssh_config": str(config),
                        "windows_ssh_config_sha256": "stale",
                        "concrete_top_level_host_aliases": ["devmgmt-wsl"],
                        "host_alias_visible_to_codex_app_discovery": True,
                        "identity_file": "~/.ssh/codex_wsl_ed25519",
                        "windows_app_config": str(app_config),
                        "windows_app_config_sha256": "stale",
                        "bootstrap_features_ready": True,
                        "remote_control_enabled": True,
                        "remote_connections_enabled": True,
                        "agents_is_inert_empty": False,
                    },
                    "warnings": [],
                    "user_action_required": [],
                },
            )
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "WINDOWS_APP_CONFIG", app_config), patch.object(self.module, "WINDOWS_APP_AGENTS", app_agents), patch.object(self.module, "build_live_report") as live:
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    windows_ssh_readiness_report=cache_path,
                )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["probe_source"], "cached_report")
        self.assertEqual(report["cache_validation"]["status"], "MISMATCH")
        self.assertIn("no longer matches the current Windows SSH/bootstrap state", " ".join(report["warnings"]))
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
                    "probe": {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""},
                    "host_alias_visible_to_codex_app_discovery": True,
                    "app_connections_status": "PASS",
                    "app_host_listed_in_connections": True,
                    "app_remote_project_status": "OPENED",
                    "app_remote_project_path": str(tmp / "repo"),
                    "warnings": [],
                    "user_action_required": [],
                },
            )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["probe_source"], "injected")
        self.assertEqual(report["cache_status"], "fresh")

    def test_manual_add_failure_is_classified_as_app_discovery_when_bootstrap_is_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority())
            config = tmp / "config"
            config.write_text("Host devmgmt-wsl\n  HostName localhost\n", encoding="utf-8")
            cache_path = tmp / "reports" / "windows.json"
            version = {"ok": True, "exit_code": 0, "stdout": "OpenSSH_for_Windows", "stderr": "", "command": ""}
            resolve = {"ok": True, "exit_code": 0, "stdout": "hostname localhost\nuser andy4917\nport 22\nidentityfile ~/.ssh/codex_wsl_ed25519\n", "stderr": "", "command": ""}
            probe = {"ok": True, "exit_code": 0, "stdout": "andy4917\n", "stderr": "", "command": ""}
            app_config = tmp / "windows-home" / ".codex" / "config.toml"
            app_agents = tmp / "windows-home" / ".codex" / "AGENTS.md"
            app_config.parent.mkdir(parents=True)
            app_config.write_text("[features]\nremote_control = true\nremote_connections = true\n", encoding="utf-8")
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module, "WINDOWS_APP_CONFIG", app_config), patch.object(self.module, "WINDOWS_APP_AGENTS", app_agents), patch.object(self.module, "run_powershell", side_effect=[version, resolve, probe]):
                report = self.module.evaluate_windows_app_ssh_readiness(
                    tmp / "repo",
                    refresh_windows_ssh=True,
                    windows_ssh_readiness_report=cache_path,
                    app_host_listed_in_connections=False,
                    manual_add_host_worked=False,
                    app_remote_project_not_opened=True,
                    app_remote_project_path=str(tmp / "repo"),
                )
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["blocking_domain"], "app_discovery")
        self.assertEqual(report["ssh_transport_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
