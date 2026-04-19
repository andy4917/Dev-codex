from __future__ import annotations

import importlib.util
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
        self.authority = {
            "canonical_roots": {
                "management": "/home/andy4917/Dev-Management",
                "workflow": "/home/andy4917/Dev-Workflow",
                "product": "/home/andy4917/Dev-Product",
            },
            "generation_targets": {
                "scorecard": {
                    "delivery_gate": "/home/andy4917/Dev-Management/scripts/delivery_gate.py",
                    "summary_export": "/home/andy4917/Dev-Management/scripts/export_user_score_summary.py",
                    "runtime_hook": {
                        "state_root": "/tmp/scorecard-hook-tests",
                        "user_prompt_throttle_seconds": 300,
                    },
                }
            },
        }

    def test_emit_notice_for_workspace_inside_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            notice = self.module.emit_notice(
                authority=self.authority,
                cwd=Path("/home/andy4917/Dev-Workflow"),
                event="SessionStart",
                now=1000.0,
                state_dir=state_dir,
            )

        self.assertIn("Global scorecard layer is binding for /home/andy4917/Dev-Workflow", notice)
        self.assertIn("prepare_user_scorecard_review.py --workspace-root /home/andy4917/Dev-Workflow --mode verify", notice)

    def test_emit_notice_is_empty_outside_canonical_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            notice = self.module.emit_notice(
                authority=self.authority,
                cwd=Path("/tmp/non-canonical-workspace"),
                event="SessionStart",
                now=1000.0,
                state_dir=Path(tmpdir),
            )

        self.assertEqual(notice, "")

    def test_user_prompt_submit_is_throttled_per_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            first = self.module.emit_notice(
                authority=self.authority,
                cwd=Path("/home/andy4917/Dev-Workflow"),
                event="UserPromptSubmit",
                now=1000.0,
                state_dir=state_dir,
            )
            second = self.module.emit_notice(
                authority=self.authority,
                cwd=Path("/home/andy4917/Dev-Workflow"),
                event="UserPromptSubmit",
                now=1100.0,
                state_dir=state_dir,
            )
            third = self.module.emit_notice(
                authority=self.authority,
                cwd=Path("/home/andy4917/Dev-Workflow"),
                event="UserPromptSubmit",
                now=1405.0,
                state_dir=state_dir,
            )

        self.assertTrue(first)
        self.assertEqual(second, "")
        self.assertTrue(third)


if __name__ == "__main__":
    unittest.main()
