from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "export_user_score_summary.py"
COMMON_MODULE_PATH = ROOT / "scripts" / "_scorecard_common.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("export_user_score_summary", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load export_user_score_summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_common_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("_scorecard_common", COMMON_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load _scorecard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExportUserScoreSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.common = _load_common_module()

    def _signed_receipt(
        self,
        *,
        workspace_root: Path,
        run_id: str,
        gate_status: str,
        mode: str,
        profile: str,
    ) -> dict:
        state_path = self.common.gate_receipt_state_path(workspace_root, run_id)
        mirror_path = self.common.gate_receipt_mirror_path(workspace_root, run_id)
        release_mode = mode == "release"
        release_scope_authoritative = release_mode and profile == "L4"
        payload = {
            "schema_version": 2,
            "run_id": run_id,
            "profile": profile,
            "mode": mode,
            "workspace_root_realpath": str(workspace_root),
            "git_root": str(workspace_root),
            "base_commit": "base",
            "head_commit": "head",
            "changed_file_set_hash": "set-hash",
            "changed_file_content_hash": "content-hash",
            "policy_hashes": {"workspace_authority.json": "policy-hash"},
            "script_hashes": {"iaw_closeout.py": "script-hash"},
            "evidence_manifest_hash": "manifest-hash",
            "gate_status": gate_status,
            "scorecard_ref": str(workspace_root / "reports" / "user-scorecard.json"),
            "audit_refs": {},
            "summary_ref": str(workspace_root / "SUMMARY.md"),
            "issued_at": "2026-04-20T00:00:00+00:00",
            "codex_project_id": self.common.project_id(workspace_root),
            "worktree_id": self.common.worktree_id(workspace_root),
            "preflight_reasons": [],
            "step_failures": [],
            "authoritative": True,
            "signature_policy": self.common.gate_receipt_signature_policy(),
            "authority_layer": {
                "kind": "signed_gate_receipt",
                "state_root": str(self.common.gate_receipts_root()),
                "state_path": str(state_path),
                "mirror_path": str(mirror_path),
            },
            "workspace_identity": {
                "workspace_root_realpath": str(workspace_root),
                "git_root": str(workspace_root),
                "codex_project_id": self.common.project_id(workspace_root),
                "worktree_id": self.common.worktree_id(workspace_root),
            },
            "evidence_binding": {
                "changed_files": [],
                "changed_file_count": 0,
                "changed_file_set_hash": "set-hash",
                "changed_file_content_hash": "content-hash",
                "evidence_manifest_hash": "manifest-hash",
                "policy_hashes": {"workspace_authority.json": "policy-hash"},
                "script_hashes": {"iaw_closeout.py": "script-hash"},
            },
            "release_semantics": {
                "scope": "release" if release_mode else "verification",
                "release_mode": release_mode,
                "release_profile_required": "L4",
                "release_scope_authoritative": release_scope_authoritative,
                "release_ready": release_scope_authoritative and gate_status == "PASS",
                "verify_claims_authoritative": True,
            },
        }
        return self.common.signed_payload(payload)

    def test_missing_receipt_downgrades_gate_and_credit_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [{"axis": "completion_score", "requested_points": 24, "source": "clean_room_verify", "reason": "reserved completion credit generated from clean_room_verify PASS evidence"}],
                        "credited_credit": [{"axis": "completion_score", "requested_points": 24, "credited_points": 24, "source": "clean_room_verify", "capped": False, "blocked": False, "block_reason": ""}],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard)]
                with redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: MISSING", output)
        self.assertIn("- requested: clean_room_verify completion_score +24 (reserved completion credit generated from clean_room_verify PASS evidence)", output)
        self.assertIn("- credited: UNVERIFIED pending gate_receipt", output)
        self.assertIn("19. gate 상태: UNVERIFIED", output)
        self.assertIn("22. 최종 판정: UNVERIFIED", output)

    def test_pending_receipt_shows_reserved_clean_room_completion_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [{"axis": "completion_score", "requested_points": 24, "source": "clean_room_verify", "reason": "reserved completion credit generated from clean_room_verify WAIVED evidence"}],
                        "credited_credit": [{"axis": "completion_score", "requested_points": 24, "credited_points": 24, "source": "clean_room_verify", "capped": False, "blocked": False, "block_reason": ""}],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "clean_room_verify": {"status": "WAIVED", "reason": "verify waived"},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard), "--allow-pending-receipt"]
                with redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: PENDING", output)
        self.assertIn("- requested: clean_room_verify completion_score +24 (reserved completion credit generated from clean_room_verify WAIVED evidence)", output)
        self.assertIn("- credited: clean_room_verify completion_score +24 (reserved completion credit generated from clean_room_verify WAIVED evidence)", output)
        self.assertIn("21. Negative Findings: clean_room_verify:waived", output)
        self.assertIn("credit_effect=+24_by_runtime_policy", output)

    def test_iaw_state_home_precedence_for_authoritative_receipt_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_home = root / "codex-home"
            iaw_home = root / "iaw-home"
            workspace = root / "workspace"
            workspace.mkdir(parents=True)
            run_id = "run-iaw-home"
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "workspace_root": str(workspace),
                        "run_id": run_id,
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [],
                        "credited_credit": [],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            env["IAW_STATE_HOME"] = str(iaw_home)
            with patch.dict(os.environ, env, clear=False):
                receipt = self._signed_receipt(workspace_root=workspace.resolve(), run_id=run_id, gate_status="PASS", mode="verify", profile="L2")
                state_receipt = self.common.gate_receipt_state_path(workspace.resolve(), run_id)
            self.assertEqual(state_receipt, iaw_home / "gate-receipts" / workspace.name / f"{run_id}.json")
            state_receipt.parent.mkdir(parents=True, exist_ok=True)
            state_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard), "--receipt-file", str(state_receipt)]
                with patch.dict(os.environ, env, clear=False), redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: PRESENT", output)
        self.assertIn("19. gate 상태: PASS", output)

    def test_signed_receipt_must_come_from_authoritative_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_home = root / "codex-home"
            workspace = root / "workspace"
            workspace.mkdir(parents=True)
            run_id = "run-001"
            mirror_receipt = workspace / ".agent-runs" / run_id / "gate_receipt.json"
            mirror_receipt.parent.mkdir(parents=True, exist_ok=True)
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "workspace_root": str(workspace),
                        "run_id": run_id,
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [],
                        "credited_credit": [],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            argv = sys.argv[:]
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            with patch.dict(os.environ, env, clear=False):
                receipt = self._signed_receipt(workspace_root=workspace.resolve(), run_id=run_id, gate_status="PASS", mode="verify", profile="L2")
            mirror_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard), "--receipt-file", str(mirror_receipt)]
                with patch.dict(os.environ, env, clear=False), redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: MISSING", output)
        self.assertIn("19. gate 상태: UNVERIFIED", output)

    def test_valid_v13_state_receipt_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_home = root / "codex-home"
            workspace = root / "workspace"
            workspace.mkdir(parents=True)
            run_id = "run-002"
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "workspace_root": str(workspace),
                        "run_id": run_id,
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [],
                        "credited_credit": [],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            with patch.dict(os.environ, env, clear=False):
                receipt = self._signed_receipt(workspace_root=workspace.resolve(), run_id=run_id, gate_status="PASS", mode="verify", profile="L2")
                state_receipt = self.common.gate_receipt_state_path(workspace.resolve(), run_id)
            state_receipt.parent.mkdir(parents=True, exist_ok=True)
            state_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard), "--receipt-file", str(state_receipt)]
                with patch.dict(os.environ, env, clear=False), redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: PRESENT", output)
        self.assertIn("19. gate 상태: PASS", output)
        self.assertIn("22. 최종 판정: PASS", output)

    def test_authoritative_summary_surfaces_credit_and_gate_block_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 30},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 82,
                        "reviewer_penalties": {},
                        "requested_credit": [
                            {"axis": "completion_score", "requested_points": 4, "source": "agent_request", "reason": "non-user bonus"},
                            {"axis": "completion_score", "requested_points": 8, "source": "user_approved_review", "reason": "overflow bonus"},
                        ],
                        "credited_credit": [
                            {
                                "axis": "completion_score",
                                "requested_points": 4,
                                "credited_points": 0,
                                "source": "agent_request",
                                "capped": False,
                                "blocked": True,
                                "block_reason": "requested_only_source",
                            },
                            {
                                "axis": "completion_score",
                                "requested_points": 8,
                                "credited_points": 6,
                                "source": "user_approved_review",
                                "capped": True,
                                "blocked": False,
                                "block_reason": "budget_exhausted",
                            },
                        ],
                        "anti_cheat_layer": {
                            "status": "GUARDED",
                            "signal_points": 8,
                            "penalty_points": 8,
                            "guarded_total_score": 82,
                            "decision_summary": {"highest_decision": "penalty", "counts": {"warn": 0, "penalty": 1, "cap": 0, "dq": 0}},
                        },
                        "anti_cheat_signals": [
                            {
                                "code": "excessive_bonus_request",
                                "severity": "medium",
                                "confidence": "high",
                                "decision": "penalty",
                                "detected_by": "compute_user_scorecard.py",
                                "provenance": {},
                                "points": 8,
                                "reason": "user awards on axis 'completion_score' requested 8 points above budget 6",
                                "evidence_ref": "",
                            }
                        ],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "BLOCKED",
                        "gate_reasons": [
                            "review snapshot tried to override the authoritative approved user-review data",
                            "user awards on axis 'completion_score' requested 8 points above budget 6",
                        ],
                        "remaining_manual_close_out": [],
                        "final_decision": "BLOCKED",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = [
                    "export_user_score_summary.py",
                    "--scorecard-file",
                    str(scorecard),
                    "--allow-pending-receipt",
                ]
                with redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("- credited: agent_request completion_score +0/4 blocked=requested_only_source (non-user bonus)", output)
        self.assertIn("- credited: user_approved_review completion_score +6/8 capped=budget_exhausted (overflow bonus)", output)
        self.assertIn("- gate reason: review snapshot tried to override the authoritative approved user-review data", output)
        self.assertIn("- gate reason: user awards on axis 'completion_score' requested 8 points above budget 6", output)


if __name__ == "__main__":
    unittest.main()
