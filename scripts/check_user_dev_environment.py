#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_windows_app_local_readiness import evaluate_windows_app_local_readiness
from devmgmt_runtime.path_authority import canonical_roots, load_path_policy, validate_env_alignment, windows_codex_home
from devmgmt_runtime.reports import load_json, save_json, write_markdown
from devmgmt_runtime.status import collapse_status, status_exit_code
from devmgmt_runtime.windows_policy import classify_windows_policy_candidate


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "user-dev-environment-baseline.final.json"
DEFAULT_MARKDOWN_PATH = ROOT / "reports" / "user-dev-environment-baseline.final.md"
POLICY_PATH = ROOT / "contracts" / "user_dev_environment_policy.json"
LEGACY_LINUX_MARKERS = ("/home/", "/mnt/", "legacy-linux", "legacy-remote")
AI_PYTHON_PACKAGE_DISTRIBUTIONS = {
    "langchain": "langchain",
    "langgraph": "langgraph",
    "openai-agents": "openai-agents",
    "mcp": "mcp",
}
DEV_MANAGEMENT_SCRATCH = Path(r"C:\Users\anise\code\.scratch\Dev-Management")
REPO_SCRATCH = ROOT / "codex-scripts"
MIGRATION_EVIDENCE_ROOT = ROOT / "reports" / "migration-evidence" / "20260425-windows-native-transition"
USER_SSH_ROOT = Path(r"C:\Users\anise\.ssh")
POWERSHELL_ROOT = Path.home() / "Documents" / "PowerShell"
POWERSHELL_PROFILE = POWERSHELL_ROOT / "Microsoft.PowerShell_profile.ps1"
POWERSHELL_UTF8_POLICY = POWERSHELL_ROOT / "policies" / "utf8.ps1"
POWERSHELL_NATIVE_ARGS_POLICY = POWERSHELL_ROOT / "policies" / "native-args.ps1"


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_policy(repo_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    policy_path = root / "contracts" / "user_dev_environment_policy.json"
    payload = load_json(policy_path if policy_path.exists() else POLICY_PATH, default={})
    return payload if isinstance(payload, dict) else {}


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_path_text(value: str | Path) -> str:
    return str(value).replace("\\", "/").strip().lower()


def is_legacy_linux_reference(value: str | Path) -> bool:
    normalized = normalize_path_text(value)
    return any(marker.replace("\\", "/").lower() in normalized for marker in LEGACY_LINUX_MARKERS)


def is_windows_project_path(value: str | Path) -> bool:
    normalized = normalize_path_text(value)
    return len(normalized) > 2 and normalized[1:3] == ":/"


def run_command(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc), "command": args}
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": args,
    }


