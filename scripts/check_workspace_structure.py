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
from devmgmt_runtime.reports import load_json, save_json, write_markdown
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "workspace-structure.final.json"
POLICY_PATH = ROOT / "contracts" / "workspace_structure_policy.json"
EXPECTED_TAXONOMY = [
    "CLI_SHELL",
    "CORE_RUNTIME",
    "CONTRACT_AUTHORITY",
    "DOCS",
    "SDK",
    "SCRIPTS",
    "TOOLS",
    "PATCHES",
    "THIRD_PARTY",
    "CONFIG_ENV",
    "GENERATED_EVIDENCE",
    "TESTS",
    "SKILLS",
    "PRODUCT_SOURCE",
    "USER_CONTROL_PLANE",
    "APP_STATE",
    "EXTERNAL_DEPENDENCY",
    "DECOMMISSIONED",
    "STALE_OR_MISPLACED",
]
EXPECTED_DEV_MANAGEMENT_ROLES = {
    "contracts": "CONTRACT_AUTHORITY",
    "devmgmt_runtime": "CORE_RUNTIME",
    "docs": "DOCS",
    "scripts": "SCRIPTS",
    "tests": "TESTS",
    "reports": "GENERATED_EVIDENCE",
    "tools": "TOOLS",
    "patches": "PATCHES",
    "third_party": "THIRD_PARTY",
    ".agents/skills": "SKILLS",
}
DEFAULT_TREE_DEPTH = 3
MAX_TREE_ENTRIES = 80
TREE_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SENSITIVE_TREE_ROLES = {"CONFIG_ENV", "USER_CONTROL_PLANE", "APP_STATE", "APP_CONTROL_PLANE", "DECOMMISSIONED"}


def _check(status: str, reasons: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "reasons": reasons or []}
    payload.update(extra)
    return payload


def _safe_iterdir(path: Path) -> tuple[list[Path], str]:
    try:
        return (sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())), "")
    except OSError as exc:
        return ([], f"{exc.__class__.__name__}: {exc}")


def build_directory_tree(path: Path, *, max_depth: int = DEFAULT_TREE_DEPTH, max_entries: int = MAX_TREE_ENTRIES, list_files: bool = True) -> dict[str, Any]:
    resolved = path.expanduser()
    payload: dict[str, Any] = {
        "name": resolved.name or str(resolved),
        "path": str(resolved),
        "type": "directory" if resolved.is_dir() else "file" if resolved.is_file() else "missing",
        "exists": resolved.exists(),
        "children": [],
        "truncated": False,
        "error": "",
    }
    if not resolved.exists() or not resolved.is_dir() or max_depth <= 0:
        return payload

    children, error = _safe_iterdir(resolved)
    if error:
        payload["error"] = error
        return payload

    visible = [item for item in children if item.name not in TREE_EXCLUDED_DIRS]
    skipped = len(children) - len(visible)
    if len(visible) > max_entries:
        payload["truncated"] = True
        skipped += len(visible) - max_entries
        visible = visible[:max_entries]

    child_payloads: list[dict[str, Any]] = []
    file_count = 0
    dir_count = 0
    for child in visible:
        if child.is_dir():
            dir_count += 1
            child_payloads.append(build_directory_tree(child, max_depth=max_depth - 1, max_entries=max_entries, list_files=list_files))
        elif list_files:
            file_count += 1
            child_payloads.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": "file",
                    "exists": True,
                    "children": [],
                    "truncated": False,
                    "error": "",
                }
            )
        else:
            file_count += 1
    payload["children"] = child_payloads
    payload["child_summary"] = {
        "directories": dir_count,
        "files": file_count,
        "skipped_or_truncated": skipped,
    }
    return payload


