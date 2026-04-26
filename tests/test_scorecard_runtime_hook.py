from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "scorecard_runtime_hook.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("scorecard_runtime_hook", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scorecard_runtime_hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScorecardRuntimeHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.workflow_root = Path(r"C:\Users\anise\code\Dev-Workflow")
        self.authority = {
            "canonical_roots": {
                "management": r"C:\Users\anise\code\Dev-Management",
                "workflow": str(self.workflow_root),
                "product": r"C:\Users\anise\code\Dev-Product",
            },
            "generation_targets": {
                "scorecard": {
                    "closeout": r"C:\Users\anise\code\Dev-Management\scripts\iaw_closeout.py",
                    "delivery_gate": r"C:\Users\anise\code\Dev-Management\scripts\delivery_gate.py",
                    "summary_export": r"C:\Users\anise\code\Dev-Management\scripts\export_user_score_summary.py",
                    "runtime_hook": {
                        "state_root": "/tmp/scorecard-hook-tests",
                        "user_prompt_throttle_seconds": 0,
                    },
                }
            },
        }

    def test_emit_notice_for_workspace_inside_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            notice = self.module.emit_notice(
                authority=self.authority,
                cwd=self.workflow_root,
                event="UserPromptSubmit",
                now=1000.0,
                state_dir=state_dir,
            )

        self.assertIn(f"Binding scorecard layer for {self.workflow_root}", notice)
        self.assertIn(f"iaw_closeout.py --workspace-root {self.workflow_root} --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify", notice)

    def test_emit_notice_is_empty_outside_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            notice = self.module.emit_notice(
                authority=self.authority,
                cwd=Path(r"C:\Users\anise\outside-workspace"),
                event="UserPromptSubmit",
                now=1000.0,
                state_dir=Path(tmpdir),
            )

        self.assertEqual(notice, "")

    def test_user_prompt_submit_emits_every_task_turn_when_unthrottled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            first = self.module.emit_notice(
                authority=self.authority,
                cwd=self.workflow_root,
                event="UserPromptSubmit",
                now=1000.0,
                state_dir=state_dir,
            )
            second = self.module.emit_notice(
                authority=self.authority,
                cwd=self.workflow_root,
                event="UserPromptSubmit",
                now=1001.0,
                state_dir=state_dir,
            )

        self.assertTrue(first)
        self.assertTrue(second)

    def test_user_prompt_submit_response_is_json_object_with_additional_context(self) -> None:
        notice = "[scorecard-hook] Binding scorecard layer"
        payload = self.module.user_prompt_submit_response(notice)

        self.assertIs(payload["continue"], True)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(payload["hookSpecificOutput"]["additionalContext"], notice)
        json.dumps(payload)

    def test_user_prompt_submit_response_empty_notice_is_empty_json_object(self) -> None:
        self.assertEqual(self.module.user_prompt_submit_response(""), {})

    def test_hooks_payload_targets_user_prompt_submit(self) -> None:
        from devmgmt_runtime.scorecard_hook import hooks_payload

        payload = hooks_payload(self.authority)
        hook = payload["hooks"]["UserPromptSubmit"][0]["hooks"][0]

        self.assertEqual(payload["hooks"]["UserPromptSubmit"][0]["matcher"], ".*")
        self.assertEqual(hook["type"], "command")
        self.assertIn("scorecard_runtime_hook.py", hook["command"])
        self.assertIn("--event UserPromptSubmit", hook["command"])
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
