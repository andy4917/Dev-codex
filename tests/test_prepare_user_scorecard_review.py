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
GATE = ROOT / "scripts" / "delivery_gate.py"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


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
                    "user_review_update_request": "user requested preserved review input",
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
                        "awards": [],
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

    def test_prepare_ignores_user_review_without_explicit_request_or_approval(self) -> None:
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
                    "user_review": {
                        "status": "APPROVED",
                        "awards": [{"axis": "completion_score", "points": 4, "reason": "unauthorized"}],
                        "penalties": [{"axis": "completion_score", "points": 1, "reason": "unauthorized"}],
                        "notes": "should be ignored",
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
            self.assertEqual(payload["user_review"]["status"], "PENDING")
            self.assertEqual(payload["user_review"]["awards"], [])
            self.assertEqual(payload["user_review"]["penalties"], [])
            self.assertEqual(payload["user_review"]["notes"], "")
            audit = json.loads((workspace / "reports" / "scorecard-authority-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["tamper_events"][0]["category"], "unauthorized_user_review_modification")
            self.assertEqual(audit["tamper_events"][0]["disqualifier_ids"], ["DQ-011"])

    def test_prepare_loads_signed_verdicts_and_ignores_wrong_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / f"{trace_id}.json"
            snapshot_output = tmp / "review-out.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "awards": [], "penalties": [], "notes": ""}})

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

            compute_output = tmp / "scorecard.json"
            compute = subprocess.run(
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
            self.assertNotEqual(compute.returncode, 0, msg=compute.stderr)
            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertEqual(scorecard["anti_cheat_layer"]["status"], "FAIL")
            self.assertEqual(scorecard["anti_cheat_signals"][0]["code"], "reviewer_truth_tamper")
            self.assertTrue(any(item["id"] == "DQ-011" for item in scorecard["disqualifier_result"]["matched_rules"]))

    def test_prepare_merges_workspace_audit_tamper_events_and_applies_legacy_score_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            reports = workspace / "reports"
            _write_json(
                reports / "audit.final.json",
                {
                    "status": "FAIL",
                    "tamper_events": [
                        {
                            "category": "forbidden_feature_flag",
                            "reason": "forbidden feature flag 'use_agent_identity' is still enabled",
                            "path": str(workspace / ".codex" / "config.toml"),
                            "disqualifier_ids": ["DQ-010"],
                            "evidence_refs": [str(workspace / ".codex" / "config.toml")],
                        }
                    ],
                },
            )

            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "awards": [], "penalties": [], "notes": ""}})

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertNotEqual(compute.returncode, 0, msg=compute.stderr)

            audit = json.loads((workspace / "reports" / "scorecard-authority-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["workspace_audit_status"], "FAIL")
            self.assertEqual(audit["tamper_events"][0]["disqualifier_ids"], ["DQ-010"])

            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertEqual(scorecard["disqualifier_result"]["status"], "FAIL")
            self.assertEqual(scorecard["raw_total_score"], 84)
            self.assertEqual(scorecard["capped_total_score"], 56)
            self.assertTrue(
                any(cap["id"] == "legacy_hardcoding_violation" for cap in scorecard["platform_cap"]["active_caps"])
            )

    def test_completion_score_requires_user_awards_for_problem_discovery_and_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(
                base_review,
                {
                    "status": "TEMPLATE",
                    "user_review_update_request": "user requested additional completion awards",
                    "user_review": {
                        "status": "APPROVED",
                        "awards": [
                            {
                                "axis": "completion_score",
                                "points": 3,
                                "reason": "핵심 문제를 발견함",
                                "category": "problem_discovery"
                            },
                            {
                                "axis": "completion_score",
                                "points": 3,
                                "reason": "근본 원인 패치를 적용함",
                                "category": "problem_resolution"
                            }
                        ],
                        "penalties": [],
                        "notes": "user-awarded completion points"
                    }
                },
            )

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertEqual(compute.returncode, 0, msg=compute.stderr)

            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            completion = scorecard["scores"]["completion_score"]
            self.assertEqual(completion["scoring_mode"], "verified_work_plus_user_awards")
            self.assertEqual(completion["base_points"], 0)
            self.assertEqual(completion["derived_award_points"], 24)
            self.assertEqual(completion["requested_user_award_points"], 6)
            self.assertEqual(completion["user_award_points"], 6)
            self.assertEqual(completion["score"], 30)
            self.assertEqual(len(completion["derived_awards"]), 1)
            self.assertEqual(len(completion["awards"]), 2)
            self.assertEqual(scorecard["raw_total_score"], 90)
            self.assertEqual(scorecard["scorecard_schema_version"], 2)
            self.assertEqual(scorecard["gate_order"][0], "disqualifier_check")
            self.assertEqual(scorecard["anti_cheat_layer"]["status"], "PASS")
            self.assertEqual(
                [item["source"] for item in scorecard["requested_credit"]],
                ["user_approved_review", "user_approved_review", "system_derived"],
            )
            self.assertEqual(
                [item["credited_points"] for item in scorecard["credited_credit"]],
                [3, 3, 24],
            )

    def test_completion_score_overbudget_awards_trigger_anti_cheat_penalty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(
                base_review,
                {
                    "status": "TEMPLATE",
                    "user_review_update_request": "user requested aggressive completion award",
                    "user_review": {
                        "status": "APPROVED",
                        "awards": [
                            {
                                "axis": "completion_score",
                                "points": 8,
                                "reason": "문제 해결 기여를 크게 인정함",
                                "category": "problem_resolution"
                            }
                        ],
                        "penalties": [],
                        "notes": "overbudget request"
                    }
                },
            )

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertEqual(compute.returncode, 0, msg=compute.stderr)

            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            completion = scorecard["scores"]["completion_score"]
            self.assertEqual(completion["requested_user_award_points"], 8)
            self.assertEqual(completion["user_award_points"], 6)
            self.assertEqual(completion["score"], 30)
            anti_cheat = scorecard["anti_cheat_layer"]
            self.assertEqual(anti_cheat["status"], "GUARDED")
            self.assertEqual(anti_cheat["signal_points"], 8)
            self.assertEqual(anti_cheat["penalty_points"], 8)
            self.assertEqual(scorecard["guarded_total_score"], 82)
            self.assertEqual(scorecard["capped_total_score"], 82)
            self.assertEqual(
                [signal["id"] for signal in anti_cheat["signals"]],
                ["excessive_bonus_request"],
            )
            self.assertEqual(scorecard["requested_credit"][0]["requested_points"], 8)
            self.assertEqual(scorecard["credited_credit"][0]["credited_points"], 6)
            self.assertTrue(scorecard["credited_credit"][0]["capped"])

    def test_reserved_derived_award_spoof_triggers_reward_hacking_disqualifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(
                base_review,
                {
                    "status": "TEMPLATE",
                    "user_review_update_request": "user attempted spoofed derived award",
                    "user_review": {
                        "status": "APPROVED",
                        "awards": [
                            {
                                "axis": "completion_score",
                                "points": 2,
                                "reason": "검증 가산을 직접 넣으려 함",
                                "category": "verified_work_execution"
                            }
                        ],
                        "penalties": [],
                        "notes": "spoofed derived award"
                    }
                },
            )

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertEqual(compute.returncode, 0, msg=compute.stderr)

            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            completion = scorecard["scores"]["completion_score"]
            self.assertEqual(completion["requested_user_award_points"], 2)
            self.assertEqual(completion["user_award_points"], 0)
            self.assertEqual(completion["score"], 24)
            anti_cheat = scorecard["anti_cheat_layer"]
            self.assertEqual(anti_cheat["status"], "FAIL")
            self.assertEqual(anti_cheat["signal_points"], 16)
            self.assertEqual(anti_cheat["penalty_points"], 16)
            self.assertEqual(scorecard["guarded_total_score"], 68)
            self.assertEqual(scorecard["capped_total_score"], 68)
            self.assertEqual(
                [signal["id"] for signal in anti_cheat["signals"]],
                ["reserved_derived_award_spoofing"],
            )
            self.assertEqual(scorecard["disqualifier_result"]["status"], "FAIL")
            self.assertTrue(
                any(item["id"] == "DQ-011" for item in scorecard["disqualifier_result"]["matched_rules"])
            )

    def test_agent_self_score_attempt_stays_requested_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(
                base_review,
                {
                    "status": "TEMPLATE",
                    "user_review_update_request": "writer tried to self-credit",
                    "user_review": {
                        "status": "APPROVED",
                        "awards": [
                            {
                                "axis": "completion_score",
                                "points": 5,
                                "reason": "self claimed completion",
                                "reported_by": "agent",
                            }
                        ],
                        "penalties": [],
                        "notes": "self score attempt",
                    },
                },
            )

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertIn(compute.returncode, {0, 1, 2}, msg=compute.stderr)
            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "writer_self_score_attempt" for item in scorecard["anti_cheat_signals"]))
            self.assertEqual(scorecard["requested_credit"][0]["source"], "agent_request")
            self.assertEqual(scorecard["requested_credit"][0]["requested_points"], 5)
            self.assertEqual(scorecard["credited_credit"][0]["credited_points"], 0)
            self.assertTrue(scorecard["credited_credit"][0]["blocked"])
            self.assertEqual(scorecard["credited_credit"][0]["block_reason"], "requested_only_source")

    def test_clean_room_verify_waived_still_grants_system_derived_completion_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            _write_json(
                workspace / "reports" / "acceptance-report.json",
                {"status": "WAIVED", "mode": "full", "reason": "verify waived"},
            )
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "awards": [], "penalties": [], "notes": ""}})

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertEqual(compute.returncode, 0, msg=compute.stderr)

            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            completion = scorecard["scores"]["completion_score"]
            self.assertEqual(completion["derived_award_points"], 24)
            self.assertEqual(scorecard["credited_credit"][-1]["source"], "system_derived")
            self.assertEqual(scorecard["credited_credit"][-1]["credited_points"], 24)

    def test_claimed_verification_without_evidence_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            (workspace / "reports" / "acceptance-report.json").unlink()
            _write_json(
                workspace / "reports" / "delivery-gate.json",
                {
                    "status": "PASS",
                    "mode": "verify",
                    "gate_tier": "L2",
                    "reasons": [],
                    "acceptance": {"status": "PASS"},
                },
            )
            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "awards": [], "penalties": [], "notes": ""}})

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)
            audit = json.loads((workspace / "reports" / "scorecard-authority-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["tamper_events"][0]["category"], "claimed_verification_without_evidence")

            compute = subprocess.run(
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
            self.assertIn(compute.returncode, {0, 1, 2}, msg=compute.stderr)
            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertTrue(
                any(item["code"] == "claimed_verification_without_evidence" for item in scorecard["anti_cheat_signals"])
            )

            gate_output = tmp / "gate-scorecard.json"
            gate = subprocess.run(
                [
                    sys.executable,
                    str(GATE),
                    "--review-file",
                    str(snapshot_output),
                    "--output-file",
                    str(gate_output),
                    "--mode",
                    "verify",
                ],
                cwd=ROOT,
                env=self._env(codex_home),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(gate.returncode, 2, msg=gate.stderr)
            gated = json.loads(gate_output.read_text(encoding="utf-8"))
            self.assertEqual(gated["gate_status"], "BLOCKED")

    def test_test_deletion_or_weakening_without_rationale_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            workspace, _trace_id = self._build_workspace(tmp)
            _git(workspace, "init")
            _git(workspace, "config", "user.email", "codex@example.com")
            _git(workspace, "config", "user.name", "Codex")
            _write_text(workspace / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")
            _git(workspace, "add", ".")
            _git(workspace, "commit", "-m", "baseline")
            _write_text(
                workspace / "tests" / "test_sample.py",
                "import pytest\n\n@pytest.mark.skip(reason='temp')\ndef test_ok():\n    assert True\n",
            )

            codex_home = tmp / "codex-home"
            context_output = codex_home / "state" / "scorecard-context" / workspace.name / "trace-verify-001.json"
            snapshot_output = tmp / "review-out.json"
            compute_output = tmp / "scorecard.json"
            base_review = tmp / "base-review.json"
            _write_json(base_review, {"status": "TEMPLATE", "user_review": {"status": "PENDING", "awards": [], "penalties": [], "notes": ""}})

            prepare = subprocess.run(
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
            self.assertEqual(prepare.returncode, 0, msg=prepare.stderr)

            compute = subprocess.run(
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
            self.assertIn(compute.returncode, {0, 1, 2}, msg=compute.stderr)
            scorecard = json.loads(compute_output.read_text(encoding="utf-8"))
            self.assertTrue(
                any(item["code"] == "test_deletion_or_weakening_without_rationale" for item in scorecard["anti_cheat_signals"])
            )


if __name__ == "__main__":
    unittest.main()
