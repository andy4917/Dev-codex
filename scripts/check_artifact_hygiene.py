#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "artifact-hygiene.unified-phase.json"
TRANSIENT_SUFFIXES = (".tmp", ".bak", ".old", ".orig")


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collapse_status(values: list[str]) -> str:
    items = [value for value in values if value]
    if any(value == "BLOCKED" for value in items):
        return "BLOCKED"
    if any(value == "WARN" for value in items):
        return "WARN"
    return "PASS"


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def evaluate_artifact_hygiene(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    reports = root / "reports"
    stale_drafts = sorted(str(path) for path in reports.glob("*.draft.*"))
    remediation_reports = sorted(reports.glob("manual-system-remediation-*.md"))
    preview_root = reports / "generated-runtime-preview"
    preview_files = sorted(path for path in preview_root.glob("*")) if preview_root.exists() else []
    stale_previews: list[str] = []
    allowed_current_preview_names = {"codex-ssh-wrapper.sh"}
    for path in preview_files:
        if path.name not in allowed_current_preview_names:
            stale_previews.append(str(path))
    if len(preview_files) > 1:
        stale_previews = sorted(str(path) for path in preview_files)
    transient = sorted(str(path) for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TRANSIENT_SUFFIXES and ".git/" not in str(path))
    warnings: list[str] = []
    if stale_drafts:
        warnings.append("stale draft reports detected")
    if len(remediation_reports) > 1:
        warnings.append("multiple remediation reports exist; keep the latest as final evidence and treat older ones as superseded")
    if stale_previews:
        warnings.append("stale generated runtime preview files detected")
    if transient:
        warnings.append("transient backup or scratch files detected")
    status = collapse_status(["WARN" if warnings else ""])
    return {
        "status": status,
        "stale_draft_reports": stale_drafts,
        "remediation_reports": [str(path) for path in remediation_reports],
        "stale_preview_files": stale_previews,
        "transient_files": transient,
        "cleanup_allowed_only_with_explicit_apply": True,
    }


def apply_cleanup(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    current = evaluate_artifact_hygiene(root)
    quarantined: list[dict[str, str]] = []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    quarantine_root = root / "quarantine" / "artifact-hygiene" / stamp
    quarantine_root.mkdir(parents=True, exist_ok=True)

    def quarantine_path(path: Path) -> Path:
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = Path(path.name)
        target = quarantine_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        quarantined.append({"source": str(path), "quarantine_path": str(target)})
        return target

    for raw_path in current.get("stale_draft_reports", []):
        path = Path(raw_path)
        if path.exists() and path.is_file():
            quarantine_path(path)
    remediation_reports = [Path(item) for item in current.get("remediation_reports", [])]
    if len(remediation_reports) > 1:
        for path in remediation_reports[:-1]:
            if path.exists() and path.is_file():
                quarantine_path(path)
    for raw_path in current.get("stale_preview_files", []):
        path = Path(raw_path)
        if path.exists() and path.is_file():
            quarantine_path(path)
    for raw_path in current.get("transient_files", []):
        path = Path(raw_path)
        if path.exists() and path.is_file() and root in path.parents:
            quarantine_path(path)
    refreshed = evaluate_artifact_hygiene(root)
    refreshed["cleanup_applied"] = True
    refreshed["quarantine_root"] = str(quarantine_root)
    refreshed["quarantined_files"] = quarantined
    refreshed["rollback_procedure"] = [
        f"Review files under {quarantine_root}",
        "Move any quarantined file back to its original source path if the cleanup needs to be rolled back.",
    ]
    return refreshed


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Artifact Hygiene", "", f"- Status: {report['status']}"]
    if report.get("cleanup_applied"):
        lines.append(f"- Cleanup applied: true")
        lines.append(f"- Quarantine root: {report.get('quarantine_root', '')}")
    for key in ("stale_draft_reports", "remediation_reports", "stale_preview_files", "transient_files"):
        values = report.get(key, [])
        if values:
            lines.extend(["", f"## {key}"])
            lines.extend(f"- {value}" for value in values)
    if report.get("quarantined_files"):
        lines.extend(["", "## quarantined_files"])
        lines.extend(f"- {item['source']} -> {item['quarantine_path']}" for item in report["quarantined_files"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report stale drafts, duplicate remediation reports, preview leftovers, and transient artifacts.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply-cleanup", action="store_true")
    args = parser.parse_args()
    report = apply_cleanup(args.repo_root) if args.apply_cleanup else evaluate_artifact_hygiene(args.repo_root)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
