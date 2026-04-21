from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devmgmt_runtime import path_authority


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_MODULE_PATH = ROOT / "scripts" / "preflight_path_context.py"


def _load_preflight_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in __import__("sys").path:
        __import__("sys").path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("preflight_path_context", PREFLIGHT_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load preflight_path_context.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PathAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preflight = _load_preflight_module()

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _tempdir(self):
        return tempfile.TemporaryDirectory(dir="/tmp")

    def _build_repo(self, tmp: Path, *, create_env: bool = True) -> tuple[Path, Path]:
        repo = tmp / "Dev-Management"
        workflow = tmp / "Dev-Workflow"
        product = tmp / "Dev-Product"
        repo.mkdir()
        workflow.mkdir()
        product.mkdir()
        (repo / "contracts").mkdir()
        (repo / "scripts").mkdir()
        (repo / "devmgmt_runtime").mkdir()
        (repo / "reports").mkdir()
        (repo / "tests").mkdir()

        codex_bin = tmp / "codex-bin" / "codex"
        codex_bin.parent.mkdir(parents=True)
        codex_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        codex_bin.chmod(0o755)

        windows_home = tmp / "windows-home" / ".codex"
        user_home = tmp / "user-home" / ".codex"
        user_home.mkdir(parents=True)

        policy = {
            "schema_version": "2026.04.path-authority.v1",
            "canonical_execution_host": "devmgmt-wsl",
            "canonical_roots": {
                "dev_management": str(repo),
                "dev_workflow": str(workflow),
                "dev_product": str(product),
            },
            "legacy_root_aliases": {
                "management": "dev_management",
                "workflow": "dev_workflow",
                "product": "dev_product",
            },
            "runtime_paths": {
                "codex_cli_bin": str(codex_bin),
                "codex_user_home": str(user_home),
                "windows_codex_home": str(windows_home),
            },
            "allowed_env_vars": [
                "DEVMGMT_ROOT",
                "DEV_WORKFLOW_ROOT",
                "DEV_PRODUCT_ROOT",
                "CANONICAL_EXECUTION_HOST",
                "CODEX_CLI_BIN",
            ],
            "forbidden_primary_paths": [
                "/mnt/c/Users/anise/.codex/bin/wsl",
                "/mnt/c/Users/anise/.codex/tmp/arg0",
                "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            ],
            "windows_surfaces": {
                "ssh_config": "bootstrap_allowed",
                "codex_home": "app_state_only",
                "policy_config": "forbidden",
                "agents": "forbidden",
                "hooks": "forbidden",
                "skills": "forbidden",
            },
            "path_rules": {
                "canonical_root_literals_allowed_in": ["contracts/", "reports/", "tests/", ".env.example"],
                "targeted_docs_enforced": [],
                "scan_roots": ["scripts", "devmgmt_runtime"],
            },
            "compatibility": {
                "mode": "dual-read",
                "divergence_status": "BLOCKED",
                "removal_phase": "post-path-authority-cutover",
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
                "host_alias": "devmgmt-wsl",
                "repo_root": str(repo),
                "forbidden_primary_resolution": "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            },
            "canonical_remote_execution_surface": {
                "host_alias": "devmgmt-wsl",
                "repo_root": str(repo),
                "forbidden_primary_resolution": "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            },
            "windows_app_state": {
                "codex_home": str(windows_home),
            },
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "config": str(user_home / "config.toml"),
                        "agents": str(user_home / "AGENTS.md"),
                        "hooks_config": str(user_home / "hooks.json"),
                        "user_override_config": str(user_home / "user-config.toml"),
                    }
                }
            },
            "hardcoding_definition": {
                "path_rules": {
                    "legacy_repo_paths_to_remove": ["/legacy/runtime-root"],
                }
            },
        }
        self._write_json(repo / "contracts" / "path_authority_policy.json", policy)
        self._write_json(repo / "contracts" / "workspace_authority.json", authority)

        (repo / "scripts" / "ok.py").write_text("from pathlib import Path\n", encoding="utf-8")
        (repo / "devmgmt_runtime" / "__init__.py").write_text('"""ok"""\n', encoding="utf-8")
        (repo / ".envrc").write_text(
            "\n".join(
                [
                    "# Dev-Management direnv bootstrap.",
                    "# Source of truth is contracts/path_authority_policy.json, not this file.",
                    "",
                    "if [ -f .env ]; then",
                    "  dotenv .env",
                    "fi",
                    "",
                    "if [ -f .env.local ]; then",
                    "  dotenv .env.local",
                    "fi",
                    "",
                    'export DEVMGMT_ROOT="${DEVMGMT_ROOT:-$(pwd)}"',
                    'export PATH="$HOME/.local/share/dev-management/codex-npm/bin:$PATH"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (repo / ".env.example").write_text(
            "\n".join(
                [
                    f"DEVMGMT_ROOT={repo}",
                    f"DEV_WORKFLOW_ROOT={workflow}",
                    f"DEV_PRODUCT_ROOT={product}",
                    "CANONICAL_EXECUTION_HOST=devmgmt-wsl",
                    f"CODEX_CLI_BIN={codex_bin}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        if create_env:
            (repo / ".env").write_text(
                "\n".join(
                    [
                        f"DEVMGMT_ROOT={repo}",
                        f"DEV_WORKFLOW_ROOT={workflow}",
                        f"DEV_PRODUCT_ROOT={product}",
                        "CANONICAL_EXECUTION_HOST=devmgmt-wsl",
                        f"CODEX_CLI_BIN={codex_bin}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        subprocess.run(["git", "init"], cwd=repo, check=False, capture_output=True, text=True)
        return repo, codex_bin

    def test_env_alignment_pass_with_matching_values(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            policy = path_authority.load_path_policy(repo)
            env = {
                "DEVMGMT_ROOT": str(repo),
                "DEV_WORKFLOW_ROOT": str(repo.parent / "Dev-Workflow"),
                "DEV_PRODUCT_ROOT": str(repo.parent / "Dev-Product"),
                "CANONICAL_EXECUTION_HOST": "devmgmt-wsl",
                "CODEX_CLI_BIN": str(codex_bin),
            }
            report = path_authority.validate_env_alignment(policy, env=env)
        self.assertEqual(report["status"], "PASS")

    def test_env_alignment_blocks_conflicting_values(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            policy = path_authority.load_path_policy(repo)
            env = {
                "DEVMGMT_ROOT": str(repo.parent / "elsewhere"),
                "DEV_WORKFLOW_ROOT": str(repo.parent / "Dev-Workflow"),
                "DEV_PRODUCT_ROOT": str(repo.parent / "Dev-Product"),
                "CANONICAL_EXECUTION_HOST": "devmgmt-wsl",
                "CODEX_CLI_BIN": str(codex_bin),
            }
            report = path_authority.validate_env_alignment(policy, env=env)
        self.assertEqual(report["status"], "BLOCKED")

    def test_forbidden_windows_codex_path_is_blocked(self) -> None:
        with self._tempdir() as tmpdir:
            repo, _codex_bin = self._build_repo(Path(tmpdir))
            policy = path_authority.load_path_policy(repo)
            with self.assertRaises(ValueError):
                path_authority.assert_not_forbidden_path(Path("/mnt/c/Users/anise/.codex/bin/wsl/codex"), policy)

    def test_resolve_under_blocks_escape(self) -> None:
        with self._tempdir() as tmpdir:
            repo, _codex_bin = self._build_repo(Path(tmpdir))
            policy = path_authority.load_path_policy(repo)
            with self.assertRaises(ValueError):
                path_authority.resolve_under("dev_management", "..", "escape.txt", policy=policy)

    def test_helpers_return_path_objects(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            policy = path_authority.load_path_policy(repo)
        self.assertIsInstance(path_authority.get_devmgmt_root(policy), Path)
        self.assertEqual(path_authority.get_codex_cli_bin(policy), codex_bin)

    def test_preflight_blocks_hardcoded_source_literal(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            (repo / "scripts" / "bad.py").write_text(f'ROOT = "{repo}"\n', encoding="utf-8")
            with patch.object(self.preflight, "inspect_direnv", return_value={"status": "PASS", "available": True, "allowed": True, "reason": ""}), patch.object(
                self.preflight,
                "shell",
                return_value={"ok": True, "stdout": f"{codex_bin}\n", "stderr": ""},
            ):
                report = self.preflight.evaluate_path_context(repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["hardcoded_path_scan"]["status"], "BLOCKED")

    def test_preflight_allows_canonical_literals_in_allowlisted_reports(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            (repo / "reports" / "allowed.md").write_text(f"{repo}\n", encoding="utf-8")
            with patch.object(self.preflight, "inspect_direnv", return_value={"status": "PASS", "available": True, "allowed": True, "reason": ""}), patch.object(
                self.preflight,
                "shell",
                return_value={"ok": True, "stdout": f"{codex_bin}\n", "stderr": ""},
            ):
                report = self.preflight.evaluate_path_context(repo)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["hardcoded_path_scan"]["status"], "PASS")

    def test_preflight_blocks_tracked_env_local(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            (repo / ".env.local").write_text("DEVMGMT_ROOT=/tmp/local\n", encoding="utf-8")
            subprocess.run(["git", "add", ".env.local"], cwd=repo, check=False, capture_output=True, text=True)
            with patch.object(self.preflight, "inspect_direnv", return_value={"status": "PASS", "available": True, "allowed": True, "reason": ""}), patch.object(
                self.preflight,
                "shell",
                return_value={"ok": True, "stdout": f"{codex_bin}\n", "stderr": ""},
            ):
                report = self.preflight.evaluate_path_context(repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["env_files"]["status"], "BLOCKED")

    def test_preflight_warns_when_direnv_is_missing_but_helper_resolution_passes(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            with patch.object(self.preflight, "inspect_direnv", return_value={"status": "WARN", "available": False, "allowed": None, "reason": "direnv is not installed"}), patch.object(
                self.preflight,
                "shell",
                return_value={"ok": True, "stdout": f"{codex_bin}\n", "stderr": ""},
            ):
                report = self.preflight.evaluate_path_context(repo)
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["hardcoded_path_scan"]["status"], "PASS")
        self.assertEqual(report["codex_cli"]["status"], "PASS")

    def test_preflight_blocks_windows_codex_policy_surface(self) -> None:
        with self._tempdir() as tmpdir:
            repo, codex_bin = self._build_repo(Path(tmpdir))
            windows_config = repo.parent / "windows-home" / ".codex" / "config.toml"
            windows_config.parent.mkdir(parents=True, exist_ok=True)
            windows_config.write_text("approval_policy = \"on-request\"\n", encoding="utf-8")
            with patch.object(self.preflight, "inspect_direnv", return_value={"status": "PASS", "available": True, "allowed": True, "reason": ""}), patch.object(
                self.preflight,
                "shell",
                return_value={"ok": True, "stdout": f"{codex_bin}\n", "stderr": ""},
            ):
                report = self.preflight.evaluate_path_context(repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["windows_policy_surfaces"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
