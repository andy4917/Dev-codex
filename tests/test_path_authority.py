from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from devmgmt_runtime import path_authority


class PathAuthorityTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _build_repo(self, tmp: Path) -> tuple[Path, dict[str, object]]:
        repo = tmp / "Dev-Management"
        workflow = tmp / "Dev-Workflow"
        product = tmp / "Dev-Product"
        codex_home = tmp / ".codex"
        codex_bin = tmp / "Codex" / "codex.exe"
        for path in (repo, workflow, product, codex_home, codex_bin.parent):
            path.mkdir(parents=True, exist_ok=True)
        (repo / "contracts").mkdir()
        codex_bin.write_text("", encoding="utf-8")
        policy = {
            "schema_version": "2026.04.path-authority.windows-native.v1",
            "canonical_execution_host": "windows-native",
            "canonical_roots": {
                "dev_management": str(repo),
                "dev_workflow": str(workflow),
                "dev_product": str(product),
            },
            "runtime_paths": {
                "codex_cli_bin": str(codex_bin),
                "codex_user_home": str(codex_home),
                "windows_codex_home": str(codex_home),
            },
            "allowed_env_vars": ["DEVMGMT_ROOT", "DEV_WORKFLOW_ROOT", "DEV_PRODUCT_ROOT", "CANONICAL_EXECUTION_HOST", "CODEX_CLI_BIN", "CODEX_HOME"],
            "forbidden_primary_paths": ["legacy-linux-path", "mounted-linux-launcher", "legacy-remote-route"],
            "windows_surfaces": {
                "codex_home": "app_control_plane",
                "policy_config": "app_control_plane_allowed",
                "agents": "global_custom_instructions_allowed",
                "hooks": "forbidden_without_explicit_policy",
                "skills": "app_owned_or_user_approved_allowed",
            },
        }
        authority = {
            "canonical_roots": {
                "management": str(repo),
                "workflow": str(workflow),
                "product": str(product),
            },
            "forbidden_primary_runtime_paths": list(policy["forbidden_primary_paths"]),
            "canonical_execution_surface": {
                "host_alias": "windows-native",
                "repo_root": str(repo),
            },
            "canonical_remote_execution_surface": {
                "host_alias": "windows-native",
                "repo_root": str(repo),
            },
        }
        self._write_json(repo / "contracts" / "path_authority_policy.json", policy)
        self._write_json(repo / "contracts" / "workspace_authority.json", authority)
        return repo, policy

    def test_env_alignment_passes_for_windows_native_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, policy = self._build_repo(Path(tmpdir))
            loaded = path_authority.load_path_policy(repo)
            env = {
                "DEVMGMT_ROOT": str(repo),
                "DEV_WORKFLOW_ROOT": str(Path(policy["canonical_roots"]["dev_workflow"])),
                "DEV_PRODUCT_ROOT": str(Path(policy["canonical_roots"]["dev_product"])),
                "CANONICAL_EXECUTION_HOST": "windows-native",
                "CODEX_CLI_BIN": str(Path(policy["runtime_paths"]["codex_cli_bin"])),
                "CODEX_HOME": str(Path(policy["runtime_paths"]["windows_codex_home"])),
            }
            report = path_authority.validate_env_alignment(loaded, env=env)
        self.assertEqual(report["status"], "PASS")

    def test_env_alignment_blocks_conflicting_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, policy = self._build_repo(Path(tmpdir))
            loaded = path_authority.load_path_policy(repo)
            env = {
                "DEVMGMT_ROOT": str(repo.parent / "elsewhere"),
                "CANONICAL_EXECUTION_HOST": "windows-native",
                "CODEX_CLI_BIN": str(Path(policy["runtime_paths"]["codex_cli_bin"])),
            }
            report = path_authority.validate_env_alignment(loaded, env=env)
        self.assertEqual(report["status"], "BLOCKED")

    def test_resolve_under_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, _policy = self._build_repo(Path(tmpdir))
            loaded = path_authority.load_path_policy(repo)
            with self.assertRaises(ValueError):
                path_authority.resolve_under("dev_management", "..", "escape.txt", policy=loaded)

    def test_windows_codex_config_classifies_as_allowed_control_plane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, policy = self._build_repo(Path(tmpdir))
            loaded = path_authority.load_path_policy(repo)
            config = Path(policy["runtime_paths"]["windows_codex_home"]) / "config.toml"
            result = path_authority.classify_path(config, policy=loaded)
        self.assertEqual(result["classification"], "windows_policy_surface")
        self.assertEqual(result["surface_status"], "app_control_plane_allowed")

    def test_ssh_helpers_are_decommissioned(self) -> None:
        with self.assertRaises(RuntimeError):
            path_authority.windows_ssh_config_path({})
        with self.assertRaises(RuntimeError):
            path_authority.linux_ssh_config_path({})


if __name__ == "__main__":
    unittest.main()
