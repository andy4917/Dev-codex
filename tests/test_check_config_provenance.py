from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devmgmt_runtime.scorecard_hook import render_hooks_json


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_config_provenance.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_config_provenance", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_config_provenance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckConfigProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _build_repo(self, tmp: Path) -> tuple[Path, Path]:
        repo = tmp / "Dev-Management"
        codex_home = tmp / ".codex"
        codex_home.mkdir(parents=True)
        (repo / "contracts").mkdir(parents=True)
        authority = {
            "authority_root": str(repo),
            "canonical_execution_host": "windows-native",
            "canonical_roots": {"management": str(repo), "workflow": str(tmp / "Dev-Workflow"), "product": str(tmp / "Dev-Product")},
            "canonical_execution_surface": {"id": "windows-native", "expected_os": "windows", "repo_root": str(repo)},
            "windows_app_state": {"codex_home": str(codex_home)},
            "generation_targets": {
                "global_runtime": {"windows": {"config": str(codex_home / "config.toml"), "agents": str(codex_home / "AGENTS.md")}},
                "scorecard": {
                    "runtime_hook": {
                        "script": str(repo / "scripts" / "scorecard_runtime_hook.py"),
                        "user_prompt_throttle_seconds": 0,
                        "events": {"UserPromptSubmit": {"matcher": ".*"}},
                        "windows_command_prefix": "python",
                    }
                },
            },
            "hardcoding_definition": {"feature_rules": {"forbidden_feature_flags": ["telepathy"]}},
        }
        path_policy = {
            "schema_version": "2026.04.path-authority.windows-native.v1",
            "canonical_execution_host": "windows-native",
            "canonical_roots": {"dev_management": str(repo), "dev_workflow": str(tmp / "Dev-Workflow"), "dev_product": str(tmp / "Dev-Product")},
            "runtime_paths": {"codex_cli_bin": str(tmp / "codex.exe"), "codex_user_home": str(codex_home), "windows_codex_home": str(codex_home)},
            "allowed_env_vars": [],
            "forbidden_primary_paths": ["legacy-linux-path", "mounted-linux-launcher", "legacy-remote-route"],
            "windows_surfaces": {"codex_home": "app_control_plane", "policy_config": "app_control_plane_allowed", "agents": "global_custom_instructions_allowed", "hooks": "forbidden_without_explicit_policy", "skills": "app_owned_or_user_approved_allowed"},
        }
        policy = {
            "schema_version": "2026.04.config-provenance.windows-native.v1",
            "optional_user_override_source": str(codex_home / "user-config.toml"),
            "blocked_active_feature_flags": ["telepathy", "workspace_dependencies"],
            "blocked_generated_config_values": {"approval_policy": [], "sandbox_mode": []},
            "generated_mirror_contract": {"steady_state": "decommissioned"},
        }
        self._write_json(repo / "contracts" / "workspace_authority.json", authority)
        self._write_json(repo / "contracts" / "path_authority_policy.json", path_policy)
        self._write_json(repo / "contracts" / "config_provenance_policy.json", policy)
        return repo, codex_home

    def test_windows_app_control_plane_config_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, codex_home = self._build_repo(Path(tmpdir))
            authority = json.loads((repo / "contracts" / "workspace_authority.json").read_text(encoding="utf-8"))
            (codex_home / "config.toml").write_text(
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n[features]\napps = true\nplugins = true\ntool_search = true\ncodex_hooks = true\n',
                encoding="utf-8",
            )
            (codex_home / "hooks.json").write_text(render_hooks_json(authority), encoding="utf-8")
            with patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home):
                report = self.module.evaluate_config_provenance(repo)
        self.assertEqual(report["gate_status"], "PASS")
        self.assertEqual(report["status"], "PASS")

    def test_forbidden_feature_blocks_windows_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, codex_home = self._build_repo(Path(tmpdir))
            (codex_home / "config.toml").write_text('approval_policy = "never"\n[features]\ntelepathy = true\n', encoding="utf-8")
            with patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home):
                report = self.module.evaluate_config_provenance(repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("active telepathy flag detected", " ".join(report["blocked_reasons"]))

    def test_unsupported_workspace_dependencies_blocks_windows_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, codex_home = self._build_repo(Path(tmpdir))
            (codex_home / "config.toml").write_text(
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n[features]\nworkspace_dependencies = true\n',
                encoding="utf-8",
            )
            with patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home):
                report = self.module.evaluate_config_provenance(repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("workspace_dependencies", " ".join(report["blocked_reasons"]))

    def test_windows_hooks_block_even_when_marketplace_shaped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, codex_home = self._build_repo(Path(tmpdir))
            (codex_home / "config.toml").write_text(
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n',
                encoding="utf-8",
            )
            self._write_json(
                codex_home / "hooks.json",
                {"hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "python hook.py"}]}]}},
            )
            with patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home):
                report = self.module.evaluate_config_provenance(repo)
        self.assertEqual(report["status"], "BLOCKED")
        hook_findings = [
            item
            for item in report["windows_policy_surface_findings"]
            if str(item.get("path", "")).endswith("hooks.json")
        ]
        self.assertEqual(hook_findings[0]["classification"], "policy_bearing_hook_surface")
        self.assertEqual(hook_findings[0]["operation"], "remove")

    def test_codex_hooks_feature_flag_is_allowed_for_scorecard_hook_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, codex_home = self._build_repo(Path(tmpdir))
            authority = json.loads((repo / "contracts" / "workspace_authority.json").read_text(encoding="utf-8"))
            (codex_home / "config.toml").write_text(
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n[features]\ncodex_hooks = true\n',
                encoding="utf-8",
            )
            (codex_home / "hooks.json").write_text(render_hooks_json(authority), encoding="utf-8")
            with patch.object(self.module, "WINDOWS_CODEX_HOME", codex_home):
                report = self.module.evaluate_config_provenance(repo)
        self.assertEqual(report["status"], "PASS")
        hook_findings = [
            item
            for item in report["windows_policy_surface_findings"]
            if str(item.get("path", "")).endswith("hooks.json")
        ]
        self.assertEqual(hook_findings[0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
