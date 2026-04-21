from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = ROOT / "scripts" / "check_startup_workflow.py"
AUDIT_PATH = ROOT / "scripts" / "audit_workspace.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class CheckStartupWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = _load_module(CHECKER_PATH, "check_startup_workflow_contract")
        self.audit = _load_module(AUDIT_PATH, "audit_workspace_startup_contract")

    def _build_repo(self, root: Path) -> tuple[Path, Path]:
        repo_root = root / "Dev-Management"
        home = root / "home"
        linux_codex = home / ".codex"
        windows_codex = root / "windows-home" / ".codex"
        repo_root.mkdir(parents=True)
        linux_codex.mkdir(parents=True)
        windows_codex.mkdir(parents=True)

        config_text = """project_root_markers = [".git"]

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
enabled = true
required = false
tool_timeout_sec = 30

[mcp_servers.context7.env_http_headers]
CONTEXT7_API_KEY = "CONTEXT7_API_KEY"

[mcp_servers.serena]
enabled = true
required = false
startup_timeout_sec = 15
tool_timeout_sec = 120
command = "serena"
args = ["start-mcp-server", "--project-from-cwd", "--context=codex"]
disabled_tools = ["execute_shell_command", "remove_project"]
"""
        _write_text(linux_codex / "config.toml", config_text)
        _write_text(windows_codex / "config.toml", config_text)

        authority = {
            "canonical_roots": {
                "management": str(repo_root),
                "workflow": str(root / "Dev-Workflow"),
                "product": str(root / "Dev-Product"),
            },
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "config": str(linux_codex / "config.toml"),
                        "agents": str(linux_codex / "AGENTS.md"),
                    },
                }
            },
            "windows_app_state": {
                "codex_home": str(windows_codex),
            },
        }
        context7_policy = {
            "remote_template": {
                "url": "https://mcp.context7.com/mcp",
                "enabled": True,
                "required": False,
                "tool_timeout_sec": 30,
                "env_http_headers": {
                    "CONTEXT7_API_KEY": "CONTEXT7_API_KEY",
                },
            },
            "protected_change_globs": [
                "pyproject.toml",
                "uv.lock",
                "requirements*.txt",
                ".codex/*.toml",
            ],
            "self_config_globs": [
                ".codex/config.toml",
            ],
            "required_report_fields": [
                "query",
                "resolved_library_id",
                "docs_retrieved",
                "version_evidence",
                "decision_summary",
            ],
        }
        serena_policy = {
            "template": {
                "enabled": True,
                "required": False,
                "startup_timeout_sec": 15,
                "tool_timeout_sec": 120,
                "command": "serena",
                "args": ["start-mcp-server", "--project-from-cwd", "--context=codex"],
                "disabled_tools": ["execute_shell_command", "remove_project"],
            },
            "override_policy": {
                "forbidden_keys": [
                    "url",
                    "bearer_token_env_var",
                    "http_headers",
                    "env_http_headers",
                ]
            },
            "required_actions": [
                "uv tool install -p 3.13 serena-agent@latest --prerelease=allow",
                "serena init",
                "cd <repo> && serena project create --index",
            ],
        }
        _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
        _write_json(repo_root / "contracts" / "context7_policy.json", context7_policy)
        _write_json(repo_root / "contracts" / "serena_policy.json", serena_policy)
        _write_text(repo_root / "README.md", "# baseline\n")

        _git(repo_root, "init")
        _git(repo_root, "config", "user.email", "codex@example.com")
        _git(repo_root, "config", "user.name", "Codex")
        _git(repo_root, "add", ".")
        _git(repo_root, "commit", "-m", "baseline")
        return repo_root, home

    def _env(self, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{home / 'bin'}:{env.get('PATH', '')}"
        return env

    def _prepare_serena_ready(self, repo_root: Path, home: Path, *, activation_ok: bool, onboarding_ok: bool) -> None:
        binary = home / "bin" / "serena"
        _write_text(binary, "#!/usr/bin/env bash\nexit 0\n")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        _write_text(home / ".serena" / "serena_config.yml", "language_backend: LSP\n")
        _write_text(repo_root / ".serena" / "project.yml", 'project_name: "Dev-Management"\n')
        if onboarding_ok:
            _write_text(repo_root / ".serena" / "memories" / "onboarding.md", "# onboarding\n")

        log_text = "INFO Serena started normally\n"
        if not activation_ok:
            log_text += "WARNING No project root found from /mnt/c/Program Files/WindowsApps/OpenAI.Codex/app/resources; not activating any project\n"
        _write_text(home / ".serena" / "logs" / "2026-04-20" / "mcp_latest.txt", log_text)

    def test_no_repo_changes_passes_without_requiring_startup_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            with patch.dict(os.environ, self._env(home), clear=False):
                report = self.checker.evaluate_startup_workflow(repo_root)

            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["serena"]["required"])
            self.assertFalse(report["context7"]["required"])
            self.assertEqual(report["context7"]["step"]["status"], "WAIVED")

    def test_serena_startup_blocks_when_onboarding_and_activation_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            self._prepare_serena_ready(repo_root, home, activation_ok=False, onboarding_ok=False)
            _write_text(repo_root / "scripts" / "task.py", "print('hello')\n")

            with patch.dict(os.environ, self._env(home), clear=False):
                report = self.checker.evaluate_startup_workflow(repo_root)
                audit_report = self.audit.build_startup_workflow_check(repo_root)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("Serena onboarding has not been performed for the current repo", report["blocking_reasons"])
            self.assertEqual(report["serena"]["activation"]["status"], "BLOCKED")
            self.assertIn("not activating any project", report["serena"]["activation"]["matched_lines"][0])
            self.assertEqual(audit_report["status"], "BLOCKED")

    def test_context7_protected_changes_require_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            self._prepare_serena_ready(repo_root, home, activation_ok=True, onboarding_ok=True)
            _write_text(repo_root / "pyproject.toml", "[project]\nname = 'demo'\n")

            with patch.dict(os.environ, self._env(home), clear=False):
                report = self.checker.evaluate_startup_workflow(repo_root)

            self.assertEqual(report["status"], "BLOCKED")
            self.assertTrue(report["context7"]["required"])
            self.assertIn(
                "protected changes require reports/context7-usage.json evidence",
                report["context7"]["blockers"],
            )

    def test_context7_self_config_change_autogenerates_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            self._prepare_serena_ready(repo_root, home, activation_ok=True, onboarding_ok=True)
            _write_text(repo_root / ".codex" / "config.toml", "[mcp_servers.context7]\nenabled = true\n")

            with patch.dict(os.environ, self._env(home), clear=False):
                report = self.checker.evaluate_startup_workflow(repo_root)

            self.assertEqual(report["context7"]["status"], "PASS")
            self.assertEqual(report["context7"]["entries"][0]["resolved_library_id"], "context7-remote-http")

    def test_app_usability_scope_warns_when_serena_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            self._prepare_serena_ready(repo_root, home, activation_ok=False, onboarding_ok=False)
            _write_text(repo_root / "scripts" / "task.py", "print('hello')\n")

            with patch.dict(os.environ, self._env(home), clear=False):
                report = self.checker.evaluate_startup_workflow(repo_root, purpose="app-usability")

            self.assertEqual(report["status"], "WARN")
            self.assertEqual(report["purpose"], "app-usability")
            self.assertIn("Serena onboarding has not been performed for the current repo", report["warnings"])

    def test_cli_writes_report_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, home = self._build_repo(Path(tmpdir))
            output_path = repo_root / "reports" / "startup-workflow.json"
            with patch.dict(os.environ, self._env(home), clear=False), patch.object(
                sys,
                "argv",
                [
                    "check_startup_workflow.py",
                    "--repo-root",
                    str(repo_root),
                    "--output-file",
                    str(output_path),
                ],
            ):
                exit_code = self.checker.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
