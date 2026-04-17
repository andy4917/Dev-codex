#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_DISQUALIFIER_FILE,
    DEFAULT_REVIEW_FILE,
    load_json,
    normalize_status,
    resolve_path,
    save_json,
    status_exit_code,
    utc_timestamp,
)


def evaluate_disqualifiers(policy: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    rules = {str(item.get("id", "")).strip(): item for item in policy.get("rules", [])}
    observed = list(review.get("disqualifiers", []))
    audit_path = resolve_path(review.get("authority_audit_path", ""), resolve_path(review.get("workspace_root", "")))
    if audit_path is not None and audit_path.exists():
        audit = load_json(audit_path)
        for event in audit.get("tamper_events", []):
            for rule_id in event.get("disqualifier_ids", []):
                observed.append(
                    {
                        "id": rule_id,
                        "reason": str(event.get("reason", "")).strip() or str(event.get("category", "")).strip(),
                        "evidence_refs": [str(audit_path), str(event.get("path", "")).strip()],
                    }
                )
    matched_rules: list[dict[str, Any]] = []
    unknown_ids: list[str] = []
    reasons: list[str] = []
    status = "PASS"

    for entry in observed:
        rule_id = str(entry.get("id", "")).strip()
        if not rule_id or rule_id not in rules:
            unknown_ids.append(rule_id or "<missing>")
            continue

        rule = rules[rule_id]
        rule_outcome = normalize_status(rule.get("outcome"), "FAIL")
        if rule_outcome == "SECURITY_INCIDENT":
            status = "SECURITY_INCIDENT"
        elif status == "PASS":
            status = "FAIL"

        matched = {
            "id": rule_id,
            "title": rule.get("title", ""),
            "outcome": rule_outcome,
            "reason": str(entry.get("reason", "")).strip() or str(rule.get("description", "")).strip(),
            "evidence_refs": entry.get("evidence_refs", []),
        }
        matched_rules.append(matched)
        reasons.append(matched["reason"])

    if unknown_ids and status == "PASS":
        status = "BLOCKED"
    if unknown_ids:
        reasons.append(f"unknown disqualifier ids: {', '.join(unknown_ids)}")

    if not reasons and status == "PASS":
        reasons.append("no disqualifiers recorded")

    return {
        "status": status,
        "matched_rules": matched_rules,
        "unknown_ids": unknown_ids,
        "reasons": reasons,
        "generated_at": utc_timestamp(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Codex global disqualifiers.")
    parser.add_argument("--policy-file", default=str(DEFAULT_DISQUALIFIER_FILE))
    parser.add_argument("--review-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-report", default="")
    args = parser.parse_args()

    policy_path = resolve_path(args.policy_file) or Path(args.policy_file)
    review_path = resolve_path(args.review_file) or Path(args.review_file)
    result = evaluate_disqualifiers(load_json(policy_path), load_json(review_path))

    output_path = resolve_path(args.output_report)
    if output_path is not None:
        save_json(output_path, result)

    print(result["status"])
    for reason in result["reasons"]:
        print(f"- {reason}")
    return status_exit_code(result["status"])


if __name__ == "__main__":
    raise SystemExit(main())
