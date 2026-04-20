#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _scorecard_common import DEFAULT_SCORECARD_FILE, gate_receipt_state_path, load_json, resolve_path, validate_gate_receipt


def _axis_score(payload: dict, key: str) -> str:
    axis = payload.get("scores", {}).get(key, {})
    if not axis.get("applicable", False):
        return "N/A"
    return str(axis.get("score", ""))


def _anti_cheat_signals(payload: dict) -> list[dict]:
    signals = payload.get("anti_cheat_signals", [])
    if signals:
        return signals
    fallback = []
    for signal in payload.get("anti_cheat_layer", {}).get("signals", []):
        fallback.append(
            {
                "code": signal.get("code", signal.get("id", "")),
                "severity": signal.get("severity", "medium"),
                "confidence": signal.get("confidence", "medium"),
                "decision": signal.get("decision", "warn"),
                "detected_by": signal.get("detected_by", "compute_user_scorecard.py"),
                "provenance": signal.get("provenance", {}),
                "points": signal.get("points", 0),
                "reason": signal.get("reason", ""),
                "evidence_ref": signal.get("evidence_ref", ""),
            }
        )
    return fallback


def _stage_line(payload: dict, key: str, default: str = "UNKNOWN") -> str:
    stage = payload.get(key, {})
    if not isinstance(stage, dict):
        return default
    status = str(stage.get("status", default)).strip() or default
    reason = str(stage.get("reason", "")).strip()
    if reason:
        return f"{status} ({reason})"
    return status


def _credit_outcome_label(item: dict) -> str:
    block_reason = str(item.get("block_reason", "")).strip()
    if item.get("blocked"):
        return f"blocked={block_reason}" if block_reason else "blocked"
    if item.get("capped"):
        return f"capped={block_reason}" if block_reason else "capped"
    return ""


