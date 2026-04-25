#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.retention import build_retention_manifest
from devmgmt_runtime.reports import save_json

DEFAULT_OUTPUT_PATH = ROOT / "reports" / "retention-manifest.final.json"


def render_markdown(report: dict[str, object]) -> str:
    summary = report.get("summary", {})
    entries = report.get("entries", [])
    lines = [
        "# Retention Manifest",
        "",
        f"- Repo root: {report.get('repo_root', '')}",
        f"- Unknown count: {report.get('unknown_count', 0)}",
        "",
        "## Summary",
    ]
    if isinstance(summary, dict):
        for key in sorted(summary):
            lines.append(f"- {key}: {summary[key]}")
    lines.extend(["", "## Entries"])
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        lines.append(
            f"- `{entry.get('path', '.')}` [{entry.get('type', 'file')}] -> {entry.get('classification', 'DELETE_NOW')}: {entry.get('reason', '')}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the retention manifest for Dev-Management.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_retention_manifest(args.repo_root)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
