#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.paths import runtime_paths
from devmgmt_runtime.reports import save_json
from devmgmt_runtime.windows_policy import remove_directory_tree, windows_policy_surface_report
from render_codex_runtime import render_hooks


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "windows-codex-policy-mirror-removal.dry-run.json"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_report(repo_root: Path, *, apply: bool) -> dict[str, Any]:
    authority = load_authority(repo_root)
    paths = runtime_paths(authority)
    windows_home = paths["observed_windows_codex_home"]
    expected_linux_hooks = render_hooks(authority, windows=False)
    candidates = [
        paths["observed_windows_policy_config"],
        paths["observed_windows_policy_agents"],
        paths["observed_windows_policy_hooks"],
        paths["observed_windows_policy_skills"],
    ]
    wrapper_candidates = sorted(windows_home.glob("**/scorecard-hook-wrapper.ps1"))
    protected_paths = [
        windows_home / "bin" / "wsl" / "codex",
        Path.home() / ".ssh" / "config",
    ]

    surface_report = windows_policy_surface_report(paths, authority, expected_linux_hooks=expected_linux_hooks)
    findings_by_path = {item["path"]: dict(item) for item in surface_report.get("findings", []) if isinstance(item, dict)}
    items: list[dict[str, Any]] = []
    for path in [*candidates, *wrapper_candidates]:
        item = findings_by_path.get(str(path), {})
        if not item:
            item = {
                "path": str(path),
                "present": False,
                "kind": "directory" if path.name == "dev-workflow" else "file",
                "classification": "absent",
                "disposition": "ACCEPTED_NONBLOCKING",
                "operation": "retain",
                "generated_marker_found": False,
                "reason": "path is absent",
            }
        items.append(item)
    applied_changes: list[dict[str, Any]] = []

    if apply:
        for item in items:
            if not item["present"]:
                continue
            source = Path(item["path"])
            if item["operation"] == "remove":
                removed_entries = remove_directory_tree(source) if source.is_dir() else 0
                if source.exists():
                    source.unlink()
                    removed_entries += 1
                applied_changes.append(
                    {
                        "source_path": str(source),
                        "action": "removed",
                        "removed_entries": removed_entries,
                        "rollback_note": "Generated or structurally stale Windows policy surface was removed; regeneration or Git history is the rollback, not a backup copy.",
                    }
                )

    summary = {
        "generated_candidates": sum(1 for item in items if item["classification"] == "generated_policy_surface"),
        "remove_now_candidates": sum(1 for item in items if item["disposition"] == "REMOVE_NOW"),
        "manual_remediation_candidates": sum(1 for item in items if item["disposition"] == "MANUAL_REMEDIATION"),
        "removed": sum(1 for item in applied_changes if item["action"] == "removed"),
    }
    return {
        "generated_at": utc_timestamp(),
        "repo_root": str(repo_root),
        "mode": "apply" if apply else "dry-run",
        "windows_codex_home": str(windows_home),
        "windows_policy_surface_report": surface_report,
        "candidates": items,
        "summary": summary,
        "protected_paths_untouched": [str(path) for path in protected_paths],
        "applied_changes": applied_changes,
        "app_restart_required": bool(applied_changes or any(item["operation"] == "remove" and item["present"] for item in items)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove Dev-Management-generated or structurally stale Windows .codex policy surfaces without touching protected app runtime state.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.apply and args.dry_run:
        raise SystemExit("--dry-run and --apply are mutually exclusive")

    report = build_report(Path(args.repo_root).expanduser().resolve(), apply=args.apply)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