def _render_tree_node(node: dict[str, Any], *, indent: str = "") -> list[str]:
    marker = "/" if node.get("type") == "directory" else ""
    suffix = ""
    if node.get("truncated"):
        suffix = " (truncated)"
    if node.get("error"):
        suffix = f" ({node['error']})"
    lines = [f"{indent}- {node.get('name', '')}{marker}{suffix}"]
    summary = node.get("child_summary", {})
    if summary and not node.get("children"):
        lines.append(
            f"{indent}  - children: {summary.get('directories', 0)} dirs, {summary.get('files', 0)} files, {summary.get('skipped_or_truncated', 0)} skipped"
        )
    for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
        lines.extend(_render_tree_node(child, indent=f"{indent}  "))
    return lines


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    required_keys = {
        "schema_version",
        "workspace_root",
        "taxonomy",
        "root_roles",
        "windows_codex_surface",
        "dev_management_roles",
        "documentation_requirements",
        "invariants",
    }
    missing = sorted(required_keys - set(policy.keys()))
    if missing:
        blockers.append(f"policy is missing required keys: {', '.join(missing)}")
    if policy.get("schema_version") != "2026.04.workspace-structure.windows-native.v1":
        blockers.append("schema_version must be 2026.04.workspace-structure.windows-native.v1")
    if policy.get("taxonomy") != EXPECTED_TAXONOMY:
        blockers.append("taxonomy does not match the approved workspace role set")
    windows_surface = policy.get("windows_codex_surface", {})
    if windows_surface.get("role") != "USER_CONTROL_PLANE":
        blockers.append("windows_codex_surface.role must be USER_CONTROL_PLANE")
    if windows_surface.get("app_state") is not True:
        blockers.append("windows_codex_surface.app_state must be true")
    if windows_surface.get("repo_authority") is not False:
        blockers.append("windows_codex_surface.repo_authority must be false")
    if windows_surface.get("authoritative") is not True:
        blockers.append("windows_codex_surface.authoritative must be true")
    if windows_surface.get("workspace_structure_authority") is not False:
        blockers.append("windows_codex_surface.workspace_structure_authority must be false")
    invariants = policy.get("invariants", {})
    for key in (
        "reports_are_evidence_only",
    ):
        if invariants.get(key) is not True:
            blockers.append(f"invariants.{key} must be true")
    if invariants.get("windows_codex_not_workspace_authority") is not True:
        blockers.append("invariants.windows_codex_not_workspace_authority must be true")
    if invariants.get("windows_codex_is_app_control_plane") is not True:
        blockers.append("invariants.windows_codex_is_app_control_plane must be true")
    role_payload = policy.get("dev_management_roles", {})
    for relative, role in EXPECTED_DEV_MANAGEMENT_ROLES.items():
        current = role_payload.get(relative, {})
        if not isinstance(current, dict) or current.get("role") != role:
            blockers.append(f"dev_management_roles.{relative} must declare role {role}")
    return _check("BLOCKED" if blockers else "PASS", blockers)


