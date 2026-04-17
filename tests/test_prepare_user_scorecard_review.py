from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts" / "prepare_user_scorecard_review.py"
RECORD = ROOT / "scripts" / "record_reviewer_verdict.py"
COMPUTE = ROOT / "scripts" / "compute_user_scorecard.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PrepareUserScorecardReviewTests(unittest.TestCase):
    def _build_workspace(self, root: Path) -> tuple[Path, str]:
        workspace = root / "workspace"
        reports = workspace / "reports"
        authority = reports / "authority"
        reports.mkdir(parents=True)
        trace_id = "trace-verify-001"

        _write_json(
            reports / "delivery-gate.json",
            {"status": "PASS", "mode": "verify", "gate_tier": "L2", "reasons": []},
        )
        _write_json(
            reports / "user-readiness.json",
            {"status": "PASS", "overall": "ready", "baseline_stage": "template-ready"},
        )
        _write_json(
            reports / "acceptance-report.json",
            {"status": "PASS", "mode": "full", "results": [{"command": "pytest"}]},
        )
        _write_json(
            reports / "traceability-report.json",
            {"status": "PASS", "summary": "trace ready", "acceptance_count": 1, "traceability_count": 1},
        )
        _write_json(
            reports / "context7-usage.json",
            {"status": "PASS", "entries": [{"query": "Context7 proof"}]},
        )
        _write_json(
            authority / "fresh-evidence.json",
            {
                "version": 1,
                "repo_root": str(workspace),
                "git_sha": "nogit",
                "worktree_id": str(workspace.resolve()),
                "trace_id": trace_id,
                "producer_lane": "verify",
                "generated_at": "2026-04-17T00:00:00+00:00",
                "reports": {},
            },
        )
        return workspace, trace_id

    def _env(self, codex_home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        return env

    def test_prepare_ignores_snapshot_reviewer_truth_without_authoritative_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            base_review = tmp / "base-review.json"
            _write_json(
                base_review,
                {
                    "status": "TEMPLATE",
                    "reviewers": {
                        "skeptic_reviewer": {
                            "status": "APPROVED",
                            "green": True,
                            "penalties": [{"axis": "trust_score", "points": 2, "reason": "manual"}],
                            "notes": "writer-forged",
                        }
                    },
                    "user_review": {
                        "status": "APPROVED",
                        "penalties": [{"axis": "completion_score", "points": 1, "reason": "user"}],
                        "notes": "keep user",
                    },
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE),
                    "--workspace-root",
                    str(workspace),
                    "--mode",
                    "verify",
                    "--base-file",
                    str(base_review),
                    "--context-output-file",
                    str(context_output),
                    "--review-snapshot-output",
                    str(snapshot_output),
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(snapshot_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["workspace_root"], str(workspace))
            self.assertEqual(payload["status"], "READY")
            self.assertEqual(payload["trace_id"], "trace-verify-001")
            self.assertEqual(payload["authoritative_context_path"], str(context_output))
            self.assertTrue(context_output.exists())
            self.assertEqual(payload["reviewers"]["skeptic_reviewer"]["green"], False)
            self.assertEqual(payload["reviewers"]["skeptic_reviewer"]["status"], "PENDING")
            self.assertEqual(payload["reviewers"]["skeptic_reviewer"]["penalties"], [])
            self.assertEqual(
                payload["user_review"]["penalties"],
                [{"axis": "completion_score", "points": 1, "reason": "user"}],
            )

            compute_output = tmp / "scorecard.json"
            compute_result = subprocess.run(
                [
                    sys.executable,
                    str(COMPUTE),
                    "--review-file",
                    str(snapshot_output),
                    "--output-file",
                    str(compute_output),
                    "--mode",
                    "verify",
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(compute_result.returncode, 0, msg=compute_result.stderr)
            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertFalse(scorecard["reviewer_requirements"]["reviewer_green"])
            self.assertIn("skeptic_reviewer", scorecard["reviewer_requirements"]["non_green_required_roles"])

    def test_prepare_loads_signed_verdicts_and_ignores_wrong_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / f"{trace_id}.json"
            snapshot_output = tmp / "review-out.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "penalties": [], "notes": ""}})

            first_prepare = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE),
                    "--workspace-root",
                    str(workspace),
                    "--mode",
                    "verify",
                    "--base-file",
                    str(base_review),
                    "--context-output-file",
                    str(context_output),
                    "--review-snapshot-output",
                    str(snapshot_output),
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(first_prepare.returncode, 0, msg=first_prepare.stderr)

            good = subprocess.run(
                [
                    sys.executable,
                    str(RECORD),
                    "--workspace-root",
                    str(workspace),
                    "--trace-id",
                    trace_id,
                    "--role",
                    "skeptic_reviewer",
                    "--status",
                    "APPROVED",
                    "--green",
                    "true",
                    "--input-report",
                    str(context_output),
                    "--notes",
                    "valid",
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(good.returncode, 0, msg=good.stderr)

            bad = subprocess.run(
                [
                    sys.executable,
                    str(RECORD),
                    "--workspace-root",
                    str(workspace),
                    "--trace-id",
                    trace_id,
                    "--role",
                    "correctness_verifier",
                    "--status",
                    "APPROVED",
                    "--green",
                    "true",
                    "--input-report",
                    str(context_output),
                    "--repo-root",
                    str(tmp / "other-workspace"),
                    "--notes",
                    "wrong provenance",
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(bad.returncode, 0, msg=bad.stderr)

            second_prepare = subprocess.run(
                [
                    sys.executable,
                    str(PREPARE),
                    "--workspace-root",
                    str(workspace),
                    "--mode",
                    "verify",
                    "--base-file",
                    str(base_review),
                    "--context-output-file",
                    str(context_output),
                    "--review-snapshot-output",
                    str(snapshot_output),
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(second_prepare.returncode, 0, msg=second_prepare.stderr)
            payload = json.loads(snapshot_output.read_text(encoding="utf-8"))
            self.assertTrue(payload["reviewers"]["skeptic_reviewer"]["green"])
            self.assertEqual(payload["reviewers"]["skeptic_reviewer"]["status"], "APPROVED")
            self.assertFalse(payload["reviewers"]["correctness_verifier"]["green"])
            audit = json.loads((workspace / "reports" / "scorecard-authority-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["valid_verdict_roles"], ["skeptic_reviewer"])
            self.assertEqual(audit["ignored_entries"][0]["role"], "correctness_verifier")
            self.assertIn("repo_root", audit["ignored_entries"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
