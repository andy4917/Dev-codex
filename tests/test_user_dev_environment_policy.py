from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "user_dev_environment_policy.json"


class UserDevEnvironmentPolicyTests(unittest.TestCase):
    def test_policy_declares_windows_native_control_plane(self) -> None:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 6)
        self.assertEqual(payload["app_control_plane"]["role"], "windows_native_app_control_plane")
        self.assertEqual(payload["windows_codex_boundary"]["role"], "WINDOWS_NATIVE_CONTROL_PLANE_VALIDATED")
        self.assertTrue(payload["windows_codex_boundary"]["allow_full_access_for_trusted_windows_roots"])
        self.assertEqual(payload["windows_surface"]["windows_codex_control_plane"], "Windows .codex is USER_CONTROL_PLANE + APP_STATE, not repo authority.")
        self.assertFalse(payload["ssh_decommission"]["active_development_surface"])
        self.assertIn("utf8", payload["powershell_policy_surface"]["policies"])

    def test_target_config_accepts_trusted_full_access(self) -> None:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        target = payload["target_app_config"]
        self.assertEqual(target["approval_policy"], "never")
        self.assertEqual(target["sandbox_mode"], "danger-full-access")
        self.assertEqual(target["windows_sandbox"], "elevated")
        self.assertNotIn("model_reasoning_effort", target)
        self.assertIn("model_reasoning_effort", payload["windows_codex_boundary"]["user_selected_runtime_preferences"])
        blocked = payload["windows_codex_boundary"]["blocked_value_rules"]
        self.assertEqual(blocked["approval_policy"], [])
        self.assertEqual(blocked["sandbox_mode"], [])

    def test_legacy_runtime_decommission_is_completed_after_evidence(self) -> None:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        decommission = payload["linux_decommission"]
        self.assertEqual(decommission["steady_state_role"], "none")
        self.assertFalse(decommission["preserve_until_verified"])
        self.assertEqual(decommission["decommission_status"], "completed_by_user_authorized_cleanup")
        self.assertIn("windows_native_checks_pass", decommission["delete_allowed_only_after"])
        self.assertTrue(payload["forbidden"]["unverified_delete_of_migration_evidence"])


if __name__ == "__main__":
    unittest.main()