def evaluate_workspace_structure(
    repo_root: str | Path | None = None,
    *,
    policy_override: dict[str, Any] | None = None,
    authority_override: dict[str, Any] | None = None,
    home_override: Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    policy = policy_override or load_json(root / "contracts" / "workspace_structure_policy.json", default={})
    authority = authority_override or load_authority(root)
    home_root = home_override or Path(str(policy.get("workspace_root", Path.home()))).expanduser()

    checks: dict[str, Any] = {}
    checks["policy"] = validate_policy(policy)

    root_roles = policy.get("root_roles", {}) if isinstance(policy.get("root_roles"), dict) else {}
    authority_roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    root_checks: list[dict[str, Any]] = []
    for label, payload in root_roles.items():
        if not isinstance(payload, dict):
            continue
        configured_path = Path(str(payload.get("path", ""))).expanduser()
        if label == "Dev-Management" and authority_roots.get("management"):
            configured_path = Path(str(authority_roots["management"])).expanduser()
        elif label == "Dev-Workflow" and authority_roots.get("workflow"):
            configured_path = Path(str(authority_roots["workflow"])).expanduser()
        elif label == "Dev-Product" and authority_roots.get("product"):
            configured_path = Path(str(authority_roots["product"])).expanduser()
        elif str(label).startswith(".") and not configured_path.is_absolute():
            configured_path = home_root / label
        exists = configured_path.exists()
        required = payload.get("required") is True
        expected_absent = payload.get("expected_absent") is True
        if expected_absent:
            status = "BLOCKED" if exists else "PASS"
            reason = "decommissioned workspace root still exists" if exists else ""
        else:
            status = "PASS" if exists or not required else "BLOCKED"
            reason = "" if exists else ("required workspace root is missing" if required else "optional workspace root is absent")
        root_checks.append(
            {
                "label": label,
                "path": str(configured_path),
                "role": str(payload.get("role", "")),
                "required": required,
                "expected_absent": expected_absent,
                "exists": exists,
                "status": status,
                "reason": reason,
            }
        )
    checks["workspace_roots"] = {
        "status": collapse_status([item["status"] for item in root_checks]),
        "items": root_checks,
    }

    windows_surface = policy.get("windows_codex_surface", {}) if isinstance(policy.get("windows_codex_surface"), dict) else {}
    checks["windows_codex_surface"] = {
        "status": "PASS"
        if windows_surface.get("role") == "USER_CONTROL_PLANE"
        and windows_surface.get("app_state") is True
        and windows_surface.get("repo_authority") is False
        and windows_surface.get("authoritative") is True
        and windows_surface.get("workspace_structure_authority") is False
        else "BLOCKED",
        "path": str(windows_surface.get("path", "")),
        "role": str(windows_surface.get("role", "")),
        "app_state": bool(windows_surface.get("app_state")),
        "repo_authority": bool(windows_surface.get("repo_authority")),
        "authoritative": bool(windows_surface.get("authoritative")),
        "workspace_structure_authority": bool(windows_surface.get("workspace_structure_authority")),
        "reasons": []
        if windows_surface.get("role") == "USER_CONTROL_PLANE"
        else ["Windows .codex must be classified as USER_CONTROL_PLANE."],
    }

    docs_requirements = policy.get("documentation_requirements", {}) if isinstance(policy.get("documentation_requirements"), dict) else {}
    management_roles = policy.get("dev_management_roles", {}) if isinstance(policy.get("dev_management_roles"), dict) else {}
    management_items: list[dict[str, Any]] = []
    for relative, payload in management_roles.items():
        if not isinstance(payload, dict):
            continue
        path = root / relative
        required = payload.get("required") is True
        exists = path.exists()
        status = "PASS"
        reason = ""
        if not exists:
            status = "BLOCKED" if required else "PASS"
            reason = "required Dev-Management path is missing" if required else "optional path is absent"
        elif path.is_dir() and relative in docs_requirements:
            required_markers = [item for item in docs_requirements[relative] if isinstance(item, str)]
            has_marker = any((path / marker).exists() for marker in required_markers)
            if not has_marker:
                status = "WARN"
                reason = "directory exists without README or manifest marker"
        management_items.append(
            {
                "path": str(path),
                "relative_path": relative,
                "role": str(payload.get("role", "")),
                "required": required,
                "exists": exists,
                "status": status,
                "reason": reason,
            }
        )
    checks["dev_management_layout"] = {
        "status": collapse_status([item["status"] for item in management_items]),
        "items": management_items,
    }

    workspace_tree_items: list[dict[str, Any]] = []
    for item in root_checks:
        role = str(item.get("role", ""))
        path = Path(str(item.get("path", ""))).expanduser()
        listing_mode = "detailed"
        if role == "USER_CONTROL_PLANE":
            listing_mode = "control_plane"
        elif role in {"APP_STATE", "APP_CONTROL_PLANE"}:
            listing_mode = "app_state"
        elif role == "DECOMMISSIONED":
            listing_mode = "decommissioned"
        elif role in SENSITIVE_TREE_ROLES:
            listing_mode = "redacted"
        workspace_tree_items.append(
            {
                "label": item.get("label", ""),
                "role": role,
                "path": str(path),
                "exists": bool(item.get("exists")),
                "listing_mode": listing_mode,
                "tree": build_directory_tree(path, list_files=role not in SENSITIVE_TREE_ROLES),
            }
        )
    checks["workspace_tree"] = {
        "status": "PASS",
        "max_depth": DEFAULT_TREE_DEPTH,
        "excluded_dirs": sorted(TREE_EXCLUDED_DIRS),
        "items": workspace_tree_items,
    }

    status = collapse_status([payload.get("status", "PASS") for payload in checks.values()])
    blockers: list[str] = []
    warnings: list[str] = []
    for payload in checks.values():
        reasons = payload.get("reasons", []) if isinstance(payload, dict) else []
        if payload.get("status") == "BLOCKED":
            blockers.extend(str(item) for item in reasons if str(item).strip())
        elif payload.get("status") == "WARN":
            warnings.extend(str(item) for item in reasons if str(item).strip())
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            reason = str(item.get("reason", "")).strip()
            if not reason:
                continue
            if item.get("status") == "BLOCKED":
                blockers.append(reason)
            elif item.get("status") == "WARN":
                warnings.append(reason)

    return {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "policy_path": str(root / "contracts" / "workspace_structure_policy.json"),
        "workspace_root": str(home_root),
        "management_root": str(root),
        "checks": checks,
        "blockers": sorted(dict.fromkeys(blockers)),
        "warnings": sorted(dict.fromkeys(warnings)),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Workspace Structure",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Workspace root: {report.get('workspace_root', '')}",
        f"- Management root: {report.get('management_root', '')}",
        "",
        "## Checks",
    ]
    for name, payload in report.get("checks", {}).items():
        if name == "workspace_tree":
            continue
        lines.append(f"- [{payload.get('status', 'WARN')}] {name}")
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            reason = str(item.get("reason", "")).strip() or "ok"
            lines.append(f"  - {item.get('relative_path', item.get('label', item.get('path', 'unknown')))} => {item.get('role', '')}: {reason}")
    tree_payload = report.get("checks", {}).get("workspace_tree", {})
    if isinstance(tree_payload, dict):
        lines.extend(["", "## Folder Tree"])
        lines.append(f"- Max depth: {tree_payload.get('max_depth', DEFAULT_TREE_DEPTH)}")
        lines.append(f"- Excluded dirs: {', '.join(tree_payload.get('excluded_dirs', []))}")
        for item in tree_payload.get("items", []):
            mode = item.get("listing_mode", "detailed")
            lines.append("")
            lines.append(f"### {item.get('label', '')} ({item.get('role', '')}, {mode})")
            lines.append(f"- Path: {item.get('path', '')}")
            if not item.get("exists"):
                lines.append("- Status: missing")
                continue
            lines.extend(_render_tree_node(item.get("tree", {})))
    if report.get("blockers"):
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in report.get("blockers", []))
    if report.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in report.get("warnings", []))
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], output_path: Path) -> None:
    save_json(output_path, report)
    write_markdown(output_path.with_suffix(".md"), render_markdown(report))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Dev-Management workspace structure policy alignment.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_workspace_structure(Path(args.repo_root).expanduser().resolve())
    output_path = Path(args.output_file).expanduser().resolve()
    write_reports(report, output_path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report.get("status", "WARN"))


if __name__ == "__main__":
    raise SystemExit(main())
