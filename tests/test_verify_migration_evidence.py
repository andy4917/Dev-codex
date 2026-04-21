from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "verify_migration_evidence.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class VerifyMigrationEvidenceTests(unittest.TestCase):
    def _build_workspace(self, root: Path, delivery_gate_exit: int = 0, delivery_gate_status: str = "PASS") -> tuple[Path, Path, Path]:
        repo_root = root / "Dev-Management"
        workflow_root = root / "Dev-Workflow"
        product_root = root / "Dev-Product"
        project_root = product_root / "reservation-system"
        linux_codex = root / "linux-home" / ".codex"
        windows_codex = root / "windows-home" / ".codex"
        quarantine_root = repo_root / "quarantine"
        historical_quarantine_root = quarantine_root / "2026-04-16"

        for path in [repo_root, workflow_root, project_root, linux_codex, windows_codex, historical_quarantine_root]:
            path.mkdir(parents=True, exist_ok=True)
        (repo_root / ".git").mkdir(exist_ok=True)
        (workflow_root / ".git").mkdir(exist_ok=True)
        (project_root / ".git").mkdir(exist_ok=True)

        agents_body = textwrap.dedent(
            f"""\
            # Generated Codex Workspace Contract

            - Authority file: `{repo_root / 'contracts' / 'workspace_authority.json'}`
            - Windows `.codex` policy-bearing files are forbidden active surfaces because Codex App can read them.
            - Use `.git` as the only project root marker.
            """
        )
        config_body = textwrap.dedent(
            f"""\
            approval_policy = "on-request"
            sandbox_mode = "workspace-write"
            web_search = "cached"
            project_root_markers = [".git"]

            [features]
            shell_zsh_fork = true

            [projects."{repo_root}"]
            trust_level = "trusted"

            [projects."{workflow_root}"]
            trust_level = "trusted"

            [projects."{product_root}"]
            trust_level = "trusted"
            """
        )

        _write_text(linux_codex / "AGENTS.md", agents_body)
        _write_text(linux_codex / "config.toml", config_body)
        _write_text(project_root / "AGENTS.md", "# Product rules\n")
        _write_text(project_root / ".codex" / "config.toml", 'project_root_markers = [".git"]\n')
        _write_text(project_root / "contracts" / "project_policy.json", "{}\n")

        authority = {
            "canonical_roots": {
                "management": str(repo_root),
                "workflow": str(workflow_root),
                "product": str(product_root),
            },
            "windows_app_state": {
                "codex_home": str(windows_codex),
            },
            "cleanup_policy": {
                "quarantine_root": str(quarantine_root),
            },
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "agents": str(linux_codex / "AGENTS.md"),
                        "config": str(linux_codex / "config.toml"),
                        "user_override_config": str(linux_codex / "user-config.toml"),
                    },
                },
                "global_config": {
                    "project_root_markers": [".git"],
                    "trusted_projects": [
                        str(repo_root),
                        str(workflow_root),
                        str(product_root),
                    ],
                },
            },
            "hardcoding_definition": {
                "path_rules": {
                    "historical_evidence_allowlist": ["migration_manifest.json"],
                    "historical_batch_paths_not_allowed_in_active_policy": ["cleanup_policy.quarantine_root"],
                    "legacy_repo_paths_to_remove": ["/legacy/reservation-system"],
                }
            },
        }
        _write_json(repo_root / "contracts" / "workspace_authority.json", authority)

        _write_json(
            repo_root / "migration_manifest.json",
            {
                "generated_at": "2026-04-16",
                "authority": str(repo_root / "contracts" / "workspace_authority.json"),
                "mappings": [
                    {
                        "before": "/legacy/reservation-system",
                        "after": str(project_root),
                        "action": "moved",
                        "scope": "product-repo",
                        "reason": "Promoted into the canonical product root.",
                    }
                ],
            },
        )
        _write_json(
            repo_root / "reports" / "cleanup_report.json",
            {
                "generated_at": "2026-04-16",
                "quarantine_root": str(quarantine_root),
                "moved_to_management": [str(repo_root / "contracts")],
                "moved_to_workflow": [str(workflow_root / "scripts")],
                "quarantined": [str(historical_quarantine_root / "legacy-markers")],
                "deleted": ["/legacy/code (removed after migration)"],
            },
        )
        _write_json(
            repo_root / "reports" / "inventory.after.json",
            {
                "generated_at": "2026-04-16",
                "canonical_roots": [str(repo_root), str(product_root.parent), str(workflow_root)],
            },
        )

        delivery_gate_script = textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            repo_root = Path(sys.argv[sys.argv.index("--workspace-root") + 1])
            report_path = repo_root / "reports" / "user-scorecard.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps({{"gate_status": "{delivery_gate_status}", "final_decision": "{delivery_gate_status}"}}, indent=2) + "\\n",
                encoding="utf-8",
            )
            print("{delivery_gate_status}")
            raise SystemExit({delivery_gate_exit})
            """
        )
        summary_script = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("1. disqualifier 결과: PASS")
            print("12. gate 상태: PASS")
            print("14. 최종 판정: PASS")
            """
        )
        audit_script = textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            from pathlib import Path

            repo_root = Path.cwd()
            linux_agents = Path({str(linux_codex / "AGENTS.md")!r})
            linux_config = Path({str(linux_codex / "config.toml")!r})
            project_agents = Path({str(project_root / "AGENTS.md")!r})
            project_config = Path({str(project_root / ".codex" / "config.toml")!r})
            windows_agents = Path({str(windows_codex / "AGENTS.md")!r})
            windows_config = Path({str(windows_codex / "config.toml")!r})
            windows_hooks = Path({str(windows_codex / "hooks.json")!r})
            windows_skills = Path({str(windows_codex / "skills" / "dev-workflow")!r})

            observed = [windows_agents, windows_config, windows_hooks, windows_skills]
            findings = []
            for path in observed:
                if not path.exists():
                    continue
                findings.append({{
                    "path": str(path),
                    "classification": "known_generated_cleanup_candidate" if path.is_dir() or path.read_text(encoding="utf-8", errors="ignore").startswith(("GENERATED - DO NOT EDIT", "# GENERATED - DO NOT EDIT")) else "unknown_policy_surface",
                    "reason": "Windows policy-bearing file remains present on an app-readable active surface and must be removed.",
                }})

            report = {{
                "authority_path": str(repo_root / "contracts" / "workspace_authority.json"),
                "trusted_projects": [str(repo_root), str(repo_root.parent / "Dev-Workflow"), str(repo_root.parent / "Dev-Product")],
                "agents_files": [str(linux_agents), str(project_agents)] + ([str(windows_agents)] if windows_agents.exists() else []),
                "config_files": [str(linux_config), str(project_config)] + ([str(windows_config)] if windows_config.exists() else []),
                "contracts_dirs": [
                    str(repo_root / "contracts"),
                    str(Path({str(project_root / "contracts")!r})),
                ],
                "violations": {{
                    "unexpected_agents": [],
                    "unexpected_configs": [],
                    "unexpected_contract_dirs": [],
                }},
                "project_rule_leaks": [],
                "project_root_markers_git_only": True,
                "windows_policy_surface_status": "BLOCKED" if findings else "PASS",
                "windows_policy_surface_findings": findings,
                "unknown_windows_policy_files_blocking": [item["path"] for item in findings if item["classification"] == "unknown_policy_surface"],
                "windows_app_evidence_status": "PASS",
                "linux_source_of_truth_proof": {{"status": "PASS"}},
                "status": "BLOCKED" if findings else "PASS",
            }}
            report_path = repo_root / "reports" / "audit.final.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
            print(json.dumps(report))
            raise SystemExit(0)
            """
        )

        _write_text(repo_root / "scripts" / "delivery_gate.py", delivery_gate_script)
        _write_text(repo_root / "scripts" / "export_user_score_summary.py", summary_script)
        _write_text(repo_root / "scripts" / "audit_workspace.py", audit_script)

        return repo_root, linux_codex, windows_codex

    def test_entrypoint_runs_required_commands_and_writes_migration_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, linux_codex, windows_codex = self._build_workspace(Path(tmpdir))
            output_path = repo_root / "reports" / "migration-verification.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRYPOINT),
                    "--repo-root",
                    str(repo_root),
                    "--linux-codex-home",
                    str(linux_codex),
                    "--windows-codex-home",
                    str(windows_codex),
                    "--output-file",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["command_results"]["delivery_gate_verify"]["exit_code"], 0)
            self.assertEqual(payload["command_results"]["export_user_score_summary"]["exit_code"], 0)
            self.assertEqual(payload["command_results"]["audit_workspace_write_report"]["exit_code"], 0)
            self.assertEqual(payload["migration_evidence"]["before_after_mapping"][0]["before"], "/legacy/reservation-system")
            self.assertEqual(
                payload["migration_evidence"]["canonical_tree"]["management"]["top_level_entries"],
                ["contracts", "migration_manifest.json", "quarantine", "reports", "scripts"],
            )

            surviving_agents = {
                item["path"]: item["justification"] for item in payload["migration_evidence"]["surviving_agents_files"]
            }
            self.assertIn("generated Linux runtime", surviving_agents[str(linux_codex / "AGENTS.md")])
            self.assertIn("project-specific rules are allowed", surviving_agents[str(repo_root.parent / "Dev-Product" / "reservation-system" / "AGENTS.md")])
            self.assertNotIn(str(windows_codex / "AGENTS.md"), surviving_agents)

            surviving_configs = {
                item["path"]: item["justification"] for item in payload["migration_evidence"]["surviving_config_files"]
            }
            self.assertIn("generated Linux runtime", surviving_configs[str(linux_codex / "config.toml")])
            self.assertIn("project-specific rules are allowed", surviving_configs[str(repo_root.parent / "Dev-Product" / "reservation-system" / ".codex" / "config.toml")])
            self.assertNotIn(str(windows_codex / "config.toml"), surviving_configs)

            cleanup = payload["migration_evidence"]["cleanup_summary"]
            self.assertEqual(cleanup["counts"]["quarantined"], 1)
            self.assertEqual(cleanup["counts"]["deleted"], 1)
            self.assertEqual(payload["migration_evidence"]["git_root_marker_proof"]["status"], "PASS")
            self.assertEqual(payload["migration_evidence"]["windows_policy_surface_proof"]["status"], "PASS")
            self.assertEqual(payload["migration_evidence"]["windows_policy_surface_proof"]["present_paths"], [])
            self.assertEqual(payload["migration_evidence"]["windows_policy_surface_proof"]["source_of_truth_proof"]["status"], "PASS")
            self.assertEqual(payload["migration_evidence"]["hardcoding_legacy_duplicate_audit"]["status"], "PASS")

    def test_entrypoint_continues_after_blocked_gate_and_returns_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, linux_codex, windows_codex = self._build_workspace(
                Path(tmpdir), delivery_gate_exit=2, delivery_gate_status="BLOCKED"
            )
            output_path = repo_root / "reports" / "migration-verification.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRYPOINT),
                    "--repo-root",
                    str(repo_root),
                    "--linux-codex-home",
                    str(linux_codex),
                    "--windows-codex-home",
                    str(windows_codex),
                    "--output-file",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(payload["command_results"]["delivery_gate_verify"]["exit_code"], 2)
            self.assertEqual(payload["command_results"]["export_user_score_summary"]["exit_code"], 0)
            self.assertEqual(payload["command_results"]["audit_workspace_write_report"]["exit_code"], 0)
            self.assertEqual(payload["migration_evidence"]["windows_policy_surface_proof"]["status"], "PASS")

    def test_entrypoint_blocks_when_windows_policy_surface_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root, linux_codex, windows_codex = self._build_workspace(Path(tmpdir))
            output_path = repo_root / "reports" / "migration-verification.json"
            (windows_codex / "config.toml").write_text(
                '# GENERATED - DO NOT EDIT\napproval_policy = "never"\nproject_root_markers = [".git"]\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(ENTRYPOINT),
                    "--repo-root",
                    str(repo_root),
                    "--linux-codex-home",
                    str(linux_codex),
                    "--windows-codex-home",
                    str(windows_codex),
                    "--output-file",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 2, msg=result.stderr)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            proof = payload["migration_evidence"]["windows_policy_surface_proof"]
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertEqual(proof["status"], "BLOCKED")
            self.assertEqual(proof["present_paths"], [str(windows_codex / "config.toml")])
            self.assertEqual(proof["source_of_truth_proof"]["status"], "PASS")
            self.assertEqual(proof["audit_report_value"], "BLOCKED")

            surviving_configs = {
                item["path"]: item["justification"] for item in payload["migration_evidence"]["surviving_config_files"]
            }
            self.assertIn(
                "should be removed, not a canonical authority target",
                surviving_configs[str(windows_codex / "config.toml")],
            )


if __name__ == "__main__":
    unittest.main()
