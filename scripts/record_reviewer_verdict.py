#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _scorecard_common import (
    append_jsonl,
    file_hash,
    git_sha,
    project_id,
    reviewer_verdict_dir,
    signed_payload,
    utc_timestamp,
    worktree_id,
)


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_optional_json(path: str) -> list[dict[str, Any]]:
    text = str(path).strip()
    if not text:
        return []
    return json.loads(Path(text).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a signed reviewer verdict to the runtime authority channel.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--status", default="PENDING")
    parser.add_argument("--green", default="false")
    parser.add_argument("--notes", default="")
    parser.add_argument("--input-report", required=True)
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--producer-lane", default="")
    parser.add_argument("--git-sha", default="")
    parser.add_argument("--worktree-id", default="")
    parser.add_argument("--codex-project-id", default="")
    parser.add_argument("--penalties-json", default="")
    parser.add_argument("--disqualifiers-json", default="")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).expanduser().resolve()
    input_report = Path(args.input_report).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve() if str(args.repo_root).strip() else workspace_root

    payload = {
        "version": 1,
        "role": str(args.role).strip(),
        "producer_lane": str(args.producer_lane).strip() or str(args.role).strip(),
        "repo_root": str(repo_root),
        "git_sha": str(args.git_sha).strip() or git_sha(workspace_root),
        "worktree_id": str(args.worktree_id).strip() or worktree_id(workspace_root),
        "codex_project_id": str(args.codex_project_id).strip() or project_id(workspace_root),
        "trace_id": str(args.trace_id).strip(),
        "generated_at": utc_timestamp(),
        "input_report_hash": file_hash(input_report),
        "status": str(args.status).strip().upper() or "PENDING",
        "green": _parse_bool(args.green),
        "penalties": _load_optional_json(args.penalties_json),
        "disqualifiers": _load_optional_json(args.disqualifiers_json),
        "notes": str(args.notes).strip(),
    }
    signed = signed_payload(payload)
    output = reviewer_verdict_dir(workspace_root, payload["trace_id"]) / f"{payload['role']}.jsonl"
    append_jsonl(output, signed)

    print("PASS")
    print(f"- recorded reviewer verdict: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
