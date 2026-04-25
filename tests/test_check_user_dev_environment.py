from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_user_dev_environment.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_user_dev_environment", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_user_dev_environment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckUserDevEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.user_policy = {
            "target_app_config": {
                "approval_policy": "never",
                "sandbox_mode": "danger-full-access",
                "windows_sandbox": "elevated",
            },
            "windows_codex_boundary": {
                "required_local_project_roots": [],
            },
        }

    def _path_policy(self, windows_home: Path) -> dict[str, object]:
        return {
            "canonical_execution_host": "local-windows",
            "canonical_roots": {
                "dev_management": str(windows_home.parent / "code" / "Dev-Management"),
                "dev_workflow": str(windows_home.parent / "code" / "Dev-Workflow"),
                "dev_product": str(windows_home.parent / "code" / "Dev-Product"),
            },
            "runtime_paths": {
                "windows_codex_home": str(windows_home),
            },
        }

    def test_windows_full_access_config_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "high"\n[windows]\nsandbox = "elevated"\n',
                encoding="utf-8",
            )
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "PASS")

    def test_windows_hooks_are_blocked_even_when_marketplace_shaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "low"\n[windows]\nsandbox = "elevated"\n',
                encoding="utf-8",
            )
            (windows_home / "hooks.json").write_text(
                '{"hooks":{"PostToolUse":[{"matcher":"Edit","hooks":[{"type":"command","command":"python hook.py"}]}]}}\n',
                encoding="utf-8",
            )
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["surface_findings"]["hooks"]["classification"], "policy_bearing_hook_surface")
        self.assertIn("must be removed", report["surface_findings"]["hooks"]["reason"])

    def test_codex_hooks_feature_flag_blocks_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n[features]\ncodex_hooks = true\n',
                encoding="utf-8",
            )
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("codex_hooks", " ".join(report["reasons"]))

    def test_legacy_project_reference_blocks_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "medium"\n[windows]\nsandbox = "elevated"\n[projects."legacy-remote://Dev-Management"]\ntrust_level = "trusted"\n',
                encoding="utf-8",
            )
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("legacy Linux/remote project references", " ".join(report["reasons"]))

    def test_windows_repo_roots_pass_and_linux_roots_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "code" / "Dev-Management"
            root.mkdir(parents=True)
            report = self.module.inspect_repo_roots({"dev_management": root})
        self.assertEqual(report["status"], "PASS")
        blocked = self.module.inspect_repo_roots({"dev_management": Path("legacy-linux-path/Dev-Management")})
        self.assertEqual(blocked["status"], "BLOCKED")

    def test_docker_linux_bind_mount_warns(self) -> None:
        report = self.module.classify_docker_bind_sources(
            [{"Type": "bind", "Source": "legacy-linux://Dev-Management", "Destination": "/workspace"}]
        )
        self.assertEqual(report["status"], "WARN")

    def test_scratch_surface_requires_external_scratch_and_blocks_repo_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            external = tmp / ".scratch" / "Dev-Management"
            repo_scratch = tmp / "Dev-Management" / "codex-scripts"
            external.mkdir(parents=True)
            with patch.object(self.module, "DEV_MANAGEMENT_SCRATCH", external), patch.object(self.module, "REPO_SCRATCH", repo_scratch):
                report = self.module.inspect_scratch_surface()
            self.assertEqual(report["status"], "PASS")
            repo_scratch.mkdir(parents=True)
            with patch.object(self.module, "DEV_MANAGEMENT_SCRATCH", external), patch.object(self.module, "REPO_SCRATCH", repo_scratch):
                blocked = self.module.inspect_scratch_surface()
            self.assertEqual(blocked["status"], "BLOCKED")

    def test_ssh_decommission_requires_absence_without_reporting_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ssh_root = Path(tmpdir) / ".ssh"
            with patch.object(self.module, "USER_SSH_ROOT", ssh_root):
                report = self.module.inspect_ssh_decommission()
            self.assertEqual(report["status"], "PASS")
            ssh_root.mkdir()
            (ssh_root / "id_ed25519").write_text("secret", encoding="utf-8")
            with patch.object(self.module, "USER_SSH_ROOT", ssh_root):
                blocked = self.module.inspect_ssh_decommission()
            self.assertEqual(blocked["status"], "BLOCKED")
            self.assertNotIn("id_ed25519", str(blocked))

    def test_execution_route_accepts_local_windows(self) -> None:
        self.assertEqual(self.module.inspect_execution_route({"mode_selected": "local-windows"})["status"], "PASS")
        self.assertEqual(self.module.inspect_execution_route({"mode_selected": "ssh-managed"})["status"], "BLOCKED")

    def test_toolchain_blocks_missing_required_tool(self) -> None:
        with patch.object(self.module.shutil, "which", return_value=None):
            report = self.module.inspect_toolchain()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["tools"]["git"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
