from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "generate_closeout_v2_reports.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("generate_closeout_v2_reports", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load generate_closeout_v2_reports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class CloseoutV2ReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_windows_skill_disposition_uses_prior_remove_now_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            workflow_root = tmp / "Dev-Workflow"
            windows_home = tmp / "windows-home" / ".codex"
            skill_path = windows_home / "skills" / "dev-workflow"
            _write_json(
                repo_root / "contracts" / "workspace_authority.json",
                {
                    "canonical_roots": {
                        "management": str(repo_root),
                        "workflow": str(workflow_root),
                    },
                    "windows_app_state": {"codex_home": str(windows_home)},
                    "generation_targets": {"global_runtime": {"linux": {}}},
                },
            )
            _write_json(
                repo_root / "reports" / "windows-codex-policy-mirror-removal.apply.json",
                {
                    "windows_policy_surface_report": {
                        "findings": [
                            {
                                "path": str(skill_path),
                                "disposition": "REMOVE_NOW",
                                "reason": "stale mirror",
                                "details": {"is_structural_mirror": True},
                            }
                        ]
                    },
                    "applied_changes": [
                        {
                            "source_path": str(skill_path),
                            "action": "removed",
                            "rollback_path": "",
                        }
                    ],
                },
            )

            report = self.module.build_windows_skill_disposition(repo_root)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["disposition"], "REMOVE_NOW")
        self.assertEqual(report["action_taken"], "removed")
        self.assertFalse(report["exists_now"])

    def test_windows_ssh_probe_dedup_passes_with_cached_reports_and_single_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            scripts = repo_root / "scripts"
            reports = repo_root / "reports"
            scripts.mkdir(parents=True)
            reports.mkdir(parents=True)
            (scripts / "check_windows_app_ssh_readiness.py").write_text(
                'def run_windows_ssh():\n    return "OpenSSH\\\\ssh.exe"\n',
                encoding="utf-8",
            )
            (scripts / "check_global_runtime.py").write_text(
                "allow_cache_miss_live_probe=False\n",
                encoding="utf-8",
            )
            (scripts / "audit_workspace.py").write_text(
                "allow_cache_miss_live_probe=False\n",
                encoding="utf-8",
            )
            (scripts / "activate_codex_app_usability.py").write_text(
                'windows_app_ssh_readiness=windows\n--windows-ssh-readiness-report\n--no-live-windows-ssh-probe\n',
                encoding="utf-8",
            )
            _write_json(reports / "global-runtime.closeout-v2.final.json", {"windows_app_ssh_probe_source": "cached_report"})
            _write_json(reports / "audit.closeout-v2.final.json", {"windows_app_ssh_readiness": {"probe_source": "cached_report"}})
            _write_json(reports / "app-usability.closeout-v2.final-dry-run.json", {"windows_app_ssh_probe_source": "cached_report"})
            _write_json(reports / "windows-app-ssh-remote-readiness.closeout-v2.refresh.json", {"probe_source": "live_probe"})
            _write_json(reports / "windows-app-ssh-remote-readiness.final.json", {"probe_source": "cached_report"})

            report = self.module.build_windows_ssh_probe_dedup(repo_root)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["live_probe_owner_files"], [str(repo_root / "scripts" / "check_windows_app_ssh_readiness.py")])
        self.assertEqual(report["report_probe_sources"]["explicit_refresh"], "live_probe")

    def test_warn_disposition_prefers_closeout_startup_report_and_passes_when_all_entries_are_dispositioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            reports = repo_root / "reports"
            reports.mkdir(parents=True)
            _write_json(
                reports / "config-provenance.closeout-v2.final.json",
                {
                    "windows_policy_surface_findings": [
                        {
                            "path": "/mnt/c/Users/anise/.codex/config.toml",
                            "disposition": "MANUAL_REMEDIATION",
                            "reason": "external app state",
                        }
                    ]
                },
            )
            _write_json(
                reports / "global-runtime.closeout-v2.final.json",
                {
                    "overall_status": "WARN",
                    "client_surface_status": "WARN",
                    "path_contamination": {"local_contaminated_entries": ["/mnt/c/Users/anise/.codex/bin/wsl"]},
                },
            )
            _write_json(
                reports / "toolchain-surface.closeout-v2.final.json",
                {
                    "warnings": [
                        "Multiple terminal PATH mismatch is present.",
                        "Windows hooks are intentionally disabled.",
                    ]
                },
            )
            _write_json(
                reports / "hook-readiness.closeout-v2.final.json",
                {"windows_generation_reason": "Windows hook generation remains disabled."},
            )
            _write_json(
                reports / "score-layer.closeout-v2.final.json",
                {
                    "status": "BLOCKED",
                    "disqualifiers": ["startup gate remains blocked for the requested purpose"],
                    "warnings": [],
                },
            )
            _write_json(
                reports / "audit.closeout-v2.final.json",
                {
                    "status": "FAIL",
                    "startup_workflow_check": {"status": "BLOCKED"},
                },
            )
            _write_json(
                reports / "startup-workflow.closeout-v2.final.json",
                {"status": "BLOCKED", "serena": {"status": "BLOCKED", "summary": "activation pending"}},
            )
            _write_json(
                reports / "startup-workflow.final.json",
                {"status": "PASS", "serena": {"status": "PASS"}},
            )
            _write_json(
                reports / "app-usability.closeout-v2.final-dry-run.json",
                {
                    "status": "APP_READY_WITH_WARNINGS",
                    "status_reasons": ["Serena still blocks general code modification."],
                },
            )

            report = self.module.build_warn_disposition(
                repo_root,
                {"status": "PASS"},
                {"status": "PASS"},
                {"findings": []},
            )

        self.assertEqual(report["status"], "PASS")
        startup_entry = next(item for item in report["entries"] if item["id"] == "startup.serena_activation_pending")
        self.assertEqual(startup_entry["source_report"], "reports/startup-workflow.closeout-v2.final.json")


if __name__ == "__main__":
    unittest.main()
