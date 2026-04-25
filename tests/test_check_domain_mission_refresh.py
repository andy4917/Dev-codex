from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_domain_mission_refresh.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_domain_mission_refresh", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_domain_mission_refresh.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mission_frame(run_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "parent_domain": "governance_closeout",
        "workstream": "policy_and_evidence_enforcement",
        "parent_objective": "Keep closeout aligned with repo-owned authority.",
        "why_this_task_exists": "test fixture",
        "this_turn_goal": "test fixture",
        "target_state": "PASS or BLOCKED with evidence.",
        "done_when_evidence": ["checker evidence exists"],
        "closeout_authority": {
            "authority_kind": "tests_reports_receipt_checker",
            "evidence_refs": ["tests/test_check_domain_mission_refresh.py", "reports/domain-mission-refresh.final.json"],
        },
        "refresh_policy": "Refresh only impacted authoritative artifacts.",
    }


def _manifest(run_id: str, status: str = "refreshed", waiver_reason: str = "") -> dict[str, object]:
    item: dict[str, object] = {
        "artifact_id": "docs",
        "artifact_class": "doc",
        "path": "docs/GLOBAL_AGENT_WORKFLOW.md",
        "reason": "policy doc touched",
        "status": status,
        "evidence_refs": ["docs/GLOBAL_AGENT_WORKFLOW.md"],
    }
    if waiver_reason:
        item["waiver_reason"] = waiver_reason
    return {
        "schema_version": 1,
        "run_id": run_id,
        "refresh_policy": "impacted_authoritative_artifacts_only",
        "impacted_artifacts": [item],
    }


def _closeout(run_id: str, status: str = "PASS") -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "parent_objective_alignment": "Aligned",
        "updated_artifacts": [],
        "waived_items": [],
        "blocked_items": [],
        "residual_risk": [],
        "authoritative_evidence": ["tests/test_check_domain_mission_refresh.py"],
    }


class DomainMissionRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_l2_missing_mission_frame_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            result = self.module.evaluate_domain_mission_refresh(workspace, "run-missing", "L2")

        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("MISSION_FRAME.json is missing", result["blockers"])

    def test_open_stale_authoritative_artifact_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-stale"
            run_root = workspace / ".agent-runs" / run_id
            _write_json(run_root / "MISSION_FRAME.json", _mission_frame(run_id))
            _write_json(run_root / "ARTIFACT_REFRESH_MANIFEST.json", _manifest(run_id, "pending_refresh"))
            _write_json(run_root / "MISSION_CLOSEOUT.json", _closeout(run_id, "PASS"))

            result = self.module.evaluate_domain_mission_refresh(workspace, run_id, "L2")

        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("artifact refresh remains open" in reason for reason in result["blockers"]))

    def test_refreshed_or_waived_impacted_artifacts_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-pass"
            run_root = workspace / ".agent-runs" / run_id
            manifest = _manifest(run_id, "waived", "Temporary fixture has no published doc to refresh.")
            _write_json(run_root / "MISSION_FRAME.json", _mission_frame(run_id))
            _write_json(run_root / "ARTIFACT_REFRESH_MANIFEST.json", manifest)
            _write_json(run_root / "MISSION_CLOSEOUT.json", _closeout(run_id, "PASS"))

            result = self.module.evaluate_domain_mission_refresh(workspace, run_id, "L2")

        self.assertEqual(result["status"], "PASS")

    def test_checker_does_not_require_unlisted_historical_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-not-impacted"
            run_root = workspace / ".agent-runs" / run_id
            manifest = {
                "schema_version": 1,
                "run_id": run_id,
                "refresh_policy": "impacted_authoritative_artifacts_only",
                "impacted_artifacts": [],
            }
            _write_json(run_root / "MISSION_FRAME.json", _mission_frame(run_id))
            _write_json(run_root / "ARTIFACT_REFRESH_MANIFEST.json", manifest)
            _write_json(run_root / "MISSION_CLOSEOUT.json", _closeout(run_id, "PASS"))

            result = self.module.evaluate_domain_mission_refresh(workspace, run_id, "L2")

        self.assertEqual(result["status"], "PASS")

    def test_summary_pass_language_requires_evidence_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-summary"
            run_root = workspace / ".agent-runs" / run_id
            (workspace / "SUMMARY.md").write_text("Verification complete. PASS.\n", encoding="utf-8")
            closeout = _closeout(run_id, "PASS")
            closeout["authoritative_evidence"] = []
            _write_json(run_root / "MISSION_FRAME.json", _mission_frame(run_id))
            _write_json(run_root / "ARTIFACT_REFRESH_MANIFEST.json", _manifest(run_id, "refreshed"))
            _write_json(run_root / "MISSION_CLOSEOUT.json", closeout)

            result = self.module.evaluate_domain_mission_refresh(workspace, run_id, "L2")

        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("SUMMARY.md uses verification/PASS language" in reason for reason in result["blockers"]))

    def test_nonassertive_pass_language_does_not_require_summary_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-nonassertive-summary"
            run_root = workspace / ".agent-runs" / run_id
            (workspace / "SUMMARY.md").write_text("No PASS claim yet. Evidence is pending.\n", encoding="utf-8")
            closeout = _closeout(run_id, "PASS")
            closeout["authoritative_evidence"] = []
            _write_json(run_root / "MISSION_FRAME.json", _mission_frame(run_id))
            _write_json(run_root / "ARTIFACT_REFRESH_MANIFEST.json", _manifest(run_id, "refreshed"))
            _write_json(run_root / "MISSION_CLOSEOUT.json", closeout)

            result = self.module.evaluate_domain_mission_refresh(workspace, run_id, "L2")

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blockers"], [])

    def test_l1_missing_artifacts_warns_without_blocking_lightweight_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            result = self.module.evaluate_domain_mission_refresh(workspace, "run-l1", "L1")

        self.assertEqual(result["status"], "WARN")
        self.assertFalse(result["blockers"])


if __name__ == "__main__":
    unittest.main()
