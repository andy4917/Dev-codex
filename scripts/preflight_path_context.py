#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.path_authority import (
    apply_path_policy_compatibility,
    canonical_roots,
    compare_workspace_authority,
    env_export_view,
    forbidden_primary_paths,
    get_codex_cli_bin,
    get_devmgmt_root,
    get_dev_product_root,
    get_dev_workflow_root,
    load_path_policy,
    path_policy_path_for,
    runtime_paths as authority_runtime_paths,
    validate_env_alignment,
    workspace_authority_path_for,
)
from devmgmt_runtime.paths import runtime_paths as managed_runtime_paths
from devmgmt_runtime.reports import load_json, save_json
from devmgmt_runtime.status import collapse_status, status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "path-preflight.final.json"
TEXT_EXTENSIONS = {".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "quarantine",
}
ALLOWED_ENVRC_LINES = [
    "if [ -f .env ]; then",
    "dotenv .env",
    "fi",
    "if [ -f .env.local ]; then",
    "dotenv .env.local",
    "fi",
    'export DEVMGMT_ROOT="${DEVMGMT_ROOT:-$(pwd)}"',
    'export PATH="$HOME/.local/share/dev-management/codex-npm/bin:$PATH"',
]
FORBIDDEN_ENVRC_TOKENS = (
    "/mnt/c/",
    "context7",
    "mcp",
    "serena",
)


def run(argv: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd) if cwd else None,
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc)}
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def shell(command: str) -> dict[str, Any]:
    shell_path = os.environ.get("SHELL", "/bin/sh")
    return run([shell_path, "-lc", command], cwd=ROOT)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def is_allowlisted_literal_file(path: Path, repo_root: Path, policy: dict[str, Any]) -> bool:
    relative = rel_path(path, repo_root).replace("\\", "/")
    allowed = policy.get("path_rules", {}).get("canonical_root_literals_allowed_in", [])
    for entry in allowed:
        token = str(entry).replace("\\", "/").strip()
        if not token:
            continue
        if token.endswith("/") and relative.startswith(token):
            return True
        if relative == token:
            return True
    return False


