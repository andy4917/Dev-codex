#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _scorecard_common import DEFAULT_SCORECARD_FILE, load_json, resolve_path


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the ordered user scorecard summary.")
    parser.add_argument("--scorecard-file", default=str(DEFAULT_SCORECARD_FILE))
    args = parser.parse_args()

    scorecard_path = resolve_path(args.scorecard_file) or Path(args.scorecard_file)
    payload = load_json(scorecard_path)

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
        for item in credited_credit:
            reason = requested_reason.get((item.get("axis", ""), item.get("requested_points", 0), item.get("source", "")), "")
            suffix = f" ({reason})" if reason else ""
            if item.get("blocked"):
                print(
                    f"- credited: {item['source']} {item['axis']} +0/{item['requested_points']} blocked={item.get('block_reason', '')}{suffix}"
                )
            elif item.get("capped"):
                print(
                    f"- credited: {item['source']} {item['axis']} +{item['credited_points']}/{item['requested_points']} capped{suffix}"
                )
            else:
                print(f"- credited: {item['source']} {item['axis']} +{item['credited_points']}{suffix}")
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

    print(f"12. gate 상태: {payload.get('gate_status', 'UNKNOWN')}")
    manual = payload.get("remaining_manual_close_out", [])
    if manual:
        print(f"13. 남은 manual close-out: {'; '.join(str(item) for item in manual)}")
    else:
        print("13. 남은 manual close-out: none")
    print(f"14. 최종 판정: {payload.get('final_decision', 'UNKNOWN')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
