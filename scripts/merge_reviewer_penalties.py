#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from _scorecard_common import (
    DEFAULT_REVIEW_FILE,
    default_user_review,
    load_json,
    merge_unique,
    normalize_user_review,
    resolve_path,
    save_json,
    user_review_update_authorized,
)

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


def _merge_user_review(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    status = str(incoming.get("status", "")).strip() or str(base.get("status", "")).strip()
    notes = str(incoming.get("notes", "")).strip() or str(base.get("notes", "")).strip()
    penalties = merge_unique(base.get("penalties", []), incoming.get("penalties", []))
    awards = merge_unique(base.get("awards", []), incoming.get("awards", []))
    return {
        "status": status or "PENDING",
        "awards": awards,
        "penalties": penalties,
        "notes": notes,
    }


def _has_nested_user_review_update(payload: dict[str, Any]) -> bool:
    user_review = payload.get("user_review")
    if not isinstance(user_review, dict):
        return False
    return bool(
        user_review.get("awards")
        or user_review.get("penalties")
        or str(user_review.get("notes", "")).strip()
        or str(user_review.get("status", "")).strip()
    )


def _has_direct_user_review_update(payload: dict[str, Any]) -> bool:
    if str(payload.get("reported_by", "")).strip().lower() != "user":
        return False
    return bool(
        payload.get("awards")
        or payload.get("penalties")
        or str(payload.get("notes", "")).strip()
        or str(payload.get("status", "")).strip()
    )


def merge_review_payload(base: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = dict(base)
    warnings: list[str] = []
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
    current_user = normalize_user_review(merged.get("user_review", default_user_review()))
    user_review_authorized = user_review_update_authorized(incoming)
    if user_review and user_review_authorized:
        merged["user_review"] = _merge_user_review(current_user, user_review)
    elif _has_nested_user_review_update(incoming):
        merged["user_review"] = current_user
        warnings.append("ignored user_review update without explicit user approval or task request")
    else:
        merged["user_review"] = current_user

    if str(incoming.get("reported_by", "")).strip().lower() == "user":
        if user_review_authorized:
            merged["user_review"] = _merge_user_review(merged.get("user_review", current_user), incoming)
        elif _has_direct_user_review_update(incoming):
            warnings.append("ignored direct user_review delta without explicit user approval or task request")

    merged["disqualifiers"] = merge_unique(merged.get("disqualifiers", []), incoming.get("disqualifiers", []))
    return merged, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge reviewer penalties and user awards or penalties into the canonical scorecard review file.")
    parser.add_argument("inputs", nargs="*")
    parser.add_argument("--base-file", default=str(DEFAULT_REVIEW_FILE))
    parser.add_argument("--output-file", default=str(DEFAULT_REVIEW_FILE))
    args = parser.parse_args()

    base_path = resolve_path(args.base_file) or Path(args.base_file)
    output_path = resolve_path(args.output_file) or Path(args.output_file)
    merged = load_json(base_path)
    warnings: list[str] = []
    for raw_path in args.inputs:
        payload_path = resolve_path(raw_path) or Path(raw_path)
        merged, incoming_warnings = merge_review_payload(merged, load_json(payload_path))
        warnings.extend(incoming_warnings)

    save_json(output_path, merged)
    print("PASS")
    print(f"- merged review file: {output_path}")
    for warning in warnings:
        print(f"- warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
