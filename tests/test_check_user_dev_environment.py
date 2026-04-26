from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devmgmt_runtime.scorecard_hook import render_hooks_json
from devmgmt_runtime.windows_policy import approved_global_agents_text


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
                "repair_behavior": {
                    "dispose_backups_and_temporary_artifacts_to_recycle_bin": True,
                },
            },
        }

    def _path_policy(self, windows_home: Path) -> dict[str, object]:
        repo = windows_home.parent / "code" / "Dev-Management"
        return {
            "canonical_execution_host": "windows-native",
            "canonical_roots": {
                "dev_management": str(repo),
                "dev_workflow": str(windows_home.parent / "code" / "Dev-Workflow"),
                "dev_product": str(windows_home.parent / "code" / "Dev-Product"),
            },
            "runtime_paths": {
                "windows_codex_home": str(windows_home),
            },
            "generation_targets": {
                "scorecard": {
                    "runtime_hook": {
                        "script": str(repo / "scripts" / "scorecard_runtime_hook.py"),
                        "user_prompt_throttle_seconds": 0,
                        "events": {"UserPromptSubmit": {"matcher": ".*"}},
                        "windows_command_prefix": "python",
                    }
                }
            },
        }

    def _write_ready_config(self, windows_home: Path, path_policy: dict[str, object]) -> None:
        (windows_home / "config.toml").write_text(
            'sandbox_mode = "danger-full-access"\napproval_policy = "never"\nmodel_reasoning_effort = "high"\n[features]\ncodex_hooks = true\napps = true\nplugins = true\ntool_search = true\ntool_suggest = true\ntool_call_mcp_elicitation = true\n[windows]\nsandbox = "elevated"\n',
            encoding="utf-8",
        )
        (windows_home / "hooks.json").write_text(render_hooks_json(path_policy), encoding="utf-8")

    def test_windows_full_access_config_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            path_policy = self._path_policy(windows_home)
            self._write_ready_config(windows_home, path_policy)
            report = self.module.inspect_windows_codex_boundary(self.user_policy, path_policy)
        self.assertEqual(report["status"], "PASS")

    def test_analytics_opt_out_is_safe_user_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            path_policy = self._path_policy(windows_home)
            self._write_ready_config(windows_home, path_policy)
            with (windows_home / "config.toml").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("\n[analytics]\nenabled = false\n")
            report = self.module.inspect_windows_codex_boundary(self.user_policy, path_policy)
        self.assertEqual(report["status"], "PASS")

    def test_recycle_bin_disposal_policy_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            path_policy = self._path_policy(windows_home)
            self._write_ready_config(windows_home, path_policy)
            policy = {
                "target_app_config": self.user_policy["target_app_config"],
                "windows_codex_boundary": {"required_local_project_roots": []},
            }
            report = self.module.inspect_windows_codex_boundary(policy, path_policy)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("Recycle Bin", " ".join(report["reasons"]))

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

    def test_noncanonical_global_agents_text_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n[windows]\nsandbox = "elevated"\n',
                encoding="utf-8",
            )
            (windows_home / "AGENTS.md").write_text("temporary global exception\n", encoding="utf-8")
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["surface_findings"]["agents"]["classification"], "noncanonical_global_instruction_surface")

    def test_approved_global_authority_capsule_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            path_policy = self._path_policy(windows_home)
            self._write_ready_config(windows_home, path_policy)
            (windows_home / "AGENTS.md").write_text(approved_global_agents_text(path_policy), encoding="utf-8")
            report = self.module.inspect_windows_codex_boundary(self.user_policy, path_policy)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["surface_findings"]["agents"]["classification"], "APP_GLOBAL_AUTHORITY_CAPSULE")

    def test_scorecard_hook_is_required_when_codex_hooks_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n[features]\ncodex_hooks = true\n',
                encoding="utf-8",
            )
            report = self.module.inspect_windows_codex_boundary(self.user_policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("approved scorecard", " ".join(report["reasons"]))

    def test_unsupported_workspace_dependencies_blocks_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_home = Path(tmpdir) / ".codex"
            windows_home.mkdir()
            (windows_home / "config.toml").write_text(
                'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n[features]\nworkspace_dependencies = true\n',
                encoding="utf-8",
            )
            policy = dict(self.user_policy)
            policy["windows_codex_boundary"] = {
                **self.user_policy["windows_codex_boundary"],
                "unsupported_feature_keys": ["workspace_dependencies"],
            }
            report = self.module.inspect_windows_codex_boundary(policy, self._path_policy(windows_home))
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("unsupported experimental features", " ".join(report["reasons"]))

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

    def test_scratch_surface_requires_external_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            external = tmp / ".scratch" / "Dev-Management"
            external.mkdir(parents=True)
            with patch.object(self.module, "DEV_MANAGEMENT_SCRATCH", external):
                report = self.module.inspect_scratch_surface()
            self.assertEqual(report["status"], "PASS")
            with patch.object(self.module, "DEV_MANAGEMENT_SCRATCH", tmp / ".scratch" / "missing"):
                blocked = self.module.inspect_scratch_surface()
            self.assertEqual(blocked["status"], "BLOCKED")

    def test_execution_route_accepts_only_windows_native_label(self) -> None:
        self.assertEqual(self.module.inspect_execution_route({"mode_selected": "windows-native"})["status"], "PASS")
        self.assertEqual(self.module.inspect_execution_route({"mode_selected": "local-windows"})["status"], "BLOCKED")
        self.assertIn("expected canonical execution label windows-native", " ".join(self.module.inspect_execution_route({"mode_selected": "local"})["reasons"]))
        self.assertEqual(self.module.inspect_execution_route({"mode_selected": "ssh-managed"})["status"], "BLOCKED")

    def test_toolchain_blocks_missing_required_tool(self) -> None:
        with patch.object(self.module.shutil, "which", return_value=None):
            report = self.module.inspect_toolchain()
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["tools"]["git"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