def _authoritative_receipt(payload: dict, receipt_file: str) -> dict:
    workspace_root = resolve_path(str(payload.get("workspace_root", "")))
    run_id = str(payload.get("run_id", "")).strip()
    candidate = resolve_path(receipt_file) if receipt_file else None
    if candidate is None and workspace_root is not None and run_id:
        candidate = gate_receipt_state_path(workspace_root, run_id)
    if candidate is None or not candidate.exists():
        return {}
    receipt = load_json(candidate, default={})
    verdict = validate_gate_receipt(
        receipt,
        receipt_path=candidate,
        workspace_root=workspace_root,
        run_id=run_id,
    )
    if not verdict["ok"]:
        return {}
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the ordered user scorecard summary.")
    parser.add_argument("--scorecard-file", default=str(DEFAULT_SCORECARD_FILE))
    parser.add_argument("--receipt-file", default="")
    parser.add_argument("--allow-pending-receipt", action="store_true")
    args = parser.parse_args()

    scorecard_path = resolve_path(args.scorecard_file) or Path(args.scorecard_file)
    payload = load_json(scorecard_path)
    receipt = _authoritative_receipt(payload, str(args.receipt_file).strip())
    authoritative = bool(receipt) or bool(args.allow_pending_receipt)
    receipt_status = "PRESENT" if receipt else ("PENDING" if args.allow_pending_receipt else "MISSING")

    print(f"0. authoritative receipt: {receipt_status}")

    print(f"1. disqualifier 결과: {payload.get('disqualifier_result', {}).get('status', 'UNKNOWN')}")
    print(f"2. trust_score: {_axis_score(payload, 'trust_score')}")
    print(f"3. completion_score: {_axis_score(payload, 'completion_score')}")
    print(f"4. compliance_score: {_axis_score(payload, 'compliance_score')}")
    print(f"5. reliability_score: {_axis_score(payload, 'reliability_score')}")
    print(f"6. search_evidence_score: {_axis_score(payload, 'search_evidence_score')}")
    print(f"7. total_score: {payload.get('capped_total_score', payload.get('raw_total_score', ''))}")

    print("8. reviewer별 감점 근거:")
    for role, penalties in payload.get("reviewer_penalties", {}).items():
        if penalties:
            for penalty in penalties:
                print(f"- {role}: {penalty['axis']} -{penalty['points']} ({penalty['reason']})")
        else:
            print(f"- {role}: none")

    print("9. requested/credited credit:")
    requested_credit = payload.get("requested_credit", [])
    credited_credit = payload.get("credited_credit", [])
    requested_reason = {
        (item.get("axis", ""), item.get("requested_points", 0), item.get("source", "")): item.get("reason", "")
        for item in requested_credit
    }
    if requested_credit:
        for item in requested_credit:
            print(f"- requested: {item['source']} {item['axis']} +{item['requested_points']} ({item['reason']})")
    if credited_credit:
        if authoritative:
            for item in credited_credit:
                reason = requested_reason.get((item.get("axis", ""), item.get("requested_points", 0), item.get("source", "")), "")
                suffix = f" ({reason})" if reason else ""
                outcome = _credit_outcome_label(item)
                if outcome:
                    print(
                        f"- credited: {item['source']} {item['axis']} +{item['credited_points']}/{item['requested_points']} {outcome}{suffix}"
                    )
                else:
                    print(f"- credited: {item['source']} {item['axis']} +{item['credited_points']}{suffix}")
        else:
            print("- credited: UNVERIFIED pending gate_receipt")
    if payload.get("user_penalties"):
        for penalty in payload["user_penalties"]:
            print(f"- penalty: user {penalty['axis']} -{penalty['points']} ({penalty['reason']})")
    if not requested_credit and not credited_credit and not payload.get("user_penalties"):
        print("- none")

    anti_cheat = payload.get("anti_cheat_layer", {})
    decision_summary = anti_cheat.get("decision_summary", {})
    print(
        f"10. anti-cheat guard: {anti_cheat.get('status', 'UNKNOWN')} "
        f"(signals={anti_cheat.get('signal_points', 0)}, penalty={anti_cheat.get('penalty_points', 0)}, guarded_total={anti_cheat.get('guarded_total_score', payload.get('raw_total_score', ''))})"
    )
    print(
        f"- decision summary: highest={decision_summary.get('highest_decision', 'warn')} "
        f"counts={decision_summary.get('counts', {})}"
    )
    for signal in _anti_cheat_signals(payload):
        print(
            f"- signal: {signal['code']} decision={signal.get('decision', 'warn')} "
            f"confidence={signal.get('confidence', 'medium')} +{signal['points']} ({signal['reason']})"
        )

    cap = payload.get("platform_cap", {})
    if cap.get("cap_applied"):
        reasons = ", ".join(str(item.get("reason", "")).strip() for item in cap.get("active_caps", []))
        print(f"11. cap 적용 여부와 이유: applied (limit={cap.get('cap_limit')}) {reasons}".rstrip())
    else:
        print("11. cap 적용 여부와 이유: not applied")

    print(f"12. taste gate: {_stage_line(payload, 'taste_gate')}")
    print(f"13. task tree: {_stage_line(payload, 'task_tree')}")
    print(f"14. evidence manifest: {_stage_line(payload, 'evidence_manifest')}")
    print(f"15. repeated verify: {_stage_line(payload, 'repeated_verify')}")
    print(f"16. cross verification: {_stage_line(payload, 'cross_verification')}")
    print(f"17. convention lock: {_stage_line(payload, 'convention_lock')}")
    print(f"18. summary coverage: {_stage_line(payload, 'summary_coverage')}")
    cross = payload.get("cross_verification", {})
    if isinstance(cross, dict) and cross.get("disagreement_refs"):
        print(f"- unresolved disagreement refs: {', '.join(str(item) for item in cross.get('disagreement_refs', []))}")
    summary_coverage = payload.get("summary_coverage", {})
    if isinstance(summary_coverage, dict):
        print(
            f"- negative findings present: {summary_coverage.get('negative_findings_present', False)} "
            f"uncovered_claims={summary_coverage.get('uncovered_claim_count', 0)} "
            f"zombie_sections={summary_coverage.get('zombie_section_count', 0)}"
        )

    print(f"19. gate 상태: {payload.get('gate_status', 'UNKNOWN') if authoritative else 'UNVERIFIED'}")
    if authoritative:
        for reason in payload.get("gate_reasons", []):
            text = str(reason).strip()
            if text:
                print(f"- gate reason: {text}")
    manual = payload.get("remaining_manual_close_out", [])
    if manual:
        print(f"20. 남은 manual close-out: {'; '.join(str(item) for item in manual)}")
    else:
        print("20. 남은 manual close-out: none")

    negative_findings: list[str] = []
    for signal in _anti_cheat_signals(payload):
        decision = str(signal.get("decision", "warn")).strip().lower() or "warn"
        if decision in {"penalty", "cap", "dq"}:
            negative_findings.append(f"{signal['code']}:{decision}")
    evidence_manifest = payload.get("evidence_manifest", {})
    if isinstance(evidence_manifest, dict) and evidence_manifest.get("status") == "WAIVED":
        negative_findings.append("evidence_manifest:waived")
    repeated_verify = payload.get("repeated_verify", {})
    if isinstance(repeated_verify, dict) and repeated_verify.get("status") == "WAIVED":
        negative_findings.append("repeated_verify:waived")
    clean_room_verify = payload.get("clean_room_verify", {})
    if isinstance(clean_room_verify, dict) and str(clean_room_verify.get("status", "")).strip().upper() == "WAIVED":
        negative_findings.append("clean_room_verify:waived")
    if manual:
        negative_findings.append("manual_close_out:open")
    if isinstance(cross, dict) and int(cross.get("unresolved_disagreement_count", 0)) > 0:
        negative_findings.append("cross_verification:unresolved")
    if negative_findings:
        print(f"21. Negative Findings: {', '.join(negative_findings)}")
        if "clean_room_verify:waived" in negative_findings:
            print("- clean_room_verify:waived credit_effect=+24_by_runtime_policy readiness_effect=gate_policy_dependent note=WAIVED_remains_disclosed_and_is_not_PASS")
    else:
        print("21. Negative Findings: none")
    print(f"22. 최종 판정: {payload.get('final_decision', 'UNKNOWN') if authoritative else 'UNVERIFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
