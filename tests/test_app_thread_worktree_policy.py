from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class AppThreadWorktreePolicyTests(unittest.TestCase):
    def test_permanent_control_thread_is_allowed_but_not_authority(self) -> None:
        payload = _load_json(ROOT / "contracts" / "app_surface_policy.json")
        control_thread = payload["control_thread"]
        self.assertTrue(control_thread["required"])
        self.assertEqual(control_thread["name"], "Dev-Management Control")
        self.assertFalse(control_thread["thread_is_execution_authority"])
        self.assertFalse(control_thread["thread_is_policy_authority"])

    def test_persistent_ops_worktree_is_not_authority(self) -> None:
        payload = _load_json(ROOT / "contracts" / "execution_surfaces.json")
        worktree = payload["worktree_policy"]
        self.assertFalse(worktree["persistent_ops_worktree_is_authority"])
        self.assertTrue(worktree["task_worktrees_are_ephemeral"])
        self.assertTrue(worktree["generated_mirrors_must_use_canonical_repo_root"])

    def test_generated_mirrors_bind_to_canonical_repo_root(self) -> None:
        authority = _load_json(ROOT / "contracts" / "workspace_authority.json")
        config_policy = _load_json(ROOT / "contracts" / "config_provenance_policy.json")
        self.assertEqual(authority["generated_mirror_contract"]["canonical_repo_root"], "/home/andy4917/Dev-Management")
        self.assertTrue(config_policy["worktree_rules"]["generated_mirrors_must_use_canonical_repo_root"])

    def test_app_memory_and_thread_context_are_hints_only(self) -> None:
        payload = _load_json(ROOT / "contracts" / "app_surface_policy.json")
        self.assertFalse(payload["auth_surface"]["app_memory_is_authority"])
        self.assertFalse(payload["auth_surface"]["thread_memory_is_authority"])

    def test_score_policy_blocks_worktree_source_of_truth_escalation(self) -> None:
        payload = _load_json(ROOT / "contracts" / "score_policy.json")
        self.assertEqual(payload["worktree_policy"]["worktree_source_of_truth_escalation_status"], "BLOCKED")
        self.assertEqual(payload["worktree_policy"]["branch_lock_conflict_status"], "BLOCKED")
        self.assertEqual(payload["worktree_policy"]["stale_persistent_worktree_status"], "WARN")


if __name__ == "__main__":
    unittest.main()
