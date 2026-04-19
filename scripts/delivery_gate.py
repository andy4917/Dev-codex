#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import DEFAULT_POLICY_FILE, DEFAULT_REVIEW_FILE, DEFAULT_SCORECARD_FILE, load_json, normalize_status, resolve_path, save_json, status_exit_code
from compute_user_scorecard import compute_scorecard


def _stage_gate_status(stage: dict[str, Any]) -> tuple[str, list[str]]:
    status = normalize_status(stage.get("status"), "UNKNOWN")
    reasons: list[str] = []
    reason = str(stage.get("reason", "")).strip()
    if reason:
        reasons.append(reason)
    if status in {"PASS", "WAIVED"} and not stage.get("manual_close_out"):
        return "PASS", reasons
    if stage.get("manual_close_out"):
        reasons.extend(str(item).strip() for item in stage.get("manual_close_out", []) if str(item).strip())
        return "BLOCKED", reasons
    if status in {"FAIL", "SECURITY_INCIDENT"}:
        return "FAIL", reasons or [f"stage status is {status}"]
    return "BLOCKED", reasons or [f"stage status is {status}"]


def _normalized_gate_steps(gate_checks: dict[str, Any]) -> list[str]:
    steps: list[str] = []
    for key in gate_checks:
        text = str(key).strip()
        if text and text[0].isdigit() and "_" in text:
            steps.append(text.split("_", 1)[1])
        else:
            steps.append(text)
    return steps


def _append_gate_order_signal(scorecard: dict[str, Any], gate_checks: dict[str, Any]) -> None:
    expected = list(scorecard.get("gate_order", []))
    emitted = _normalized_gate_steps(gate_checks)
    if not expected or emitted == expected:
        return
    signal = {
        "id": "gate_order_drift",
        "code": "gate_order_drift",
        "severity": "high",
        "confidence": "high",
        "decision": "cap",
        "detected_by": "delivery_gate.py",
        "provenance": {
            "source_file": str(DEFAULT_POLICY_FILE),
            "source_hash": "",
            "base_commit": "",
            "head_commit": "",
        },
        "points": 20,
        "reason": "delivery gate emitted checks in an order that does not match the canonical policy order",
        "evidence_refs": [str(DEFAULT_POLICY_FILE)],
        "evidence_ref": str(DEFAULT_POLICY_FILE),
        "details": {"expected": expected, "emitted": emitted},
    }
    scorecard.setdefault("anti_cheat_signals", []).append(
        {
            "code": signal["code"],
            "severity": signal["severity"],
            "confidence": signal["confidence"],
            "decision": signal["decision"],
            "detected_by": signal["detected_by"],
            "provenance": signal["provenance"],
            "points": signal["points"],
            "reason": signal["reason"],
            "evidence_ref": signal["evidence_ref"],
        }
    )
    anti_cheat = scorecard.setdefault("anti_cheat_layer", {})
    anti_cheat.setdefault("signals", []).append(signal)
    summary = anti_cheat.setdefault(
        "decision_summary",
        {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}, "auto_dq_signals": []},
    )
    counts = summary.setdefault("counts", {"warn": 0, "penalty": 0, "cap": 0, "dq": 0})
    counts["cap"] = int(counts.get("cap", 0)) + 1
    if summary.get("highest_decision") != "dq":
        summary["highest_decision"] = "cap"
    if anti_cheat.get("status") != "FAIL":
        anti_cheat["status"] = "GUARDED"


def _summary_gate_status(summary: dict[str, Any]) -> tuple[str, list[str]]:
    status = normalize_status(summary.get("status"), "UNKNOWN")
    reasons: list[str] = []
    reason = str(summary.get("reason", "")).strip()
    if reason:
        reasons.append(reason)
    if status in {"PASS", "WAIVED"}:
        return "PASS", reasons
    if status in {"FAIL", "SECURITY_INCIDENT"}:
        return "FAIL", reasons or [f"summary stage status is {status}"]
    return "BLOCKED", reasons or [f"summary stage status is {status}"]


