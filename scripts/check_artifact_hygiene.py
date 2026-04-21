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
QUARANTINE_SCRIPT_SUFFIXES = {".bat", ".cmd", ".exe", ".ps1", ".sh"}
QUARANTINE_IMPORTABLE_SUFFIXES = {".py"}
ACTIVE_QUARANTINE_REFERENCE_KEYWORDS = (
    "importlib",
    "python",
    "source ",
    "subprocess",
    "sys.path",
)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_manifest(quarantine_root: Path, quarantined: list[dict[str, str]]) -> Path:
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quarantine_root": str(quarantine_root),
        "classification": "inert_evidence_only",
        "reason": "Superseded remediation reports, stale preview files, and transient artifacts were quarantined as inert evidence.",
        "inert_guarantees": [
            "quarantined artifacts are not active policy sources",
            "quarantined artifacts must not be executed or imported",
            "restoration requires explicit manual review",
        ],
        "items": quarantined,
    }
    manifest_path = quarantine_root / "MANIFEST.json"
    save_json(manifest_path, manifest)
    try:
        manifest_path.chmod(0o644)
    except OSError:
        pass
    return manifest_path


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


def is_executable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & 0o111)
    except OSError:
        return False


def scan_quarantine_root(quarantine_root: Path) -> dict[str, list[str]]:
    executable_files: list[str] = []
    importable_files: list[str] = []
    cli_files: list[str] = []
    manifest_files: list[str] = []
    if not quarantine_root.exists():
        return {
            "executable_files": executable_files,
            "importable_files": importable_files,
            "cli_files": cli_files,
            "manifest_files": manifest_files,
        }

    for path in sorted(quarantine_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "MANIFEST.json":
            manifest_files.append(str(path))
            continue
        if is_executable(path):
            executable_files.append(str(path))
        suffix = path.suffix.lower()
        if suffix in QUARANTINE_IMPORTABLE_SUFFIXES:
            importable_files.append(str(path))
        elif suffix in QUARANTINE_SCRIPT_SUFFIXES:
            cli_files.append(str(path))
    return {
        "executable_files": executable_files,
        "importable_files": importable_files,
        "cli_files": cli_files,
        "manifest_files": manifest_files,
    }


def scan_preview_root(preview_root: Path) -> dict[str, list[str]]:
    preview_files = sorted(path for path in preview_root.glob("*")) if preview_root.exists() else []
    stale_previews: list[str] = []
    preview_executable_files: list[str] = []
    allowed_current_preview_names = {"codex-ssh-wrapper.sh"}
    for path in preview_files:
        if path.name not in allowed_current_preview_names:
            stale_previews.append(str(path))
        if path.is_file() and is_executable(path):
            preview_executable_files.append(str(path))
    if len(preview_files) > 1:
        stale_previews = sorted(str(path) for path in preview_files)
    return {
        "files": [str(path) for path in preview_files],
        "stale_preview_files": stale_previews,
        "preview_executable_files": preview_executable_files,
    }


def scan_transient_files(root: Path) -> list[str]:
    transient: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TRANSIENT_SUFFIXES:
            continue
        normalized = str(path).replace("\\", "/")
        if "/.git/" in normalized or "/quarantine/" in normalized:
            continue
        transient.append(str(path))
    return sorted(transient)


def scan_active_quarantine_references(root: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for base in (root / "tests", root / "docs", root / "scripts"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name == "check_artifact_hygiene.py":
                continue
            if path.name == "test_artifact_hygiene.py":
                continue
            if path.suffix.lower() not in {".md", ".py", ".txt", ".json", ".yaml", ".yml"}:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                normalized = line.lower()
                if "quarantine/" not in normalized and "quarantine\\" not in normalized:
                    continue
                if "manifest.json" in normalized:
                    continue
                if not any(keyword in normalized for keyword in ACTIVE_QUARANTINE_REFERENCE_KEYWORDS):
                    continue
                hits.append(
                    {
                        "path": str(path),
                        "line": line_number,
                        "text": line.strip(),
                    }
                )
    return hits


def finding(path: str, *, category: str, status: str, disposition: str, reason: str) -> dict[str, str]:
    return {
        "path": path,
        "category": category,
        "status": status,
        "disposition": disposition,
        "reason": reason,
    }


def evaluate_artifact_hygiene(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    reports = root / "reports"
    quarantine_root = root / "quarantine"
    stale_drafts = sorted(str(path) for path in reports.glob("*.draft.*"))
    remediation_reports = sorted(reports.glob("manual-system-remediation-*.md"))
    preview_root = reports / "generated-runtime-preview"
    preview_scan = scan_preview_root(preview_root)
    transient = scan_transient_files(root)
    quarantine_scan = scan_quarantine_root(quarantine_root)
    active_references = scan_active_quarantine_references(root)

    warnings: list[str] = []
    blocked: list[str] = []
    findings: list[dict[str, str]] = []

    if stale_drafts:
        warnings.append("stale draft reports detected")
        findings.extend(
            finding(
                path,
                category="stale_draft_report",
                status="WARN",
                disposition="INERT_QUARANTINE",
                reason="stale draft report should be quarantined or removed from active reports",
            )
            for path in stale_drafts
        )
    if len(remediation_reports) > 1:
        warnings.append("multiple remediation reports exist; keep the latest as final evidence and treat older ones as superseded")
        for path in remediation_reports[:-1]:
            findings.append(
                finding(
                    str(path),
                    category="superseded_remediation_report",
                    status="WARN",
                    disposition="INERT_QUARANTINE",
                    reason="older remediation draft remains beside the latest final remediation evidence",
                )
            )
    if preview_scan["stale_preview_files"]:
        warnings.append("stale generated runtime preview files detected")
        findings.extend(
            finding(
                path,
                category="stale_generated_runtime_preview",
                status="WARN",
                disposition="INERT_QUARANTINE",
                reason="generated-runtime-preview should retain only the current inert preview evidence",
            )
            for path in preview_scan["stale_preview_files"]
        )
    if transient:
        warnings.append("transient backup or scratch files detected")
        findings.extend(
            finding(
                path,
                category="transient_file",
                status="WARN",
                disposition="REMOVE_NOW",
                reason="backup or scratch file should not remain on active repo surfaces",
            )
            for path in transient
        )

    if preview_scan["preview_executable_files"]:
        blocked.append("generated runtime preview contains executable files")
        findings.extend(
            finding(
                path,
                category="executable_generated_runtime_preview",
                status="BLOCKED",
                disposition="FIX_NOW",
                reason="generated-runtime-preview must remain inert evidence only and cannot be executable",
            )
            for path in preview_scan["preview_executable_files"]
        )
    if quarantine_scan["executable_files"]:
        blocked.append("quarantine contains executable files")
        findings.extend(
            finding(
                path,
                category="executable_quarantine_file",
                status="BLOCKED",
                disposition="FIX_NOW",
                reason="quarantine is evidence only and must not contain executable files",
            )
            for path in quarantine_scan["executable_files"]
        )
    if quarantine_scan["importable_files"]:
        blocked.append("quarantine contains importable Python modules")
        findings.extend(
            finding(
                path,
                category="importable_quarantine_module",
                status="BLOCKED",
                disposition="FIX_NOW",
                reason="quarantine is evidence only and must not contain importable Python modules",
            )
            for path in quarantine_scan["importable_files"]
        )
    if quarantine_scan["cli_files"]:
        blocked.append("quarantine contains CLI or script entrypoints")
        findings.extend(
            finding(
                path,
                category="quarantine_cli_entrypoint",
                status="BLOCKED",
                disposition="FIX_NOW",
                reason="quarantine is evidence only and must not contain CLI or script entrypoints",
            )
            for path in quarantine_scan["cli_files"]
        )
    if active_references:
        blocked.append("tests, docs, or scripts reference quarantine as an active execution surface")
        findings.extend(
            finding(
                f"{item['path']}:{item['line']}",
                category="active_quarantine_reference",
                status="BLOCKED",
                disposition="FIX_NOW",
                reason="quarantine may be referenced only as evidence and must not be treated as an execution or import source",
            )
            for item in active_references
        )

    status = collapse_status(["BLOCKED" if blocked else "", "WARN" if warnings else ""])
    cleanup_actions = [
        "Quarantine stale drafts, superseded remediation reports, stale preview files, and transient backups with --apply-cleanup."
    ] if warnings else []
    if blocked:
        cleanup_actions.append("Remove executable/importable quarantine content and active quarantine references before closeout.")

    return {
        "status": status,
        "stale_draft_reports": stale_drafts,
        "remediation_reports": [str(path) for path in remediation_reports],
        "stale_preview_files": preview_scan["stale_preview_files"],
        "preview_executable_files": preview_scan["preview_executable_files"],
        "transient_files": transient,
        "quarantine_executable_files": quarantine_scan["executable_files"],
        "quarantine_importable_files": quarantine_scan["importable_files"],
        "quarantine_cli_files": quarantine_scan["cli_files"],
        "quarantine_manifest_files": quarantine_scan["manifest_files"],
        "active_quarantine_reference_hits": active_references,
        "findings": findings,
        "cleanup_actions": cleanup_actions,
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
    manifest_path = write_manifest(quarantine_root, quarantined)
    refreshed = evaluate_artifact_hygiene(root)
    refreshed["cleanup_applied"] = True
    refreshed["quarantine_root"] = str(quarantine_root)
    refreshed["manifest_path"] = str(manifest_path)
    refreshed["quarantined_files"] = quarantined
    refreshed["rollback_procedure"] = [
        f"Review files under {quarantine_root}",
        "Move any quarantined file back to its original source path if the cleanup needs to be rolled back.",
    ]
    return refreshed


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Artifact Hygiene", "", f"- Status: {report['status']}"]
    if report.get("cleanup_applied"):
        lines.append("- Cleanup applied: true")
        lines.append(f"- Quarantine root: {report.get('quarantine_root', '')}")
    for key in (
        "stale_draft_reports",
        "remediation_reports",
        "stale_preview_files",
        "preview_executable_files",
        "transient_files",
        "quarantine_executable_files",
        "quarantine_importable_files",
        "quarantine_cli_files",
    ):
        values = report.get(key, [])
        if values:
            lines.extend(["", f"## {key}"])
            lines.extend(f"- {value}" for value in values)
    if report.get("active_quarantine_reference_hits"):
        lines.extend(["", "## active_quarantine_reference_hits"])
        lines.extend(
            f"- {item['path']}:{item['line']} :: {item['text']}"
            for item in report["active_quarantine_reference_hits"]
        )
    if report.get("quarantined_files"):
        lines.extend(["", "## quarantined_files"])
        lines.extend(f"- {item['source']} -> {item['quarantine_path']}" for item in report["quarantined_files"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report stale drafts, quarantine inertness violations, preview leftovers, and transient artifacts.")
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
