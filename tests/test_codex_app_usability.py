from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "activate_codex_app_usability.py"
RENDER_PATH = ROOT / "scripts" / "render_codex_runtime.py"


def _load_module(path: Path, name: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexAppUsabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module(SCRIPT_PATH, "activate_codex_app_usability")
        self.render = _load_module(RENDER_PATH, "render_codex_runtime_for_usability")

    def _authority(self, tmp: Path) -> dict[str, object]:
        return {
            "canonical_roots": {
                "management": str(tmp),
                "workflow": str(tmp / "workflow"),
                "product": str(tmp / "product"),
            },
            "cleanup_policy": {"quarantine_root": str(tmp / "quarantine")},
            "runtime_layering": {
                "restore_seed_policy": {
                    "preferred_windows_access_host": "wsl.localhost",
                    "terminal_restore_policy": "background",
                    "conversation_detail_mode": "steps",
                },
                "user_override_policy": {
                    "allowed_fields": ["model"],
                    "protected_fields": ["canonical_roots"],
                    "blocked_feature_overrides": ["remote_control"],
                },
            },
            "windows_app_state": {"codex_home": str(tmp / "win" / ".codex")},
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "launcher": str(tmp / ".local" / "bin" / "codex"),
                        "config": str(tmp / ".codex" / "config.toml"),
                        "agents": str(tmp / ".codex" / "AGENTS.md"),
                        "user_override_config": str(tmp / ".codex" / "user-config.toml"),
                    },
                },
                "scorecard": {
                    "policy": str(tmp / "contracts" / "user_score_policy.json"),
                    "disqualifiers": str(tmp / "contracts" / "disqualifier_policy.json"),
                    "reviewer_verdict_root": str(tmp / "state" / "reviewer-verdicts"),
                    "review_snapshot": str(tmp / "reports" / "user-scorecard.review.json"),
                    "closeout": str(tmp / "scripts" / "iaw_closeout.py"),
                    "delivery_gate": str(tmp / "scripts" / "delivery_gate.py"),
                    "summary_export": str(tmp / "scripts" / "export_user_score_summary.py"),
                    "score_layer": str(tmp / "scripts" / "run_score_layer.py"),
                    "workspace_authority_root": str(tmp / "state" / "workspace-authority"),
                    "receipt_state_root": str(tmp / "state" / "iaw"),
                    "runtime_hook": {"events": {}},
                },
            },
            "observed_remote_evidence": {},
            "canonical_remote_execution_surface": {"id": "ssh-devmgmt-wsl", "host_alias": "devmgmt-wsl"},
            "control_thread_policy": {"name": "Dev-Management Control", "remote_host": "devmgmt-wsl"},
            "worktree_policy_summary": {"persistent_ops_worktree_allowed": False, "task_worktrees_are_ephemeral": True},
            "hardcoding_definition": {"feature_rules": {"forbidden_feature_flags": ["telepathy", "workspace_dependencies"]}},
        }

    def test_app_ready_with_warnings_when_serena_only_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "reports").mkdir()
            authority = self._authority(tmp)
            with patch.object(self.module, "load_authority", return_value=authority), patch.object(
                self.module,
                "load_app_policy",
                return_value={"settings_flow": {"settings_path": "Settings > Connections", "host_alias": "devmgmt-wsl", "remote_project": str(tmp)}},
            ), patch.object(
                self.module,
                "evaluate_global_runtime",
                return_value={
                    "overall_status": "WARN",
                    "canonical_execution_status": "PASS",
                    "ssh_runtime_status": "PASS",
                    "remote_codex_resolution_status": {"status": "PASS"},
                    "remote_native_codex_status": {"status": "PASS", "selected_path": "/home/andy4917/.local/share/dev-management/codex-npm/bin/codex", "version": "codex-cli 0.122.0"},
                },
            ), patch.object(
                self.module,
                "evaluate_windows_app_ssh_readiness",
                return_value={"status": "PASS", "windows_ssh_config": str(tmp / "ssh" / "config"), "applied": False, "backups": [], "simple_user_instruction": "Open Settings > Connections."},
            ), patch.object(
                self.module,
                "evaluate_config_provenance",
                return_value={"gate_status": "PASS", "windows_policy_surface_status": "PASS", "app_state_surface": {"status": "PASS"}},
            ), patch.object(
                self.module,
                "evaluate_active_config_smoke",
                return_value={"gate_status": "PASS", "windows_app_evidence_status": "PASS"},
            ), patch.object(
                self.module,
                "evaluate_toolchain_surface",
                return_value={"status": "PASS"},
            ), patch.object(
                self.module,
                "evaluate_git_surfaces",
                return_value={"status": "WARN"},
            ), patch.object(
                self.module,
                "evaluate_hook_readiness",
                return_value={"status": "WARN", "hook_only_enforcement_claim": False},
            ), patch.object(
                self.module,
                "install_linux_codex_cli",
                return_value={"status": "PASS", "applied": False, "path": "/home/andy4917/.local/share/dev-management/codex-npm/bin/codex", "version": "codex-cli 0.122.0"},
            ), patch.object(
                self.module,
                "repair_linux_launcher_shim",
                return_value={"status": "PASS", "preview_path": str(tmp / "preview.sh"), "live_write_allowed": True, "current_target": "/home/andy4917/.local/share/dev-management/codex-npm/bin/codex", "expected_target": "/home/andy4917/.local/share/dev-management/codex-npm/bin/codex", "reasons": [], "changed": False},
            ), patch.object(
                self.module,
                "repair_serena",
                return_value={"actions_planned": [], "actions_applied": []},
            ), patch.object(
                self.module,
                "evaluate_startup_workflow",
                return_value={"status": "WARN"},
            ), patch.object(
                self.module,
                "evaluate_artifact_hygiene",
                return_value={"status": "PASS"},
            ), patch.object(
                self.module,
                "evaluate_score_layer",
                return_value={"status": "WARN"},
            ), patch.object(
                self.module,
                "run_audit_cli",
                return_value={"status": "WARN"},
            ):
                report = self.module.evaluate_app_usability(tmp)

        self.assertEqual(report["status"], "APP_READY_WITH_WARNINGS")
        self.assertEqual(report["windows_app_ssh_status"], "PASS")
        self.assertEqual(report["serena_status"], "WARN")
        self.assertEqual(report["control_thread_status"], "PASS")

    def test_app_not_ready_when_remote_codex_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "reports").mkdir()
            authority = self._authority(tmp)
            with patch.object(self.module, "load_authority", return_value=authority), patch.object(
                self.module,
                "load_app_policy",
                return_value={"settings_flow": {"settings_path": "Settings > Connections", "host_alias": "devmgmt-wsl", "remote_project": str(tmp)}},
            ), patch.object(
                self.module,
                "evaluate_global_runtime",
                return_value={
                    "overall_status": "BLOCKED",
                    "canonical_execution_status": "PASS",
                    "ssh_runtime_status": "PASS",
                    "remote_codex_resolution_status": {"status": "BLOCKED"},
                    "remote_native_codex_status": {"status": "BLOCKED"},
                },
            ), patch.object(
                self.module,
                "evaluate_windows_app_ssh_readiness",
                return_value={"status": "PASS", "windows_ssh_config": str(tmp / "ssh" / "config"), "applied": False, "backups": [], "simple_user_instruction": "Open Settings > Connections."},
            ), patch.object(
                self.module,
                "evaluate_config_provenance",
                return_value={"gate_status": "PASS", "windows_policy_surface_status": "PASS", "app_state_surface": {"status": "PASS"}},
            ), patch.object(
                self.module,
                "evaluate_active_config_smoke",
                return_value={"gate_status": "PASS", "windows_app_evidence_status": "PASS"},
            ), patch.object(
                self.module,
                "evaluate_toolchain_surface",
                return_value={"status": "BLOCKED"},
            ), patch.object(
                self.module,
                "evaluate_git_surfaces",
                return_value={"status": "WARN"},
            ), patch.object(
                self.module,
                "evaluate_hook_readiness",
                return_value={"status": "PASS", "hook_only_enforcement_claim": False},
            ), patch.object(
                self.module,
                "install_linux_codex_cli",
                return_value={"status": "BLOCKED", "applied": False, "path": "", "version": ""},
            ), patch.object(
                self.module,
                "repair_linux_launcher_shim",
                return_value={"status": "BLOCKED", "preview_path": str(tmp / "preview.sh"), "live_write_allowed": False, "current_target": "/mnt/c/Users/anise/.codex/bin/wsl/codex", "expected_target": "/home/andy4917/.local/share/dev-management/codex-npm/bin/codex", "reasons": ["blocked"], "changed": False},
            ), patch.object(
                self.module,
                "repair_serena",
                return_value={"actions_planned": [], "actions_applied": []},
            ), patch.object(
                self.module,
                "evaluate_startup_workflow",
                return_value={"status": "WARN"},
            ), patch.object(
                self.module,
                "evaluate_artifact_hygiene",
                return_value={"status": "PASS"},
            ), patch.object(
                self.module,
                "evaluate_score_layer",
                return_value={"status": "BLOCKED"},
            ), patch.object(
                self.module,
                "run_audit_cli",
                return_value={"status": "FAIL"},
            ):
                report = self.module.evaluate_app_usability(tmp)

        self.assertEqual(report["status"], "APP_NOT_READY")
        self.assertEqual(report["remote_codex_status"], "BLOCKED")

    def test_generated_agents_include_app_setup_guidance(self) -> None:
        authority = self._authority(ROOT)
        authority["control_thread_policy"] = {"name": "Dev-Management Control", "remote_host": "devmgmt-wsl"}
        authority["worktree_policy_summary"] = {"persistent_ops_worktree_allowed": False, "task_worktrees_are_ephemeral": True}
        agents = self.render.render_agents(authority, windows=False)
        self.assertIn("User app setup path: Restart Codex App -> Settings > Connections -> select devmgmt-wsl", agents)
        self.assertIn("Optional user override source is /home/andy4917/.codex/user-config.toml only.", agents)
        self.assertIn("Dev-Management Control", agents)


if __name__ == "__main__":
    unittest.main()