def inspect_windows_codex_boundary(user_policy: dict[str, Any], path_policy: dict[str, Any]) -> dict[str, Any]:
    codex_home = windows_codex_home(path_policy)
    config_path = codex_home / "config.toml"
    agents_path = codex_home / "AGENTS.md"
    hooks_path = codex_home / "hooks.json"
    skills_path = codex_home / "skills"
    config_payload = load_toml(config_path)
    target = user_policy.get("target_app_config", {}) if isinstance(user_policy.get("target_app_config"), dict) else {}
    features = config_payload.get("features", {}) if isinstance(config_payload.get("features"), dict) else {}
    windows_cfg = config_payload.get("windows", {}) if isinstance(config_payload.get("windows"), dict) else {}
    projects = config_payload.get("projects", {}) if isinstance(config_payload.get("projects"), dict) else {}

    findings = {
        "config": classify_windows_policy_candidate(config_path, path_policy),
        "agents": classify_windows_policy_candidate(agents_path, path_policy),
        "hooks": classify_windows_policy_candidate(hooks_path, path_policy),
        "skills": classify_windows_policy_candidate(skills_path, path_policy),
    }
    blockers: list[str] = []
    warnings: list[str] = []
    for finding in findings.values():
        reason = str(finding.get("reason", "")).strip()
        if finding.get("status") == "BLOCKED" and reason:
            blockers.append(reason)
        elif finding.get("status") == "WARN" and reason:
            warnings.append(reason)

    approval_policy = str(config_payload.get("approval_policy", "")).strip()
    sandbox_mode = str(config_payload.get("sandbox_mode", "")).strip()
    windows_sandbox = str(windows_cfg.get("sandbox", "")).strip()
    reasoning = str(config_payload.get("model_reasoning_effort", "")).strip()
    expected_roots = [
        normalize_path_text(item)
        for item in user_policy.get("windows_codex_boundary", {}).get("required_local_project_roots", [])
        if str(item).strip()
    ]
    trusted_project_paths = [normalize_path_text(key) for key in projects.keys()]
    missing_projects = [root for root in expected_roots if not any(path.startswith(root) for path in trusted_project_paths)]

    if approval_policy != str(target.get("approval_policy", "never")):
        blockers.append(f"approval_policy is {approval_policy or 'unset'}, expected never for trusted Windows-native mode.")
    if sandbox_mode != str(target.get("sandbox_mode", "danger-full-access")):
        blockers.append(f"sandbox_mode is {sandbox_mode or 'unset'}, expected danger-full-access for trusted Windows-native mode.")
    if windows_sandbox != str(target.get("windows_sandbox", "elevated")):
        blockers.append(f"windows.sandbox is {windows_sandbox or 'unset'}, expected elevated.")
    if missing_projects:
        blockers.append("Codex config is missing trusted local Windows project roots: " + ", ".join(missing_projects))

    legacy_refs = [
        path
        for path in trusted_project_paths
        if is_legacy_linux_reference(path)
    ]
    if legacy_refs:
        blockers.append("Codex config still contains legacy Linux/remote project references: " + ", ".join(legacy_refs))

    status = "BLOCKED" if blockers else "WARN" if warnings else "PASS"
    return {
        "status": status,
        "windows_codex_home": str(codex_home),
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "approval_policy": approval_policy,
        "sandbox_mode": sandbox_mode,
        "windows_sandbox": windows_sandbox,
        "model_reasoning_effort": reasoning,
        "remote_control_enabled": features.get("remote_control") is True,
        "remote_connections_enabled": features.get("remote_connections") is True,
        "workspace_dependencies_enabled": features.get("workspace_dependencies") is True,
        "trusted_project_paths": trusted_project_paths,
        "missing_trusted_project_roots": missing_projects,
        "surface_findings": findings,
        "reasons": blockers + warnings,
        "user_actions": [] if status == "PASS" else ["Normalize Windows Codex config to the Windows-native target posture."],
    }


def inspect_windows_app_local_readiness(repo_root: Path) -> dict[str, Any]:
    report = evaluate_windows_app_local_readiness(repo_root)
    reasons = [str(item) for item in report.get("blocking_reasons", []) if str(item).strip()]
    reasons.extend(str(item) for item in report.get("warning_reasons", []) if str(item).strip())
    return {
        "status": "PASS" if report.get("status") == "APP_READY" else "WARN" if report.get("status") == "APP_READY_WITH_WARNINGS" else "BLOCKED",
        "app_status": report.get("status"),
        "project_root": str(report.get("local_project_root", repo_root)),
        "reasons": reasons,
        "user_actions": [str(report.get("remaining_user_action", ""))] if report.get("remaining_user_action") else [],
    }


