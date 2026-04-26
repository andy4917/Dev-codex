#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.codex_app_maintenance import default_paths, run_maintenance
from devmgmt_runtime.reports import save_json, write_markdown
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "codex-app-maintenance.final.json"
DEFAULT_LOG_RETENTION_DAYS = 1
DEFAULT_MAX_LOG_ROWS = 10000
DEFAULT_MAX_SESSION_FILES = 60
DEFAULT_MAX_LIVE_THREADS = 12


def render_markdown(report: dict[str, object]) -> str:
    actions = report.get("actions", {})
    lines = [
        "# Codex App Maintenance",
        "",
        f"- Status: `{report.get('status', 'UNKNOWN')}`",
        f"- Checked at: `{report.get('checked_at', '')}`",
        f"- Applied: `{report.get('applied', False)}`",
        f"- Backup policy: `{report.get('backup_policy', '')}`",
        f"- Backup dir: `{report.get('backup_dir', '')}`",
        f"- Archive dir: `{report.get('archive_dir', '')}`",
        f"- Temporary artifact disposal: `{report.get('temporary_artifact_disposal', '')}`",
        "",
        "## Actions",
    ]
    if isinstance(actions, dict):
        for name, payload in actions.items():
            if not isinstance(payload, dict):
                continue
            bits = []
            for key in (
                "changed",
                "stale_count",
                "candidate_count",
                "candidate_mb",
                "candidate_rows",
                "live_threads_before",
                "live_threads_after",
                "total_rows_before",
                "total_rows_after",
                "applied",
                "failed",
            ):
                if key in payload:
                    bits.append(f"{key}={payload[key]}")
            lines.append(f"- `{name}`: " + (", ".join(bits) if bits else "checked"))
    warnings = report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings"])
        for item in warnings:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize stale Codex App restore refs and compress old Codex logs."
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--codex-home", default=str(Path.home() / ".codex"))
    parser.add_argument(
        "--package-local-cache",
        default=str(Path.home() / "AppData" / "Local" / "Packages" / "OpenAI.Codex_2p2nqsd0c76g0" / "LocalCache"),
    )
    parser.add_argument("--log-retention-days", type=int, default=DEFAULT_LOG_RETENTION_DAYS)
    parser.add_argument("--max-log-rows", type=int, default=DEFAULT_MAX_LOG_ROWS)
    parser.add_argument("--max-session-files", type=int, default=DEFAULT_MAX_SESSION_FILES)
    parser.add_argument("--max-live-threads", type=int, default=DEFAULT_MAX_LIVE_THREADS)
    parser.add_argument(
        "--cleanup-render-cache",
        action="store_true",
        help="Recycle Codex Electron render caches such as Cache, Code Cache, and GPUCache. Best used immediately before app restart.",
    )
    parser.add_argument(
        "--keep-backups",
        action="store_true",
        help="Deprecated compatibility flag. Backups are not retained; backup/temp disposal is Recycle Bin by policy.",
    )
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paths = default_paths(Path(args.codex_home), Path(args.package_local_cache))
    report = run_maintenance(
        paths=paths,
        apply=args.apply,
        retention_days=args.log_retention_days,
        max_log_rows=args.max_log_rows,
        max_session_files=args.max_session_files,
        max_live_threads=args.max_live_threads,
        cleanup_render_cache=args.cleanup_render_cache,
        keep_backups=args.keep_backups,
    )
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    write_markdown(output_path.with_suffix(".md"), render_markdown(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"{report['status']}: applied={report['applied']} "
            f"backup_policy={report['backup_policy']} archive={report['archive_dir']}"
        )
    return status_exit_code(str(report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