def run_delivery_gate(review: dict[str, Any], mode: str) -> dict[str, Any]:
    scorecard = compute_scorecard(load_json(DEFAULT_POLICY_FILE), review, mode)
    disqualifier = scorecard["disqualifier_result"]

    gate_checks = {
        "1_disqualifier_check": {
            "status": normalize_status(disqualifier.get("status"), "PASS"),
            "reasons": disqualifier.get("reasons", []),
        }
    }

    gate_status = "PASS"
    gate_failure_step = ""
    gate_reasons: list[str] = []

    def first_failure(status: str, step: str, reasons: list[str]) -> None:
        nonlocal gate_status, gate_failure_step, gate_reasons
        if gate_failure_step:
            return
        gate_status = status
        gate_failure_step = step
        gate_reasons = reasons

    disqualifier_status = normalize_status(disqualifier.get("status"), "PASS")
    if disqualifier_status == "SECURITY_INCIDENT":
        first_failure("FAIL", "1_disqualifier_check", disqualifier.get("reasons", []))
    elif disqualifier_status == "FAIL":
        first_failure("FAIL", "1_disqualifier_check", disqualifier.get("reasons", []))
    elif disqualifier_status == "BLOCKED":
        first_failure("BLOCKED", "1_disqualifier_check", disqualifier.get("reasons", []))

    if mode == "quick" and not gate_failure_step:
        gate_checks["2_quick_mode_score_gate"] = {
            "status": "WAIVED",
            "reasons": ["quick mode enforces only disqualifier checks; score, floors, and caps are advisory"],
        }
        gate_status = "WAIVED"
    else:
        reviewer_payload = scorecard["reviewer_requirements"]
        reviewer_reasons = [
            *[f"missing reviewer: {role}" for role in reviewer_payload["missing_required_roles"]],
            *[f"reviewer not green: {role}" for role in reviewer_payload["non_green_required_roles"]],
            *scorecard["errors"],
        ]
        reviewer_status = "PASS" if reviewer_payload["reviewer_green"] and not scorecard["errors"] else "BLOCKED"
        gate_checks["2_reviewer_green_check"] = {"status": reviewer_status, "reasons": reviewer_reasons}
        if reviewer_status != "PASS":
            first_failure("BLOCKED", "2_reviewer_green_check", reviewer_reasons)

        trace = scorecard["trace"]
        trace_reasons: list[str] = []
        if trace.get("required", True) and not trace.get("present", False):
            trace_reasons.append("trace is missing, so score is invalid")
        trace_status = "PASS" if not trace_reasons else "BLOCKED"
        gate_checks["3_trace_presence_check"] = {"status": trace_status, "reasons": trace_reasons}
        if trace_status != "PASS":
            first_failure("BLOCKED", "3_trace_presence_check", trace_reasons)

        taste_gate_status, taste_gate_reasons = _summary_gate_status(scorecard.get("taste_gate", {}))
        gate_checks["4_taste_gate_check"] = {"status": taste_gate_status, "reasons": taste_gate_reasons}
        if taste_gate_status != "PASS":
            first_failure("FAIL" if taste_gate_status == "FAIL" else "BLOCKED", "4_taste_gate_check", taste_gate_reasons)

        task_tree_status, task_tree_reasons = _summary_gate_status(scorecard.get("task_tree", {}))
        gate_checks["5_task_tree_check"] = {"status": task_tree_status, "reasons": task_tree_reasons}
        if task_tree_status != "PASS":
            first_failure("FAIL" if task_tree_status == "FAIL" else "BLOCKED", "5_task_tree_check", task_tree_reasons)

        evidence_manifest_status, evidence_manifest_reasons = _summary_gate_status(scorecard.get("evidence_manifest", {}))
        gate_checks["6_evidence_manifest_check"] = {"status": evidence_manifest_status, "reasons": evidence_manifest_reasons}
        if evidence_manifest_status != "PASS":
            first_failure(
                "FAIL" if evidence_manifest_status == "FAIL" else "BLOCKED",
                "6_evidence_manifest_check",
                evidence_manifest_reasons,
            )

        repeated_verify_status, repeated_verify_reasons = _summary_gate_status(scorecard.get("repeated_verify", {}))
        gate_checks["7_repeated_verify_check"] = {"status": repeated_verify_status, "reasons": repeated_verify_reasons}
        if repeated_verify_status != "PASS":
            first_failure(
                "FAIL" if repeated_verify_status == "FAIL" else "BLOCKED",
                "7_repeated_verify_check",
                repeated_verify_reasons,
            )

        cross_verification_status, cross_verification_reasons = _summary_gate_status(scorecard.get("cross_verification", {}))
        gate_checks["8_cross_verification_check"] = {
            "status": cross_verification_status,
            "reasons": cross_verification_reasons,
        }
        if cross_verification_status != "PASS":
            first_failure(
                "FAIL" if cross_verification_status == "FAIL" else "BLOCKED",
                "8_cross_verification_check",
                cross_verification_reasons,
            )

        convention_lock_status, convention_lock_reasons = _summary_gate_status(scorecard.get("convention_lock", {}))
        gate_checks["9_convention_lock_check"] = {"status": convention_lock_status, "reasons": convention_lock_reasons}
        if convention_lock_status != "PASS":
            first_failure(
                "FAIL" if convention_lock_status == "FAIL" else "BLOCKED",
                "9_convention_lock_check",
                convention_lock_reasons,
            )

        summary_coverage_status, summary_coverage_reasons = _summary_gate_status(scorecard.get("summary_coverage", {}))
        gate_checks["10_summary_coverage_check"] = {
            "status": summary_coverage_status,
            "reasons": summary_coverage_reasons,
        }
        if summary_coverage_status != "PASS":
            first_failure(
                "FAIL" if summary_coverage_status == "FAIL" else "BLOCKED",
                "10_summary_coverage_check",
                summary_coverage_reasons,
            )

        axis_floor_reasons = [
            *[f"axis floor failed: {axis}" for axis in scorecard["axis_floor_check"]["failed_axes"] if axis != "total_score"],
        ]
        if not scorecard["axis_floor_check"]["raw_total_passes"]:
            axis_floor_reasons.append(
                f"raw total score {scorecard['raw_total_score']} is below floor {scorecard['total_floor']}"
            )
        axis_floor_status = scorecard["axis_floor_check"]["status"]
        gate_checks["11_axis_floor_check"] = {"status": axis_floor_status, "reasons": axis_floor_reasons}
        if axis_floor_status != "PASS":
            first_failure("BLOCKED", "11_axis_floor_check", axis_floor_reasons)

        anti_cheat = scorecard.get("anti_cheat_layer", {})
        decision_summary = anti_cheat.get("decision_summary", {})
        highest_decision = str(decision_summary.get("highest_decision", "warn")).strip().lower() or "warn"
        anti_cheat_reasons = [str(signal.get("reason", "")).strip() for signal in anti_cheat.get("signals", []) if str(signal.get("reason", "")).strip()]
        anti_cheat_status = "PASS"
        if highest_decision == "dq" or anti_cheat.get("status") == "FAIL":
            anti_cheat_status = "FAIL"
        elif any(
            str(signal.get("code", signal.get("id", ""))).strip()
            in {
                "claimed_verification_without_evidence",
                "evidence_backdating_or_stale_report_reuse",
                "evidence_manifest_mismatch",
                "verification_word_without_artifact",
                "cross_verification_disagreement_unresolved",
                "zombie_section_or_stale_claim",
            }
            for signal in anti_cheat.get("signals", [])
        ):
            anti_cheat_status = "BLOCKED"
        gate_checks["12_anti_cheat_guard_check"] = {"status": anti_cheat_status, "reasons": anti_cheat_reasons}
        if anti_cheat_status != "PASS":
            first_failure("FAIL" if anti_cheat_status == "FAIL" else "BLOCKED", "12_anti_cheat_guard_check", anti_cheat_reasons)

        cap_reasons: list[str] = []
        if scorecard["platform_cap"]["cap_applied"]:
            for cap in scorecard["platform_cap"]["active_caps"]:
                cap_reasons.append(str(cap.get("reason", "")).strip())
        if scorecard["capped_total_score"] < scorecard["total_floor"]:
            cap_reasons.append(
                f"capped total score {scorecard['capped_total_score']} is below floor {scorecard['total_floor']}"
            )
        cap_status = scorecard["platform_cap"]["status"]
        gate_checks["13_platform_cap_check"] = {"status": cap_status, "reasons": cap_reasons}
        if cap_status != "PASS":
            first_failure("BLOCKED", "13_platform_cap_check", cap_reasons)

        readiness_status, readiness_reasons = _stage_gate_status(scorecard["existing_readiness"])
        gate_checks["14_existing_readiness_and_manual_close_out_check"] = {
            "status": readiness_status,
            "reasons": readiness_reasons,
        }
        if readiness_status != "PASS":
            first_failure("FAIL" if readiness_status == "FAIL" else "BLOCKED", "14_existing_readiness_and_manual_close_out_check", readiness_reasons)

        verify_status, verify_reasons = _stage_gate_status(scorecard["clean_room_verify"])
        gate_checks["15_clean_room_verify_check"] = {"status": verify_status, "reasons": verify_reasons}
        if verify_status != "PASS":
            first_failure("FAIL" if verify_status == "FAIL" else "BLOCKED", "15_clean_room_verify_check", verify_reasons)

    _append_gate_order_signal(scorecard, gate_checks)

    remaining_manual_close_out = [
        *scorecard["existing_readiness"].get("manual_close_out", []),
        *scorecard["clean_room_verify"].get("manual_close_out", []),
    ]

    if not gate_failure_step and mode != "quick":
        gate_status = "PASS"

    final_decision = gate_status
    if final_decision not in {"PASS", "FAIL", "BLOCKED", "WAIVED"}:
        final_decision = "FAIL"

    scorecard.update(
        {
            "status": gate_status,
            "gate_checks": gate_checks,
            "gate_status": gate_status,
            "gate_failure_step": gate_failure_step,
            "gate_reasons": gate_reasons,
            "remaining_manual_close_out": remaining_manual_close_out,
            "final_decision": final_decision,
        }
    )
    return scorecard


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex global delivery gate for the user penalty scorecard.")
    parser.add_argument("--mode", choices=["quick", "verify", "release"], default="verify")
    parser.add_argument("--review-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-file", default=str(DEFAULT_SCORECARD_FILE))
    parser.add_argument("--workspace-root", default="")
    args = parser.parse_args()

    review_path = resolve_path(args.review_file) or Path(args.review_file)
    output_path = resolve_path(args.output_file) or Path(args.output_file)
    review = load_json(review_path)
    if args.workspace_root.strip():
        review["workspace_root"] = args.workspace_root.strip()

    result = run_delivery_gate(review, args.mode)
    save_json(output_path, result)

    print(result["gate_status"])
    for reason in result.get("gate_reasons", []):
        print(f"- {reason}")
    return status_exit_code(result["gate_status"])


if __name__ == "__main__":
    raise SystemExit(main())
