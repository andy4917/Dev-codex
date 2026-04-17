#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import DEFAULT_REVIEW_FILE, load_json, merge_unique, resolve_path, save_json

REVIEWER_ROLES = [
    "skeptic_reviewer",
    "correctness_verifier",
    "contamination_monitor",
    "final_auditor",
]


def _merge_penalty_container(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    status = str(incoming.get("status", "")).strip() or str(base.get("status", "")).strip()
    notes = str(incoming.get("notes", "")).strip() or str(base.get("notes", "")).strip()
    penalties = merge_unique(base.get("penalties", []), incoming.get("penalties", []))
    green = incoming.get("green", base.get("green", False))
    return {
        "status": status or "PENDING",
        "green": bool(green),
        "penalties": penalties,
        "notes": notes,
    }


def merge_review_payload(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key in ("status", "task_id", "workspace_root", "delivery_mode"):
        value = str(incoming.get(key, "")).strip()
        if value:
            merged[key] = value

    for key in ("task_context", "evidence_inputs", "trace", "existing_readiness", "clean_room_verify"):
        source = incoming.get(key, {})
        if isinstance(source, dict):
            current = merged.get(key, {})
            merged[key] = {**current, **source}

    if "reviewers" not in merged:
        merged["reviewers"] = {}
    for role in REVIEWER_ROLES:
        current = merged["reviewers"].get(role, {"status": "PENDING", "green": False, "penalties": [], "notes": ""})
        incoming_role = incoming.get("reviewers", {}).get(role, {})
        if incoming_role:
            merged["reviewers"][role] = _merge_penalty_container(current, incoming_role)
        else:
            merged["reviewers"][role] = current

    reviewer_role = str(incoming.get("reviewer_role", "")).strip()
    if reviewer_role in REVIEWER_ROLES:
        current = merged["reviewers"].get(reviewer_role, {"status": "PENDING", "green": False, "penalties": [], "notes": ""})
        merged["reviewers"][reviewer_role] = _merge_penalty_container(current, incoming)

    user_review = incoming.get("user_review", {})
    current_user = merged.get("user_review", {"status": "PENDING", "penalties": [], "notes": ""})
    if user_review:
        penalties = merge_unique(current_user.get("penalties", []), user_review.get("penalties", []))
        merged["user_review"] = {
            "status": str(user_review.get("status", "")).strip() or str(current_user.get("status", "")).strip() or "PENDING",
            "penalties": penalties,
            "notes": str(user_review.get("notes", "")).strip() or str(current_user.get("notes", "")).strip(),
        }
    else:
        merged["user_review"] = current_user

    if str(incoming.get("reported_by", "")).strip().lower() == "user":
        penalties = merge_unique(current_user.get("penalties", []), incoming.get("penalties", []))
        merged["user_review"] = {
            "status": str(incoming.get("status", "")).strip() or str(current_user.get("status", "")).strip() or "PENDING",
            "penalties": penalties,
            "notes": str(incoming.get("notes", "")).strip() or str(current_user.get("notes", "")).strip(),
        }

    merged["disqualifiers"] = merge_unique(merged.get("disqualifiers", []), incoming.get("disqualifiers", []))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge reviewer and user deductions into the canonical scorecard review file.")
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("--base-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-file", default=str(DEFAULT_REVIEW_FILE))
    args = parser.parse_args()

    base_path = resolve_path(args.base_file) or Path(args.base_file)
    output_path = resolve_path(args.output_file) or Path(args.output_file)
    merged = load_json(base_path)
    for raw_path in args.inputs:
        payload_path = resolve_path(raw_path) or Path(raw_path)
        merged = merge_review_payload(merged, load_json(payload_path))

    save_json(output_path, merged)
    print("PASS")
    print(f"- merged review file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
