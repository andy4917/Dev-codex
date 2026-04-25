#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reference_graph import build_reference_graph
from devmgmt_runtime.reports import save_json

DEFAULT_OUTPUT_PATH = ROOT / "reports" / "reference-graph.final.json"


def render_markdown(report: dict[str, object]) -> str:
    nodes = report.get("nodes", [])
    edges = report.get("edges", [])
    lines = [
        "# Reference Graph",
        "",
        f"- Repo root: {report.get('repo_root', '')}",
        f"- Nodes: {len(nodes) if isinstance(nodes, list) else 0}",
        f"- Edges: {len(edges) if isinstance(edges, list) else 0}",
        "",
        "## Sample Edges",
    ]
    for edge in list(edges)[:200] if isinstance(edges, list) else []:
        if not isinstance(edge, dict):
            continue
        lines.append(f"- `{edge.get('source', '')}` -> `{edge.get('target', '')}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the repo reference graph for Dev-Management.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_reference_graph(args.repo_root)
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
