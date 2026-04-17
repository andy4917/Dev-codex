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

    print("9. 사용자 감점 근거:")
    if payload.get("user_penalties"):
        for penalty in payload["user_penalties"]:
            print(f"- user: {penalty['axis']} -{penalty['points']} ({penalty['reason']})")
    else:
        print("- none")

    cap = payload.get("platform_cap", {})
    if cap.get("cap_applied"):
        reasons = ", ".join(str(item.get("reason", "")).strip() for item in cap.get("active_caps", []))
        print(f"10. cap 적용 여부와 이유: applied (limit={cap.get('cap_limit')}) {reasons}".rstrip())
    else:
        print("10. cap 적용 여부와 이유: not applied")

    print(f"11. gate 상태: {payload.get('gate_status', 'UNKNOWN')}")
    manual = payload.get("remaining_manual_close_out", [])
    if manual:
        print(f"12. 남은 manual close-out: {'; '.join(str(item) for item in manual)}")
    else:
        print("12. 남은 manual close-out: none")
    print(f"13. 최종 판정: {payload.get('final_decision', 'UNKNOWN')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
