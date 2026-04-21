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
from render_codex_runtime import render_hooks


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "windows-codex-policy-mirror-removal.dry-run.json"


def read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def generated_header_present(path: Path) -> bool:
    text = read_text(path)
    return text.startswith("# GENERATED - DO NOT EDIT") or text.startswith("GENERATED - DO NOT EDIT")


def generated_directory_marker_present(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    marker_names = {
        ".devmgmt-generated",
        ".generated-by-dev-management",
        ".devmgmt-mirror-manifest.json",
    }
    return any((path / marker).exists() for marker in marker_names)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def classify_candidate(path: Path, *, expected_linux_hooks: str | None) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "present": False,
            "kind": "directory" if path.name == "dev-workflow" else "file",
            "classification": "absent",
            "generated_marker_found": False,
            "reason": "path is absent",
            "action": "retain",
            "rollback_path": "",
        }

    if path.is_dir():
        generated = path.is_symlink() or generated_directory_marker_present(path)
        return {
            "path": str(path),
            "present": True,
            "kind": "directory",
            "classification": "generated_policy_surface" if generated else "unknown_app_or_user_state",
            "generated_marker_found": generated,
            "reason": (
                "directory carries a Dev-Management generated marker or generated symlink and is safe to quarantine"
                if generated
                else "directory is inside Windows app state but does not carry a Dev-Management generated marker"
            ),
            "action": "quarantine" if generated else "retain",
            "rollback_path": "",
        }

    text = read_text(path)
    generated = generated_header_present(path)
    if path.name == "hooks.json" and expected_linux_hooks and text == expected_linux_hooks:
        generated = True
    return {
        "path": str(path),
        "present": True,
        "kind": "file",
        "classification": "generated_policy_surface" if generated else "unknown_app_or_user_state",
        "generated_marker_found": generated,
        "reason": (
            "file carries a Dev-Management generated header or matches the generated Linux hooks payload and is safe to quarantine"
            if generated
            else "file is inside Windows app state but does not carry a Dev-Management generated marker"
        ),
        "action": "quarantine" if generated else "retain",
        "rollback_path": "",
    }


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
    items = [classify_candidate(path, expected_linux_hooks=expected_linux_hooks) for path in [*candidates, *wrapper_candidates]]
    applied_changes: list[dict[str, Any]] = []

    if apply:
        for item in items:
            if item["action"] != "quarantine" or not item["present"]:
                continue
            source = Path(item["path"])
            relative = source.relative_to(windows_home)
            target = quarantine_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            item["rollback_path"] = str(target)
            applied_changes.append(
                {
                    "source_path": str(source),
                    "action": "quarantined",
                    "rollback_path": str(target),
                }
            )
    else:
        for item in items:
            if item["action"] == "quarantine" and item["present"]:
                item["rollback_path"] = str(quarantine_root / Path(item["path"]).relative_to(windows_home))

    summary = {
        "generated_candidates": sum(1 for item in items if item["classification"] == "generated_policy_surface"),
        "unknown_observed": sum(1 for item in items if item["classification"] == "unknown_app_or_user_state"),
        "quarantined": len(applied_changes),
    }
    return {
        "generated_at": utc_timestamp(),
        "repo_root": str(repo_root),
        "mode": "apply" if apply else "dry-run",
        "windows_codex_home": str(windows_home),
        "quarantine_root": str(quarantine_root),
        "candidates": items,
        "summary": summary,
        "protected_paths_untouched": [str(path) for path in protected_paths],
        "applied_changes": applied_changes,
        "app_restart_required": bool(applied_changes or any(item["action"] == "quarantine" and item["present"] for item in items)),
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
