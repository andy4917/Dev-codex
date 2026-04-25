from __future__ import annotations

import unittest

from devmgmt_runtime.reference_graph import build_reference_graph


class ReferenceGraphTests(unittest.TestCase):
    def test_runbook_points_to_global_workflow(self) -> None:
        report = build_reference_graph(".")
        edges = {(item["source"], item["target"]) for item in report["edges"]}
        self.assertIn(("docs/RUNBOOK.md", "docs/GLOBAL_AGENT_WORKFLOW.md"), edges)

    def test_closeout_uses_windows_only_checks(self) -> None:
        report = build_reference_graph(".")
        edges = {(item["source"], item["target"]) for item in report["edges"]}
        self.assertIn(("scripts/iaw_closeout.py", "scripts/check_user_dev_environment.py"), edges)
        self.assertIn(("scripts/iaw_closeout.py", "scripts/check_global_agent_workflow.py"), edges)


if __name__ == "__main__":
    unittest.main()