def iter_scan_files(repo_root: Path, policy: dict[str, Any]) -> list[Path]:
    files: list[Path] = []
    for relative in policy.get("path_rules", {}).get("scan_roots", []):
        base = (repo_root / relative).resolve()
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in TEXT_EXTENSIONS:
                files.append(path)
    for relative in policy.get("path_rules", {}).get("targeted_docs_enforced", []):
        path = (repo_root / relative).resolve()
        if path.exists() and path.is_file():
            files.append(path)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def scan_hardcoded_paths(repo_root: Path, authority: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    policy_literals = {
        *[str(path) for path in canonical_roots(policy).values()],
        *[str(path) for path in authority_runtime_paths(policy).values()],
        *forbidden_primary_paths(policy),
    }
    policy_literals = {item for item in policy_literals if item}
    legacy_literals = {
        str(item)
        for item in authority.get("hardcoding_definition", {})
        .get("path_rules", {})
        .get("legacy_repo_paths_to_remove", [])
        if str(item).strip()
    }

    findings: list[dict[str, Any]] = []
    legacy_refs: list[str] = []
    scanned_files = iter_scan_files(repo_root, policy)
    for path in scanned_files:
        if is_allowlisted_literal_file(path, repo_root, policy):
            continue
        text = read_text(path)
        for literal in sorted(policy_literals):
            if literal and literal in text:
                findings.append(
                    {
                        "path": str(path),
                        "relative_path": rel_path(path, repo_root),
                        "literal": literal,
                        "reason": "hardcoded authority path is not allowed outside contracts/tests/reports/.env.example",
                    }
                )
        for literal in sorted(legacy_literals):
            if literal and literal in text:
                legacy_refs.append(str(path))

    deduped_legacy = sorted(set(legacy_refs))
    status = "BLOCKED" if findings or deduped_legacy else "PASS"
    return {
        "status": status,
        "findings": findings,
        "legacy_repo_refs": deduped_legacy,
        "scanned_files": [str(path) for path in scanned_files],
    }


def inspect_env_files(repo_root: Path) -> dict[str, Any]:
    env_example = repo_root / ".env.example"
    env_file = repo_root / ".env"
    env_local = repo_root / ".env.local"
    tracked = run(["git", "-C", str(repo_root), "ls-files", "--", ".env.local", ".env.*.local"])
    tracked_lines = [line.strip() for line in tracked.get("stdout", "").splitlines() if line.strip()]
    status = "BLOCKED" if tracked_lines else "WARN" if not env_file.exists() else "PASS"
    return {
        "status": status,
        "env_example_exists": env_example.exists(),
        "env_exists": env_file.exists(),
        "env_local_exists": env_local.exists(),
        "tracked_local_files": tracked_lines,
        "reason": (
            ".env.local or .env.*.local is tracked by git"
            if tracked_lines
            else ".env is optional and currently absent"
            if not env_file.exists()
            else ""
        ),
    }


def inspect_envrc(repo_root: Path) -> dict[str, Any]:
    path = repo_root / ".envrc"
    if not path.exists():
        return {"status": "WARN", "exists": False, "reason": ".envrc is missing"}
    text = read_text(path)
    lowered = text.lower()
    if any(token in lowered for token in FORBIDDEN_ENVRC_TOKENS):
        return {
            "status": "BLOCKED",
            "exists": True,
            "reason": ".envrc contains forbidden runtime or toolchain configuration",
        }
    normalized = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if normalized != ALLOWED_ENVRC_LINES:
        return {
            "status": "BLOCKED",
            "exists": True,
            "reason": ".envrc is not the minimal approved bootstrap",
            "normalized_lines": normalized,
        }
    return {"status": "PASS", "exists": True, "reason": ""}


def inspect_direnv(repo_root: Path) -> dict[str, Any]:
    if shutil.which("direnv") is None:
        return {"status": "WARN", "available": False, "allowed": None, "reason": "direnv is not installed"}
    result = run(["direnv", "status"], cwd=repo_root)
    output = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".strip()
    allowed = None
    lowered = output.lower()
    if "found rc allowed true" in lowered or "loaded rc allowed true" in lowered:
        allowed = True
    elif "found rc allowed false" in lowered or "loaded rc allowed false" in lowered:
        allowed = False
    status = "PASS" if result.get("ok") and allowed is not False else "WARN"
    reason = "" if status == "PASS" else "direnv is unavailable or the current .envrc is not allowed"
    return {
        "status": status,
        "available": True,
        "allowed": allowed,
        "reason": reason,
        "output": output,
    }


def inspect_canonical_roots(policy: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    roots = {
        "dev_management": str(get_devmgmt_root(policy)),
        "dev_workflow": str(get_dev_workflow_root(policy)),
        "dev_product": str(get_dev_product_root(policy)),
    }
    missing = [path for path in roots.values() if not Path(path).exists()]
    management_root = Path(roots["dev_management"])
    try:
        repo_root.resolve().relative_to(management_root)
        repo_ok = True
    except ValueError:
        repo_ok = False
    status = "BLOCKED" if missing or not repo_ok else "PASS"
    return {
        "status": status,
        "roots": roots,
        "missing_roots": missing,
        "repo_root": str(repo_root),
        "repo_is_under_management_root": repo_ok,
    }


def inspect_codex_cli(policy: dict[str, Any]) -> dict[str, Any]:
    expected = get_codex_cli_bin(policy)
    command_v = shell("command -v codex || true")
    resolved = str(command_v.get("stdout", "")).strip()
    forbidden = forbidden_primary_paths(policy)
    resolved_is_forbidden = any(marker in resolved for marker in forbidden)
    expected_is_forbidden = any(marker in str(expected) for marker in forbidden) or str(expected).startswith("/mnt/c/")
    status = (
        "BLOCKED"
        if expected_is_forbidden or not expected.exists() or resolved_is_forbidden
        else "WARN"
        if not resolved
        else "PASS"
    )
    return {
        "status": status,
        "expected": str(expected),
        "expected_exists": expected.exists(),
        "command_v": resolved,
        "resolved_is_forbidden": resolved_is_forbidden,
        "reason": (
            "expected CODEX_CLI_BIN is missing or forbidden"
            if expected_is_forbidden or not expected.exists()
            else "command -v codex resolves to a forbidden Windows-mounted runtime"
            if resolved_is_forbidden
            else "helper resolves CODEX_CLI_BIN, but PATH is not bootstrapped"
            if not resolved
            else ""
        ),
    }


def inspect_windows_policy_surfaces(authority: dict[str, Any]) -> dict[str, Any]:
    paths = managed_runtime_paths(authority)
    observed = {
        "config": paths["observed_windows_policy_config"],
        "agents": paths["observed_windows_policy_agents"],
        "hooks": paths["observed_windows_policy_hooks"],
        "skills": paths["observed_windows_policy_skills"],
    }
    present = {name: str(path) for name, path in observed.items() if path.exists()}
    return {
        "status": "BLOCKED" if present else "PASS",
        "present": present,
        "windows_codex_home": str(paths["observed_windows_codex_home"]),
    }


def evaluate_path_context(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    policy_path = path_policy_path_for(root)
    authority_path = workspace_authority_path_for(root)
    raw_policy = load_json(policy_path, default={})
    raw_authority = load_json(authority_path, default={})
    policy = raw_policy if isinstance(raw_policy, dict) else {}
    if isinstance(policy, dict):
        policy["_path_policy_path"] = str(policy_path)
    authority = raw_authority if isinstance(raw_authority, dict) else {}

    compatibility_mismatches = compare_workspace_authority(policy, authority)
    authority = apply_path_policy_compatibility(authority, policy) if policy else authority

    compatibility = {
        "status": "BLOCKED" if compatibility_mismatches else "PASS",
        "mismatches": compatibility_mismatches,
        "mode": str(policy.get("compatibility", {}).get("mode", "")),
        "removal_phase": str(policy.get("compatibility", {}).get("removal_phase", "")),
    }
    env_alignment = validate_env_alignment(policy)
    root_check = inspect_canonical_roots(policy, root)
    codex_cli = inspect_codex_cli(policy)
    windows_policy = inspect_windows_policy_surfaces(authority)
    env_files = inspect_env_files(root)
    envrc = inspect_envrc(root)
    direnv = inspect_direnv(root)
    hardcoded = scan_hardcoded_paths(root, authority, policy)

    blockers: list[str] = []
    warnings: list[str] = []
    for check, blocked_reason, warn_reason in (
        (compatibility, "workspace_authority.json diverges from path_authority_policy.json", ""),
        (env_alignment, "environment exported view diverges from authority", ""),
        (root_check, "canonical roots are missing or repo root is outside the canonical management root", ""),
        (codex_cli, "canonical CODEX_CLI_BIN is missing or a forbidden Windows launcher is primary", "PATH is not bootstrapped to codex"),
        (windows_policy, "Windows .codex policy surfaces are present again", ""),
        (env_files, ".env.local or .env.*.local is tracked by git", ".env is absent"),
        (envrc, ".envrc is unsafe or non-minimal", ".envrc is missing"),
        (hardcoded, "hardcoded authority or legacy paths remain in source/docs", ""),
    ):
        status = str(check.get("status", "PASS"))
        if status == "BLOCKED" and blocked_reason:
            blockers.append(blocked_reason)
        if status == "WARN" and warn_reason:
            warnings.append(warn_reason)
    if direnv.get("status") == "WARN":
        warnings.append(str(direnv.get("reason", "direnv is not fully available")))

    status = collapse_status(
        [
            compatibility["status"],
            env_alignment["status"],
            root_check["status"],
            codex_cli["status"],
            windows_policy["status"],
            env_files["status"],
            envrc["status"],
            direnv["status"],
            hardcoded["status"],
        ]
    )
    return {
        "status": status,
        "gate_status": status,
        "repo_root": str(root),
        "path_policy_path": str(policy_path),
        "workspace_authority_path": str(authority_path),
        "expected_env_view": env_export_view(policy),
        "compatibility": compatibility,
        "env_alignment": env_alignment,
        "canonical_roots": root_check,
        "codex_cli": codex_cli,
        "windows_policy_surfaces": windows_policy,
        "env_files": env_files,
        "envrc": envrc,
        "direnv": direnv,
        "hardcoded_path_scan": hardcoded,
        "legacy_repo_refs": hardcoded["legacy_repo_refs"],
        "warnings": warnings,
        "blockers": blockers,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Path Preflight",
            "",
            f"- Status: {report.get('status', 'WARN')}",
            f"- Repo root: {report.get('repo_root', '')}",
            f"- Path policy: {report.get('path_policy_path', '')}",
            f"- Workspace compatibility: {report.get('compatibility', {}).get('status', 'WARN')}",
            f"- Env alignment: {report.get('env_alignment', {}).get('status', 'WARN')}",
            f"- Canonical roots: {report.get('canonical_roots', {}).get('status', 'WARN')}",
            f"- Codex CLI: {report.get('codex_cli', {}).get('status', 'WARN')}",
            f"- Windows policy surfaces: {report.get('windows_policy_surfaces', {}).get('status', 'WARN')}",
            f"- Env files: {report.get('env_files', {}).get('status', 'WARN')}",
            f"- .envrc: {report.get('envrc', {}).get('status', 'WARN')}",
            f"- direnv: {report.get('direnv', {}).get('status', 'WARN')}",
            f"- Hardcoded path scan: {report.get('hardcoded_path_scan', {}).get('status', 'WARN')}",
        ]
    ) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify path authority, exported env view, and runtime path bootstrap safety.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = evaluate_path_context(args.repo_root)
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
