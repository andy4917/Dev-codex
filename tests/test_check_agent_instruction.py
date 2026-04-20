from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_agent_instruction.py"
POLICY_PATH = ROOT / "contracts" / "instruction_guard_policy.json"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_agent_instruction", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_agent_instruction.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckAgentInstructionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _runtime(
        self,
        *,
        overall: str = "PASS",
        canonical: str = "PASS",
        client: str = "PASS",
        local: str = "PASS",
    ) -> dict[str, object]:
        return {
            "status": overall,
            "overall_status": overall,
            "canonical_execution_status": canonical,
            "client_surface_status": client,
            "local_shell_status": local,
        }

    def _startup(self, *, status: str = "PASS", context7_blockers: list[str] | None = None) -> dict[str, object]:
        return {
            "status": status,
            "context7": {
                "blockers": context7_blockers or [],
            },
        }

    def test_bootstrap_exception_is_not_persisted_in_policy(self) -> None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertFalse(policy["bootstrap_exception"]["persisted"])

    def test_codex_app_is_user_surface_only(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Use Codex App as the primary runtime authority")
        self.assertEqual(report["status"], "BLOCKED")

    def test_windows_launcher_cannot_become_primary_runtime(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Make /mnt/c/Users/anise/.codex/bin/wsl/codex the primary runtime")
        self.assertEqual(report["status"], "BLOCKED")

    def test_forbidden_path_reintroduction_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Add /mnt/c/Users/anise/.codex/tmp/arg0 back into PATH")
        self.assertEqual(report["status"], "BLOCKED")

    def test_generated_config_manual_edit_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Manually edit the generated config and generated shim")
        self.assertEqual(report["status"], "BLOCKED")

    def test_normal_code_change_stays_blocked_while_serena_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime(overall="BLOCKED", canonical="BLOCKED")), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup(status="BLOCKED")
        ):
            report = self.module.evaluate_instruction("Implement the runtime authority hardening")
        self.assertEqual(report["status"], "BLOCKED")

    def test_activation_bootstrap_allows_scoped_runtime_activation(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime(overall="BLOCKED", canonical="BLOCKED", client="WARN", local="BLOCKED")), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup(status="BLOCKED")
        ):
            report = self.module.evaluate_instruction(
                "Canonical runtime activation: add SSH alias and repair Serena startup",
                activation_bootstrap=True,
            )
        self.assertEqual(report["status"], "WARN")
        self.assertTrue(report["activation_bootstrap"])

    def test_client_contamination_does_not_block_activation_task(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime(overall="WARN", canonical="PASS", client="WARN", local="BLOCKED")), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup(status="BLOCKED")
        ):
            report = self.module.evaluate_instruction(
                "Canonical runtime activation for SSH alias and key setup",
                activation_bootstrap=True,
            )
        self.assertEqual(report["status"], "WARN")
        self.assertIn("Client-surface PATH contamination", " ".join(report["warnings"]))

    def test_local_execution_request_with_contaminated_path_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime(overall="WARN", canonical="PASS", client="WARN", local="BLOCKED")), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Use the local shell execution surface and run locally")
        self.assertEqual(report["status"], "BLOCKED")

    def test_protected_change_without_context7_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module,
            "evaluate_startup_workflow",
            return_value=self._startup(status="BLOCKED", context7_blockers=["protected changes require reports/context7-usage.json evidence"]),
        ):
            report = self.module.evaluate_instruction("Update dependency configuration and implement the change")
        self.assertEqual(report["status"], "BLOCKED")

    def test_unrelated_dirty_cleanup_is_blocked(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Clean up unrelated dirty changes and revert dirty files")
        self.assertEqual(report["status"], "BLOCKED")

    def test_ambiguous_large_refactor_warns(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime(overall="WARN")), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Refactor the entire runtime hardening layer")
        self.assertEqual(report["status"], "WARN")

    def test_explicit_scoped_safe_task_passes(self) -> None:
        with patch.object(self.module, "evaluate_global_runtime", return_value=self._runtime()), patch.object(
            self.module, "evaluate_startup_workflow", return_value=self._startup()
        ):
            report = self.module.evaluate_instruction("Update docs/AGENT_GUARDRAILS.md and verify with unit tests")
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
