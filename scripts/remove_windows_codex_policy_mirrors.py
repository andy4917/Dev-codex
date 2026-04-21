#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
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


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def make_inert(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        for child in path.rglob("*"):
            try:
                if child.is_dir():
                    child.chmod(0o755)
                else:
                    child.chmod(0o644)
            except OSError:
                continue
        try:
            path.chmod(0o755)
        except OSError:
            pass
        return
    try:
        path.chmod(0o644)
    except OSError:
        pass


def write_manifest(quarantine_root: Path, applied_changes: list[dict[str, Any]]) -> Path:
    manifest = {
        "generated_at": utc_timestamp(),
        "quarantine_root": str(quarantine_root),
        "classification": "inert_evidence_only",
        "reason": "Dev-Management-generated Windows .codex policy-bearing files were quarantined because Windows .codex is not an authority surface.",
        "inert_guarantees": [
            "files in this quarantine root must not be executed",
            "files in this quarantine root must not be imported",
            "files in this quarantine root must not be read as active policy source",
            "restoration requires explicit manual review",
        ],
        "items": applied_changes,
    }
    manifest_path = quarantine_root / "MANIFEST.json"
    save_json(manifest_path, manifest)
    try:
        manifest_path.chmod(0o644)
    except OSError:
        pass
    return manifest_path


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

    quarantine_root = repo_root / "quarantine" / "windows-codex-policy-mirrors" / timestamp_slug()
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
        item["rollback_path"] = ""
        items.append(item)
    applied_changes: list[dict[str, Any]] = []

    if apply:
        for item in items:
            if not item["present"]:
                continue
            source = Path(item["path"])
            if item["operation"] == "quarantine":
                relative = source.relative_to(windows_home)
                target = quarantine_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                make_inert(target)
                item["rollback_path"] = str(target)
                applied_changes.append(
                    {
                        "source_path": str(source),
                        "action": "quarantined",
                        "rollback_path": str(target),
                        "inert_after_quarantine": True,
                    }
                )
            elif item["operation"] == "remove":
                removed_entries = remove_directory_tree(source) if source.is_dir() else 0
                if source.exists():
                    source.unlink()
                    removed_entries += 1
                item["rollback_path"] = ""
                applied_changes.append(
                    {
                        "source_path": str(source),
                        "action": "removed",
                        "rollback_path": "",
                        "removed_entries": removed_entries,
                        "rollback_note": "No repo quarantine copy was kept because this surface was classified REMOVE_NOW stale mirror residue.",
                    }
                )
        if applied_changes:
            manifest_path = write_manifest(quarantine_root, applied_changes)
        else:
            manifest_path = quarantine_root / "MANIFEST.json"
    else:
        for item in items:
            if item["operation"] == "quarantine" and item["present"]:
                item["rollback_path"] = str(quarantine_root / Path(item["path"]).relative_to(windows_home))
        manifest_path = quarantine_root / "MANIFEST.json"

    summary = {
        "generated_candidates": sum(1 for item in items if item["classification"] == "generated_policy_surface"),
        "remove_now_candidates": sum(1 for item in items if item["disposition"] == "REMOVE_NOW"),
        "manual_remediation_candidates": sum(1 for item in items if item["disposition"] == "MANUAL_REMEDIATION"),
        "quarantined": sum(1 for item in applied_changes if item["action"] == "quarantined"),
        "removed": sum(1 for item in applied_changes if item["action"] == "removed"),
    }
    return {
        "generated_at": utc_timestamp(),
        "repo_root": str(repo_root),
        "mode": "apply" if apply else "dry-run",
        "windows_codex_home": str(windows_home),
        "quarantine_root": str(quarantine_root),
        "windows_policy_surface_report": surface_report,
        "candidates": items,
        "summary": summary,
        "manifest_path": str(manifest_path),
        "protected_paths_untouched": [str(path) for path in protected_paths],
        "applied_changes": applied_changes,
        "app_restart_required": bool(applied_changes or any(item["operation"] in {"quarantine", "remove"} and item["present"] for item in items)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine Dev-Management-generated Windows .codex policy mirrors without touching app runtime state.")
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
