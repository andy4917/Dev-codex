from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "compute_user_scorecard.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("compute_user_scorecard_v12", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load compute_user_scorecard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ComputeUserScorecardV12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_claim_phrase_findings_detect_verification_words_without_artifacts(self) -> None:
        findings = self.module._claim_phrase_findings(
            {
                "claim_ledger": {
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "claim_text": "Verified implementation complete.",
                            "claim_kind": "verification",
                            "source_ref": "SUMMARY.md:10",
                            "evidence_refs": [],
                            "verification_refs": [],
                            "status": "SUPPORTED",
                        }
                    ]
                }
            }
        )

        self.assertEqual(findings["verification_word_without_artifact_count"], 1)
        self.assertEqual(findings["verification_word_without_artifact_refs"], ["claim-1"])

    def test_task_tree_blocks_skipped_task_without_rationale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            task_path = tmp / "tasks" / "stage-01" / "task-01.md"
            _write_text(
                task_path,
                """# Task

## Objective
- Example

## Inputs Read
- Example

## Changes Made
- Example

## Claims
- Example

## Evidence Ref
- Example

## Verification
- Example

## Open Questions
- None
""",
            )

            summary = self.module._task_tree_summary(
                {
                    "workorder": {"taste_gate": {"problem_class": "G2_CHECKABLE_EXECUTION"}},
                    "task_tree": {
                        "tasks": [
                            {
                                "task_id": "task-01",
                                "stage_id": "stage-01",
                                "status": "skipped",
                                "objective": "Example",
                                "task_ref": str(task_path),
                                "rationale": "",
                            }
                        ]
                    },
                    "task_markdown_paths": [task_path],
                },
                unsupported_transition_count=0,
            )

        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["skip_without_rationale_count"], 1)

    def test_repeated_verify_requires_two_rounds_unless_waived(self) -> None:
        summary = self.module._repeated_verify_summary(
            {
                "workorder": {"taste_gate": {"problem_class": "G2_CHECKABLE_EXECUTION"}},
                "repeated_verify": {
                    "rounds": [
                        {
                            "round": 1,
                            "status": "PASS",
                            "new_material_findings": 0,
                            "finding_refs": [],
                        }
                    ]
                },
            }
        )

        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["round_count"], 1)

    def test_cross_verification_blocks_unresolved_disagreement(self) -> None:
        summary = self.module._cross_verification_summary(
            {
                "workorder": {"taste_gate": {"problem_class": "G2_CHECKABLE_EXECUTION"}},
                "cross_verification": {
                    "verifiers": [
                        {
                            "claim_id": "claim-1",
                            "scope": "summary",
                            "verifier_id": "v1",
                            "verifier_kind": "independent",
                            "result": "disagree",
                            "evidence_refs": ["claim-1"],
                        }
                    ]
                },
            }
        )

        self.assertEqual(summary["status"], "BLOCKED")
        self.assertEqual(summary["unresolved_disagreement_count"], 1)

    def test_summary_coverage_blocks_missing_negative_findings(self) -> None:
        summary = self.module._summary_coverage_summary(
            {
                "workorder": {"taste_gate": {"problem_class": "G2_CHECKABLE_EXECUTION"}},
                "summary_text": "# Implementation Summary\n\n## Scope\n",
                "summary_coverage": {
                    "summary_claims": [
                        {"claim_id": "claim-1", "summary_ref": "SUMMARY.md:1", "status": "covered", "source_kind": "task"}
                    ],
                    "negative_findings_present": False,
                    "zombie_sections": [],
                },
            }
        )

        self.assertEqual(summary["status"], "BLOCKED")
        self.assertFalse(summary["negative_findings_present"])


if __name__ == "__main__":
    unittest.main()
