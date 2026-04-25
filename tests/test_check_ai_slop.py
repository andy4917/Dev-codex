from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_ai_slop.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_ai_slop", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_ai_slop.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_slop_pass(run_root: Path, run_id: str) -> None:
    _write_json(
        run_root / "SLOP_LEDGER.json",
        {"schema_version": 1, "run_id": run_id, "status": "PASS", "entries": [], "status_summary": {"blockers": 0, "warnings": 0, "fixed": 0}},
    )


def _write_delegation_plan(run_root: Path, run_id: str, mode: str = "read_only_scouts") -> None:
    _write_json(
        run_root / "DELEGATION_PLAN.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "delegation_mode": mode,
            "lead_agent_role": "main_integrator",
            "authorization": {
                "source": "subagent-enabled workflow contract",
                "destructive_actions_require_explicit_user_approval": True,
                "protected_paths_require_main_agent_owner": True,
            },
            "default_model_policy": {
                "read_only_scout": "gpt-5.3-codex-spark",
                "verification_pair": "gpt-5.3-codex-spark",
                "bounded_worker": "inherited",
            },
            "max_subagents": 3,
            "allowed_roles": ["scope_scout", "independent_verifier"],
            "forbidden_actions": ["no evidence-free PASS"],
            "rationale": "test",
            "expected_artifacts": [],
            "evidence_refs": [".agent-runs/run/IDEA_BRIEF.json"],
        },
    )


def _write_delegation_support(run_root: Path, run_id: str, *, mode: str = "read_only_scouts", tasks: list[dict[str, object]] | None = None, results: list[dict[str, object]] | None = None) -> None:
    _write_json(
        run_root / "SUBAGENT_TASKS.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "delegation_mode": mode,
            "tasks": tasks
            if tasks is not None
            else [
                {
                    "task_id": "scope-scout-1",
                    "role": "scope_scout",
                    "model": "gpt-5.3-codex-spark",
                    "sandbox": "read-only",
                    "purpose": "scan",
                    "input_refs": [".agent-runs/run/WORKORDER.json"],
                    "allowed_paths": ["."],
                    "write_scope": [],
                    "forbidden_actions": ["write_files"],
                    "output_contract": "evidence refs",
                    "success_criteria": ["return evidence"],
                }
            ],
        },
    )
    _write_json(
        run_root / "SUBAGENT_RESULTS.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "results": results
            if results is not None
            else [
                {
                    "task_id": "scope-scout-1",
                    "role": "scope_scout",
                    "status": "PASS",
                    "summary": "scout complete",
                    "evidence_refs": [".agent-runs/run/EVIDENCE_MANIFEST.json"],
                    "confidence": "medium",
                }
            ],
            "result_policy": "evidence required",
        },
    )
    _write_json(
        run_root / "INTEGRATION_DECISION_LOG.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "decisions": [
                {
                    "decision_id": "d1",
                    "source_task_id": "scope-scout-1",
                    "decision": "accepted",
                    "rationale": "evidence backed",
                    "evidence_refs": [".agent-runs/run/SUBAGENT_RESULTS.json"],
                }
            ],
            "decision_policy": "main integrates",
        },
    )
    _write_json(
        run_root / "DELEGATION_LEDGER.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": "PASS",
            "token_budget_policy": "spark scouts",
            "idle_waiting_detected": False,
            "conflicts": [],
            "unsupported_claims": [],
        },
    )


class CheckAiSlopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_l2_missing_slop_ledger_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            report = self.module.evaluate_ai_slop(workspace, "run-missing", "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("required run artifact is missing for L2: SLOP_LEDGER.json", report["blockers"])

    def test_l1_missing_slop_ledger_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            report = self.module.evaluate_ai_slop(workspace, "run-missing", "L1")

        self.assertEqual(report["status"], "WARN")
        self.assertIn("required run artifact is missing for L1: SLOP_LEDGER.json", report["warnings"])

    def test_supported_summary_with_evidence_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_root = workspace / ".agent-runs" / "run-pass"
            _write_json(run_root / "SLOP_LEDGER.json", {"schema_version": 1, "run_id": "run-pass", "status": "PASS", "entries": [], "status_summary": {"blockers": 0, "warnings": 0, "fixed": 0}})
            _write_json(
                run_root / "CLAIM_LEDGER.json",
                {
                    "schema_version": 1,
                    "run_id": "run-pass",
                    "claims": [
                        {
                            "claim_id": "c1",
                            "claim_text": "Verification complete",
                            "claim_kind": "verification",
                            "source_ref": "SUMMARY.md",
                            "status": "SUPPORTED",
                            "evidence_refs": [".agent-runs/run-pass/EVIDENCE_MANIFEST.json"],
                        }
                    ],
                },
            )
            _write_json(run_root / "SUMMARY_COVERAGE.json", {"schema_version": 1, "run_id": "run-pass", "summary_claims": [{"claim_id": "c1", "summary_ref": "SUMMARY.md", "status": "covered"}], "negative_findings_present": True})
            (workspace / "SUMMARY.md").write_text("Verification complete. evidence_ref: .agent-runs/run-pass/EVIDENCE_MANIFEST.json\n", encoding="utf-8")

            report = self.module.evaluate_ai_slop(workspace, "run-pass", "L2")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["blockers"], [])

    def test_nonassertive_pass_language_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-nonassertive"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            (workspace / "SUMMARY.md").write_text("No PASS claim yet. Evidence is pending.\n", encoding="utf-8")

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["blockers"], [])

    def test_assertive_pass_language_without_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-assertive"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            (workspace / "SUMMARY.md").write_text("Verification complete. PASS.\n", encoding="utf-8")

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("SUMMARY.md uses verification/PASS language without evidence mapping", report["blockers"])

    def test_open_blocking_entries_and_discoverable_questions_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_root = workspace / ".agent-runs" / "run-block"
            _write_json(
                run_root / "SLOP_LEDGER.json",
                {
                    "schema_version": 1,
                    "run_id": "run-block",
                    "status": "BLOCKED",
                    "entries": [
                        {
                            "entry_id": "s1",
                            "issue_type": "unsupported_claim",
                            "severity": "block",
                            "status": "open",
                            "claim": "PASS was claimed without evidence.",
                            "evidence_refs": ["SUMMARY.md"],
                            "resolution": "",
                        }
                    ],
                    "status_summary": {"blockers": 1, "warnings": 0, "fixed": 0},
                },
            )
            _write_json(
                run_root / "QUESTION_QUEUE.json",
                {
                    "schema_version": 1,
                    "run_id": "run-block",
                    "max_questions": 3,
                    "questions": [
                        {
                            "question_id": "q1",
                            "category": "product_intent",
                            "question": "Which package manager does this repo use?",
                            "decision_changed_by_answer": "test command",
                            "default_if_unanswered": "discover from repo",
                            "required_before_implementation": False,
                        }
                    ],
                    "question_policy": "high impact only",
                },
            )

            report = self.module.evaluate_ai_slop(workspace, "run-block", "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("open blocking AI slop entry" in reason for reason in report["blockers"]))
        self.assertIn("QUESTION_QUEUE.json asks a repo-discoverable fact", report["blockers"])

    def test_active_delegation_missing_subagent_results_blocks_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-delegated"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            _write_delegation_plan(run_root, run_id)
            _write_delegation_support(run_root, run_id)
            (run_root / "SUBAGENT_RESULTS.json").unlink()

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("required delegation artifact is missing for active delegation: SUBAGENT_RESULTS.json", report["blockers"])

    def test_narrow_patch_without_delegation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-narrow"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            _write_json(run_root / "WORKORDER.json", {"schema_version": 1, "run_id": run_id, "delegation_mode": "none"})

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["blockers"], [])

    def test_overlapping_bounded_worker_write_scope_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-overlap"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            _write_delegation_plan(run_root, run_id, mode="bounded_workers")
            tasks = [
                {
                    "task_id": "worker-1",
                    "role": "bounded_worker",
                    "model": "inherited",
                    "sandbox": "workspace-write",
                    "purpose": "edit",
                    "input_refs": [],
                    "allowed_paths": ["."],
                    "write_scope": ["src/app.py"],
                    "forbidden_actions": [],
                    "output_contract": "evidence",
                    "success_criteria": ["scoped"],
                },
                {
                    "task_id": "worker-2",
                    "role": "bounded_worker",
                    "model": "inherited",
                    "sandbox": "workspace-write",
                    "purpose": "edit",
                    "input_refs": [],
                    "allowed_paths": ["."],
                    "write_scope": ["src/app.py"],
                    "forbidden_actions": [],
                    "output_contract": "evidence",
                    "success_criteria": ["scoped"],
                },
            ]
            _write_delegation_support(run_root, run_id, mode="bounded_workers", tasks=tasks)

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("overlapping subagent write ownership: src/app.py", report["blockers"])

    def test_verification_subagent_partial_pass_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            run_id = "run-partial-verifier"
            run_root = workspace / ".agent-runs" / run_id
            _write_slop_pass(run_root, run_id)
            _write_delegation_plan(run_root, run_id, mode="verification_pair")
            results = [
                {
                    "task_id": "independent-verifier-1",
                    "role": "independent_verifier",
                    "status": "PASS",
                    "summary": "one targeted test passed",
                    "evidence_refs": [".agent-runs/run/COMMAND_LOG.jsonl"],
                    "confidence": "medium",
                    "verification_scope": "partial",
                    "ran_full_suite": False,
                }
            ]
            _write_delegation_support(run_root, run_id, mode="verification_pair", results=results)

            report = self.module.evaluate_ai_slop(workspace, run_id, "L2")

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("verification subagent marked PASS after partial verification: independent-verifier-1", report["blockers"])


if __name__ == "__main__":
    unittest.main()