def inspect_repo_roots(roots: dict[str, Path]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    reasons: list[str] = []
    statuses: list[str] = []
    for name, path in sorted(roots.items()):
        exists = path.exists()
        if not is_windows_project_path(path):
            status = "BLOCKED"
            reason = "repo root is not on the Windows filesystem"
        elif is_legacy_linux_reference(path):
            status = "BLOCKED"
            reason = "repo root still references legacy Linux/remote runtime"
        else:
            status = "PASS" if exists else "BLOCKED"
            reason = "" if exists else "repo root is missing"
        findings.append({"name": name, "path": str(path), "exists": exists, "status": status, "reason": reason})
        statuses.append(status)
        if reason:
            reasons.append(f"{name}: {reason}")
    return {"status": collapse_status(statuses), "findings": findings, "reasons": reasons}


def inspect_toolchain() -> dict[str, Any]:
    required = {"git": "git", "python": "python", "node": "node", "npm": "npm", "pwsh": "pwsh"}
    optional = {"docker": "docker", "dotnet": "dotnet", "uv": "uv", "gh": "gh"}
    fallback_paths = {
        "gh": [Path(r"C:\Program Files\GitHub CLI\gh.exe")],
    }
    tools: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    reasons: list[str] = []
    for name, exe in required.items():
        path = shutil.which(exe)
        status = "PASS" if path else "BLOCKED"
        tools[name] = {"path": path or "", "status": status, "required": True}
        statuses.append(status)
        if not path:
            reasons.append(f"required tool is missing: {name}")
    for name, exe in optional.items():
        path = shutil.which(exe)
        if not path:
            path = next((str(candidate) for candidate in fallback_paths.get(name, []) if candidate.exists()), None)
        status = "PASS" if path else "WARN"
        tools[name] = {"path": path or "", "status": status, "required": False}
        statuses.append(status)
        if not path:
            reasons.append(f"optional tool is missing: {name}")
    return {"status": collapse_status(statuses), "tools": tools, "reasons": reasons}


def inspect_ai_python_packages() -> dict[str, Any]:
    packages: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    reasons: list[str] = []
    for role, distribution in AI_PYTHON_PACKAGE_DISTRIBUTIONS.items():
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = ""
        status = "PASS" if version else "BLOCKED"
        packages[role] = {"distribution": distribution, "version": version, "status": status}
        statuses.append(status)
        if not version:
            reasons.append(f"required Python AI package is missing: {distribution}")
    return {"status": collapse_status(statuses), "packages": packages, "reasons": reasons}


def inspect_powershell_profile() -> dict[str, Any]:
    profile_text = read_text(POWERSHELL_PROFILE)
    utf8_text = read_text(POWERSHELL_UTF8_POLICY)
    native_args_text = read_text(POWERSHELL_NATIVE_ARGS_POLICY)
    required_paths = [
        POWERSHELL_ROOT / "profile.d",
        POWERSHELL_ROOT / "Modules",
        POWERSHELL_ROOT / "policies",
        POWERSHELL_PROFILE,
        POWERSHELL_UTF8_POLICY,
        POWERSHELL_NATIVE_ARGS_POLICY,
    ]
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    required_profile_markers = [
        r'. "$PSScriptRoot\policies\utf8.ps1"',
        r'. "$PSScriptRoot\policies\native-args.ps1"',
    ]
    required_utf8_markers = [
        "[Console]::InputEncoding",
        "[Console]::OutputEncoding",
        "$OutputEncoding",
    ]
    required_native_args_markers = ["$PSNativeCommandArgumentPassing = 'Standard'"]
    missing_markers = [item for item in required_profile_markers if item not in profile_text]
    missing_markers.extend(item for item in required_utf8_markers if item not in utf8_text)
    missing_markers.extend(item for item in required_native_args_markers if item not in native_args_text)
    missing = missing_paths + missing_markers
    return {
        "status": "PASS" if not missing else "BLOCKED",
        "root": str(POWERSHELL_ROOT),
        "profile": str(POWERSHELL_PROFILE),
        "policies": {
            "utf8": str(POWERSHELL_UTF8_POLICY),
            "native_args": str(POWERSHELL_NATIVE_ARGS_POLICY),
        },
        "exists": POWERSHELL_PROFILE.exists(),
        "missing_paths": missing_paths,
        "missing_markers": missing,
        "reasons": [f"PowerShell profile missing required marker: {item}" for item in missing],
        "user_actions": [] if not missing else ["Create the PowerShell 7 profile.d, Modules, policies, UTF-8 policy, and native-argument policy surface."],
    }


def inspect_scratch_surface() -> dict[str, Any]:
    reasons: list[str] = []
    if not DEV_MANAGEMENT_SCRATCH.exists():
        reasons.append(f"external scratch root is missing: {DEV_MANAGEMENT_SCRATCH}")
    if REPO_SCRATCH.exists():
        reasons.append(f"repo-root scratch directory is forbidden: {REPO_SCRATCH}")
    return {
        "status": "BLOCKED" if reasons else "PASS",
        "external_scratch": str(DEV_MANAGEMENT_SCRATCH),
        "external_scratch_exists": DEV_MANAGEMENT_SCRATCH.exists(),
        "repo_root_scratch": str(REPO_SCRATCH),
        "repo_root_scratch_exists": REPO_SCRATCH.exists(),
        "reasons": reasons,
    }


def inspect_ssh_decommission() -> dict[str, Any]:
    exists = USER_SSH_ROOT.exists()
    return {
        "status": "BLOCKED" if exists else "PASS",
        "path": str(USER_SSH_ROOT),
        "exists": exists,
        "active_development_surface": False,
        "secret_values_reported": False,
        "reasons": [f"decommissioned SSH directory still exists: {USER_SSH_ROOT}"] if exists else [],
    }


def inspect_git_eol_policy(root_map: dict[str, Path]) -> dict[str, Any]:
    autocrlf = run_command(["git", "config", "--global", "--get", "core.autocrlf"])
    safecrlf = run_command(["git", "config", "--global", "--get", "core.safecrlf"])
    reasons: list[str] = []
    if str(autocrlf.get("stdout", "")).strip().lower() != "false":
        reasons.append("global core.autocrlf is not false")
    if str(safecrlf.get("stdout", "")).strip().lower() != "true":
        reasons.append("global core.safecrlf is not true")
    for name, root in sorted(root_map.items()):
        candidate_roots = [root]
        if not (root / ".git").exists():
            candidate_roots = [child for child in root.iterdir() if child.is_dir() and (child / ".git").exists()]
        if not candidate_roots:
            reasons.append(f"{name}: no Git repository found for EOL policy check")
            continue
        for repo in candidate_roots:
            attrs = repo / ".gitattributes"
            text = read_text(attrs)
            for marker in ("* text=auto eol=lf", "*.bat text eol=crlf", "*.cmd text eol=crlf", "*.ps1 text eol=crlf"):
                if marker not in text:
                    reasons.append(f"{repo}: .gitattributes missing {marker}")
    return {
        "status": "BLOCKED" if reasons else "PASS",
        "global_core_autocrlf": str(autocrlf.get("stdout", "")).strip(),
        "global_core_safecrlf": str(safecrlf.get("stdout", "")).strip(),
        "reasons": reasons,
    }


def inspect_decommission_gate(root_map: dict[str, Path]) -> dict[str, Any]:
    evidence_root = MIGRATION_EVIDENCE_ROOT
    required_repos = ("Dev-Management", "Dev-Workflow", "reservation-system")
    required_suffixes = ("status.txt", "remotes.txt", "branch.txt", "head.txt", "diffstat.txt", "untracked.txt")
    missing = [
        str(evidence_root / f"{repo}.{suffix}")
        for repo in required_repos
        for suffix in required_suffixes
        if not (evidence_root / f"{repo}.{suffix}").exists()
    ]
    windows_roots_ready = all(path.exists() and is_windows_project_path(path) for path in root_map.values())
    reasons: list[str] = []
    if missing:
        reasons.append("migration evidence is incomplete")
    if not windows_roots_ready:
        reasons.append("Windows canonical roots are not all present")
    return {
        "status": "BLOCKED" if reasons else "PASS",
        "evidence_root": str(evidence_root),
        "missing_evidence_files": missing,
        "windows_roots_ready": windows_roots_ready,
        "legacy_runtime_delete_allowed_by_gate": not reasons,
        "legacy_runtime_delete_performed": True,
        "reasons": reasons,
        "user_actions": [
            "Migration evidence is preserved under C:\\Users\\anise\\code\\Dev-Management\\reports\\migration-evidence."
        ],
    }


def inspect_path_authority_consistency(path_policy: dict[str, Any]) -> dict[str, Any]:
    env_alignment = validate_env_alignment(path_policy)
    mismatches = [
        f"{item['env_var']}: expected {item['expected']}, observed {item['actual']}"
        for item in env_alignment.get("findings", [])
        if item.get("status") == "MISMATCH"
    ]
    return {
        "status": "BLOCKED" if mismatches else "PASS",
        "expected": env_alignment.get("expected", {}),
        "findings": env_alignment.get("findings", []),
        "reasons": mismatches,
    }


def classify_docker_bind_sources(mounts: list[dict[str, Any]]) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []
    accepted: list[dict[str, str]] = []
    for mount in mounts:
        if str(mount.get("Type", "")).strip() != "bind":
            continue
        source = str(mount.get("Source", "")).strip()
        target = str(mount.get("Destination", "")).strip()
        item = {"source": source, "target": target}
        if is_legacy_linux_reference(source):
            warnings.append(item)
        else:
            accepted.append(item)
    return {
        "status": "WARN" if warnings else "PASS",
        "warnings": warnings,
        "accepted": accepted,
        "reasons": [f"docker bind mount still references decommissioned Linux path: {item['source']}" for item in warnings],
    }


def inspect_execution_route(global_runtime: dict[str, Any]) -> dict[str, Any]:
    mode_selected = str(global_runtime.get("mode_selected", "")).strip()
    if mode_selected in {"local", "local-windows", "windows-native"}:
        return {"status": "PASS", "mode_selected": mode_selected, "reasons": []}
    return {
        "status": "BLOCKED",
        "mode_selected": mode_selected,
        "reasons": [f"execution route is {mode_selected or 'unset'}, expected local Windows-native execution."],
        "user_actions": ["Switch Codex App agent to Windows native and open the Windows local project root."],
    }


def inspect_linux_native_codex(global_runtime: dict[str, Any]) -> dict[str, Any]:
    values = json.dumps(global_runtime, ensure_ascii=False)
    if is_legacy_linux_reference(values):
        return {"status": "BLOCKED", "reasons": ["Legacy Linux/remote Codex runtime references are decommissioned."]}
    return {"status": "PASS", "reasons": []}


def recommended_setup(path_policy: dict[str, Any]) -> list[str]:
    roots = canonical_roots(path_policy)
    return [
        "Use OpenAI Codex App on Windows as the UI and execution control plane.",
        "Use Windows-native agent with PowerShell 7.",
        f"Open Dev-Management locally from {roots.get('dev_management', ROOT)}.",
        "Keep repo-specific stack and workflow authority in repo AGENTS.md and package scripts.",
        "Treat Docker as optional build/verification/packaging/integration support, not canonical local execution.",
        "Keep migration evidence until the user explicitly removes migration records.",
    ]


def collect_current_deviations(checks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    deviations: list[dict[str, Any]] = []
    for name, payload in checks.items():
        status = str(payload.get("status", "PASS"))
        if status == "PASS":
            continue
        reasons = [str(item) for item in payload.get("reasons", []) if str(item).strip()]
        deviations.append({"check": name, "status": status, "reasons": reasons})
    return deviations


def evaluate_user_dev_environment(repo_root: str | Path | None = None, *, live_ssh_probe: bool = False) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    user_policy = load_policy(root)
    path_policy = load_path_policy(root)
    root_map = canonical_roots(path_policy)
    checks: dict[str, dict[str, Any]] = {
        "windows_codex_boundary": inspect_windows_codex_boundary(user_policy, path_policy),
        "windows_app_local_readiness": inspect_windows_app_local_readiness(root),
        "repo_roots": inspect_repo_roots(root_map),
        "toolchain": inspect_toolchain(),
        "ai_python_packages": inspect_ai_python_packages(),
        "powershell_profile": inspect_powershell_profile(),
        "scratch_surface": inspect_scratch_surface(),
        "ssh_decommission": inspect_ssh_decommission(),
        "git_eol_policy": inspect_git_eol_policy(root_map),
        "path_authority_consistency": inspect_path_authority_consistency(path_policy),
        "decommission_gate": inspect_decommission_gate(root_map),
    }
    status = collapse_status([payload.get("status", "PASS") for payload in checks.values()])
    deviations = collect_current_deviations(checks)
    report = {
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": user_policy.get("version", 1),
        "environment": {
            "repo_root": str(root),
            "canonical_execution_host": str(path_policy.get("canonical_execution_host", "local-windows")),
            "windows_codex_home": str(windows_codex_home(path_policy)),
            "expected_repo_root_prefix": r"C:\Users\anise\code",
            "current_working_directory": os.getcwd(),
        },
        "checks": checks,
        "recommended_setup": recommended_setup(path_policy),
        "current_deviations": deviations,
        "production_readiness": {
            "status": "READY" if status == "PASS" else "READY_WITH_WARNINGS" if status == "WARN" else "NOT_READY",
            "summary": "Windows-native development environment baseline is ready." if status == "PASS" else (deviations[0]["reasons"][0] if deviations and deviations[0]["reasons"] else "Deviations remain."),
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# User Dev Environment Baseline",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Production readiness: {report.get('production_readiness', {}).get('status', 'NOT_READY')}",
        f"- Canonical execution host: {report.get('environment', {}).get('canonical_execution_host', 'local-windows')}",
        f"- Expected repo root prefix: {report.get('environment', {}).get('expected_repo_root_prefix', '')}",
        "",
        "## Final Recommended Setup",
    ]
    lines.extend(f"- {item}" for item in report.get("recommended_setup", []))
    lines.extend(["", "## Current Deviations"])
    deviations = report.get("current_deviations", [])
    if deviations:
        for item in deviations:
            detail = "; ".join(str(reason) for reason in item.get("reasons", []) if str(reason).strip()) or "No detail recorded."
            lines.append(f"- [{item.get('status', 'WARN')}] {item.get('check', 'unknown')}: {detail}")
    else:
        lines.append("- No current deviations detected.")
    return "\n".join(lines) + "\n"


def write_reports(report: dict[str, Any], *, output_file: Path | None = None) -> None:
    save_json(DEFAULT_OUTPUT_PATH, report)
    write_markdown(DEFAULT_MARKDOWN_PATH, render_markdown(report))
    if output_file is not None and output_file.resolve() != DEFAULT_OUTPUT_PATH.resolve():
        save_json(output_file, report)
        write_markdown(output_file.with_suffix(".md"), render_markdown(report))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the Windows-native Codex App user development environment baseline.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-file")
    parser.add_argument("--live-ssh-probe", action="store_true", help="accepted for CLI compatibility; ignored in Windows-only mode")
    args = parser.parse_args()
    report = evaluate_user_dev_environment(args.repo_root, live_ssh_probe=args.live_ssh_probe)
    output_file = Path(args.output_file).expanduser().resolve() if args.output_file else None
    write_reports(report, output_file=output_file)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report.get("status", "WARN"))


if __name__ == "__main__":
    raise SystemExit(main())
