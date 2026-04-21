from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "drift_audit.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DriftAuditTests(unittest.TestCase):
    def _build_workspace(self, root: Path) -> tuple[Path, Path]:
        repo_root = root / "Dev-Management"
        workflow_root = root / "Dev-Workflow"
        product_root = root / "Dev-Product"
        project_root = product_root / "reservation-system"
        quarantine_root = repo_root / "quarantine" / "2026-04-16"
        linux_codex = root / "linux-home" / ".codex"
        windows_codex = root / "windows-home" / ".codex"

        for path in [repo_root, workflow_root, project_root, quarantine_root, linux_codex, windows_codex]:
            path.mkdir(parents=True, exist_ok=True)

        (repo_root / ".git").mkdir(exist_ok=True)
        (workflow_root / ".git").mkdir(exist_ok=True)
        (project_root / ".git").mkdir(exist_ok=True)

        _write_text(project_root / "AGENTS.md", "# Product rules\n")
        _write_text(project_root / ".codex" / "config.toml", 'project_root_markers = [".git"]\n')
        _write_text(project_root / "contracts" / "project_policy.json", "{}\n")
        _write_text(linux_codex / "config.toml", 'project_root_markers = [".git"]\n')
        _write_text(windows_codex / "config.toml", '# GENERATED - DO NOT EDIT\nproject_root_markers = [".git"]\n')

        authority = {
            "canonical_roots": {
                "management": str(repo_root),
                "workflow": str(workflow_root),
                "product": str(product_root),
            },
            "classification_rules": {
                "workflow": {
                    "canonical_skill_source": "skills",
                }
            },
            "runtime_state_exclusions": [
                "reports",
                "logs",
                "caches",
            ],
            "cleanup_policy": {
                "quarantine_root": str(quarantine_root),
            },
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "config": str(linux_codex / "config.toml"),
                    },
                },
                "global_config": {
                    "project_root_markers": [".git"],
                },
            },
            "windows_app_state": {
                "codex_home": str(windows_codex),
            },
        }
        _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
        return repo_root, project_root

    def _run(self, authority_path: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ENTRYPOINT),
                "--authority-path",
                str(authority_path),
                "--output-file",
                str(output_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_passes_with_canonical_project_local_and_runtime_state_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root, project_root = self._build_workspace(tmp)
            output_path = repo_root / "reports" / "drift-audit.json"

            (repo_root / "reports" / "contracts").mkdir(parents=True)
            (repo_root / "contracts").mkdir(exist_ok=True)
            (repo_root / "reports" / "contracts" / "snapshot.json").write_text("{}\n", encoding="utf-8")
            (repo_root.parent / "Dev-Workflow" / "skills").mkdir(parents=True, exist_ok=True)

            result = self._run(repo_root / "contracts" / "workspace_authority.json", output_path)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["summary"]["canonical"], 2)
            self.assertEqual(payload["summary"]["project-local"], 3)
            self.assertEqual(payload["summary"]["runtime-state"], 1)
            self.assertEqual(payload["summary"]["quarantine-worthy"], 0)

            by_path = {entry["path"]: entry for entry in payload["artifacts"]}
            runtime_contracts = str((repo_root / "reports" / "contracts").resolve())
            self.assertEqual(by_path[runtime_contracts]["classification"], "runtime-state")
            self.assertEqual(by_path[str((project_root / "AGENTS.md").resolve())]["classification"], "project-local")
            self.assertEqual(by_path[str((repo_root.parent / "Dev-Workflow" / "skills").resolve())]["classification"], "canonical")

    def test_fails_on_misplaced_policy_artifacts_and_non_git_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root, _project_root = self._build_workspace(tmp)
            workflow_root = repo_root.parent / "Dev-Workflow"
            product_root = repo_root.parent / "Dev-Product"
            output_path = repo_root / "reports" / "drift-audit.json"

            _write_text(workflow_root / "AGENTS.md", "# misplaced\n")
            (repo_root / "rules").mkdir(parents=True)
            (workflow_root / "legacy.hg" / ".svn").mkdir(parents=True)

            rogue_project = product_root / "rogue-project"
            rogue_project.mkdir(parents=True)
            _write_text(rogue_project / "AGENTS.md", "# bad\n")
            _write_text(rogue_project / ".codex" / "config.toml", 'project_root_markers = [".git", "pyproject.toml"]\n')
            (rogue_project / "contracts").mkdir(parents=True)
            (product_root / "reservation-system" / "rules").mkdir(parents=True)
            _write_text(product_root / "reservation-system" / "hooks.json", "{}\n")

            result = self._run(repo_root / "contracts" / "workspace_authority.json", output_path)

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["checks"]["project_specific_rules_outside_product"]["status"], "FAIL")
            self.assertEqual(payload["checks"]["git_only_project_root_marker"]["status"], "FAIL")

            violations = payload["checks"]["project_specific_rules_outside_product"]["violations"]
            self.assertIn(str((workflow_root / "AGENTS.md").resolve()), violations)
            self.assertIn(str((repo_root / "rules").resolve()), violations)
            self.assertIn(str((product_root / "reservation-system" / "rules").resolve()), violations)
            self.assertIn(str((product_root / "reservation-system" / "hooks.json").resolve()), violations)

            git_check = payload["checks"]["git_only_project_root_marker"]
            self.assertIn(str(rogue_project.resolve()), git_check["project_roots_missing_git"])
            self.assertEqual(
                git_check["config_marker_violations"][0]["markers"],
                [".git", "pyproject.toml"],
            )
            self.assertEqual(
                git_check["repository_marker_violations"][0]["marker"],
                ".svn",
            )
