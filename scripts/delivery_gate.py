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

        axis_floor_reasons = [
            *[f"axis floor failed: {axis}" for axis in scorecard["axis_floor_check"]["failed_axes"] if axis != "total_score"],
        ]
        if not scorecard["axis_floor_check"]["raw_total_passes"]:
            axis_floor_reasons.append(
                f"raw total score {scorecard['raw_total_score']} is below floor {scorecard['total_floor']}"
            )
        axis_floor_status = scorecard["axis_floor_check"]["status"]
        gate_checks["4_axis_floor_check"] = {"status": axis_floor_status, "reasons": axis_floor_reasons}
        if axis_floor_status != "PASS":
            first_failure("BLOCKED", "4_axis_floor_check", axis_floor_reasons)

        cap_reasons: list[str] = []
        if scorecard["platform_cap"]["cap_applied"]:
            for cap in scorecard["platform_cap"]["active_caps"]:
                cap_reasons.append(str(cap.get("reason", "")).strip())
        if scorecard["capped_total_score"] < scorecard["total_floor"]:
            cap_reasons.append(
                f"capped total score {scorecard['capped_total_score']} is below floor {scorecard['total_floor']}"
            )
        cap_status = scorecard["platform_cap"]["status"]
        gate_checks["5_platform_cap_check"] = {"status": cap_status, "reasons": cap_reasons}
        if cap_status != "PASS":
            first_failure("BLOCKED", "5_platform_cap_check", cap_reasons)

        readiness_status, readiness_reasons = _stage_gate_status(scorecard["existing_readiness"])
        gate_checks["6_existing_readiness_and_manual_close_out_check"] = {
            "status": readiness_status,
            "reasons": readiness_reasons,
        }
        if readiness_status != "PASS":
            first_failure("FAIL" if readiness_status == "FAIL" else "BLOCKED", "6_existing_readiness_and_manual_close_out_check", readiness_reasons)

        verify_status, verify_reasons = _stage_gate_status(scorecard["clean_room_verify"])
        gate_checks["7_clean_room_verify_check"] = {"status": verify_status, "reasons": verify_reasons}
        if verify_status != "PASS":
            first_failure("FAIL" if verify_status == "FAIL" else "BLOCKED", "7_clean_room_verify_check", verify_reasons)

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
