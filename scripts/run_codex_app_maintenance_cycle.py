#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "codex-app-maintenance-cycle.final.json"


def run_step(label: str, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    payload: dict[str, Any] = {}
    if result.stdout.strip().startswith("{"):
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
    summary: dict[str, Any] = {"status": payload.get("status", "PASS" if result.returncode == 0 else "WARN")}
    if label == "codex_app_state_maintenance":
        actions = payload.get("actions", {}) if isinstance(payload.get("actions"), dict) else {}
        for name in ("live_threads", "sessions", "desktop_logs", "render_cache", "logs_sqlite"):
            action = actions.get(name, {}) if isinstance(actions.get(name), dict) else {}
            summary[name] = {
                key: action.get(key)
                for key in (
                    "retention_days",
                    "max_session_files",
                    "max_rows",
                    "candidate_count",
                    "candidate_rows",
                    "candidate_mb",
                    "live_threads_before",
                    "live_threads_after",
                    "max_live_threads",
                    "total_files_after",
                    "total_rows_after",
                    "archive_path",
                    "disposal_policy",
                )
                if key in action
            }
    elif label == "windows_app_resource_health":
        summary.update(
            {
                "process_counts": payload.get("process_counts", {}),
                "working_sets": payload.get("working_sets", {}),
                "cpu_samples": payload.get("cpu_samples", {}),
                "warnings": payload.get("warnings", []),
                "blockers": payload.get("blockers", []),
                "cleanup_candidate_summary": payload.get("cleanup_candidate_summary", {}),
            }
        )
    return {
        "label": label,
        "command": args,
        "returncode": result.returncode,
        "status": summary["status"],
        "stdout_tail": result.stdout[-1200:],
        "stderr": result.stderr[-4000:],
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the recurring Codex App maintenance and resource-health cycle.")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--log-retention-days", type=int, default=1)
    parser.add_argument("--max-log-rows", type=int, default=10000)
    parser.add_argument("--max-session-files", type=int, default=60)
    parser.add_argument("--max-live-threads", type=int, default=12)
    parser.add_argument(
        "--resource-cpu-sample-seconds",
        type=int,
        default=3,
        help="Seconds to sample Codex App CPU during the resource-health step; set 0 to disable.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    maintenance_output = ROOT / "reports" / "codex-app-maintenance.scheduled.json"
    health_output = ROOT / "reports" / "windows-app-resource-health.scheduled.json"
    steps = [
        run_step(
            "codex_app_state_maintenance",
            [
                sys.executable,
                str(ROOT / "scripts" / "maintain_codex_app_state.py"),
                "--apply",
                "--log-retention-days",
                str(args.log_retention_days),
                "--max-log-rows",
                str(args.max_log_rows),
                "--max-session-files",
                str(args.max_session_files),
                "--max-live-threads",
                str(args.max_live_threads),
                "--output-file",
                str(maintenance_output),
                "--json",
            ],
        ),
        run_step(
            "windows_app_resource_health",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_windows_app_resource_health.py"),
                "--cleanup-stale-serena",
                "--throttle-codex-priority",
                "--prefer-low-power-gpu",
                "--cpu-sample-seconds",
                str(args.resource_cpu_sample_seconds),
                "--output-file",
                str(health_output),
                "--json",
            ],
        ),
    ]
    statuses = [str(step.get("status", "WARN")) for step in steps]
    report = {
        "status": collapse_status(statuses),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "cadence": {
            "recommended_interval_minutes": 240,
            "log_retention_days": args.log_retention_days,
            "max_log_rows": args.max_log_rows,
            "max_session_files": args.max_session_files,
            "max_live_threads": args.max_live_threads,
        },
        "steps": steps,
    }
    save_json(Path(args.output_file).expanduser().resolve(), report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['status']}: maintenance cycle steps={len(steps)}")
    return status_exit_code(str(report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
