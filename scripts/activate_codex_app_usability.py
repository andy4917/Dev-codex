#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.paths import canonical_surface
from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import status_exit_code
from devmgmt_runtime.subprocess_safe import run_ssh
from check_artifact_hygiene import evaluate_artifact_hygiene
from check_active_config_smoke import evaluate_active_config_smoke, render_markdown as render_active_config_markdown
from check_config_provenance import evaluate_config_provenance, render_markdown as render_config_markdown
from check_global_runtime import evaluate_global_runtime
from check_git_surface import evaluate_git_surfaces, render_text_summary as render_git_surface_summary
from check_hook_readiness import evaluate_hook_readiness, render_markdown as render_hook_markdown
from check_startup_workflow import evaluate_startup_workflow
from check_toolchain_surface import evaluate_toolchain_surface, render_markdown as render_toolchain_markdown
from check_windows_app_ssh_readiness import (
    WINDOWS_APP_AGENTS,
    WINDOWS_APP_CONFIG,
    bootstrap_status as inspect_windows_app_bootstrap,
    evaluate_windows_app_ssh_readiness,
    reassess_report as reassess_windows_readiness,
    render_markdown as render_windows_markdown,
)
from repair_codex_desktop_runtime import repair_linux_launcher_shim
from repair_serena_startup import repair_serena
from run_score_layer import evaluate_score_layer, render_markdown as render_score_markdown


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "app-usability.final-dry-run.json"
APP_POLICY_PATH = ROOT / "contracts" / "app_surface_policy.json"
LINUX_CODEX_PREFIX = Path("/home/andy4917/.local/share/dev-management/codex-npm")
REQUIRED_WINDOWS_BOOTSTRAP_FEATURES = ("remote_control", "remote_connections")


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_app_policy() -> dict[str, Any]:
    return load_json(APP_POLICY_PATH, default={})


def save_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _find_toml_section_bounds(lines: list[str], header: str) -> tuple[int | None, int]:
    start: int | None = None
    end = len(lines)
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped == header:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break
    return start, end


def ensure_windows_bootstrap_features(config_text: str) -> tuple[str, bool]:
    required_lines = [f"{feature} = true" for feature in REQUIRED_WINDOWS_BOOTSTRAP_FEATURES]
    if not config_text.strip():
        return "[features]\n" + "\n".join(required_lines) + "\n", True

    lines = config_text.splitlines()
    changed = False
    section_start, section_end = _find_toml_section_bounds(lines, "[features]")

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[features]", *required_lines])
        changed = True
    else:
        feature_indexes: dict[str, int] = {}
        for index in range(section_start + 1, section_end):
            candidate = lines[index].split("#", 1)[0].strip()
            if "=" not in candidate:
                continue
            key = candidate.split("=", 1)[0].strip()
            if key in REQUIRED_WINDOWS_BOOTSTRAP_FEATURES and key not in feature_indexes:
                feature_indexes[key] = index

        insert_at = section_end
        for feature in REQUIRED_WINDOWS_BOOTSTRAP_FEATURES:
            desired_line = f"{feature} = true"
            existing_index = feature_indexes.get(feature)
            if existing_index is None:
                lines.insert(insert_at, desired_line)
                insert_at += 1
                changed = True
                continue
            if lines[existing_index].strip() != desired_line:
                lines[existing_index] = desired_line
                changed = True

    rendered = "\n".join(lines)
    if config_text.endswith("\n") or not rendered.endswith("\n"):
        rendered += "\n"
    return rendered, changed


def normalize_windows_app_bootstrap(*, apply: bool, force_minimal: bool) -> dict[str, Any]:
    before = inspect_windows_app_bootstrap()
    actions_applied: list[str] = []
    actions_planned: list[str] = []
    backups_created: list[str] = []
    changed_files: list[str] = []
    config_needs_repair = force_minimal and before.get("bootstrap_features_ready") is not True
    inert_agents_present = bool(before.get("agents_is_inert_empty"))

    if config_needs_repair:
        actions_planned.append("Do not auto-repair Windows Codex App bootstrap config; classify it as external app or user state and remove stale Dev-Management residue separately")
    if inert_agents_present:
        actions_planned.append("Remove inert empty Windows AGENTS residue")

    if apply:
        if inert_agents_present:
            WINDOWS_APP_AGENTS.unlink()
            actions_applied.append("Removed inert empty Windows AGENTS residue")
            changed_files.append(str(WINDOWS_APP_AGENTS))

    after = inspect_windows_app_bootstrap()
    status = str(after.get("status", "WARN"))
    return {
        "status": status,
        "force_minimal": force_minimal,
        "applied": bool(actions_applied),
        "actions_planned": actions_planned,
        "actions_applied": actions_applied,
        "backups_created": backups_created,
        "changed_files": changed_files,
        "before": before,
        "after": after,
    }


def build_single_ui_action(steps: dict[str, Any], host_alias: str, remote_project: str) -> str:
    settings_path = str(steps.get("settings_path", "Settings > Connections")).strip() or "Settings > Connections"
    manual_add_path = str(steps.get("manual_add_host_path", f"Connections > Add host > {host_alias}")).strip() or f"Connections > Add host > {host_alias}"
    return (
        f"Codex App를 완전히 재시작하고 {settings_path}에서 {host_alias}를 선택하거나 "
        f"{manual_add_path}로 추가한 뒤 {remote_project}가 실제로 열리는지 확인해 달라."
    )


def app_server_capability_probe(host_alias: str) -> dict[str, Any]:
    return run_ssh(host_alias, "codex app-server --help")


def wsl_fallback_probe() -> dict[str, Any]:
    command = "Test-Path '\\\\wsl.localhost\\Ubuntu\\home\\andy4917\\Dev-Management'"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    return {
        "ok": result.returncode == 0 and result.stdout.strip().lower() == "true",
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
        "path": r"\\wsl.localhost\Ubuntu\home\andy4917\Dev-Management",
    }


def build_candidate(
    candidate_id: str,
    label: str,
    *,
    status: str,
    evidence: list[str],
    repairable_by_agent: bool,
    action_taken: str,
    result: str,
    remaining_user_action: str = "",
) -> dict[str, Any]:
    return {
        "id": candidate_id,
        "label": label,
        "status": status,
        "evidence": evidence,
        "repairable_by_agent": repairable_by_agent,
        "action_taken": action_taken,
        "result": result,
        "remaining_user_action": remaining_user_action,
    }


def build_app_remote_access_blocker_analysis(
    *,
    root: Path,
    windows: dict[str, Any],
    runtime: dict[str, Any],
    bootstrap: dict[str, Any],
    host_alias: str,
    remote_project: str,
    ui_action: str,
) -> dict[str, Any]:
    ssh_resolve = windows.get("ssh_config_resolve", {}) if isinstance(windows.get("ssh_config_resolve"), dict) else {}
    route_d = wsl_fallback_probe()
    route_e = app_server_capability_probe(host_alias)
    project_status = str(windows.get("app_remote_project_status", "UNOBSERVED"))
    manual_add = windows.get("manual_add_host_worked")
    listed = windows.get("app_host_listed_in_connections")
    bootstrap_after = bootstrap.get("after", {}) if isinstance(bootstrap.get("after"), dict) else {}
    bootstrap_changed = bool(bootstrap.get("applied"))
    remote_codex = runtime.get("remote_native_codex_status", {}) if isinstance(runtime.get("remote_native_codex_status"), dict) else {}
    transport_ready = str(windows.get("ssh_transport_status", "BLOCKED")) == "PASS"
    runtime_ready = str(runtime.get("canonical_execution_status", "BLOCKED")) == "PASS"
    remote_codex_ready = str(remote_codex.get("status", "WARN")) == "PASS"
    policy_surfaces_absent = (
        WINDOWS_APP_CONFIG.exists() is False
        and
        WINDOWS_APP_AGENTS.exists() is False
        and not (WINDOWS_APP_CONFIG.parent / "hooks.json").exists()
        and not (WINDOWS_APP_CONFIG.parent / "skills" / "dev-workflow").exists()
    )
    candidates = [
        build_candidate(
            "A",
            "Windows SSH config issue",
            status="PASS" if bool(windows.get("host_alias_visible_to_codex_app_discovery")) else "BLOCKED",
            evidence=[
                f"windows_ssh_config={windows.get('windows_ssh_config', '')}",
                f"identity_file={windows.get('identity_file', '')}",
                f"aliases={','.join(windows.get('concrete_top_level_host_aliases', []))}",
            ],
            repairable_by_agent=True,
            action_taken="Repaired managed Host devmgmt-wsl block" if windows.get("applied") else "Inspected concrete Host devmgmt-wsl block",
            result="Concrete top-level host alias is present." if bool(windows.get("host_alias_visible_to_codex_app_discovery")) else "Concrete top-level host alias is missing.",
            remaining_user_action="" if bool(windows.get("host_alias_visible_to_codex_app_discovery")) else ui_action,
        ),
        build_candidate(
            "B",
            "Windows OpenSSH issue",
            status="PASS" if transport_ready and bool(ssh_resolve.get("ok")) else "BLOCKED",
            evidence=[
                f"ssh_config_resolve_ok={bool(ssh_resolve.get('ok'))}",
                f"ssh_transport_status={windows.get('ssh_transport_status', 'BLOCKED')}",
            ],
            repairable_by_agent=False,
            action_taken="Verified ssh.exe config resolution and transport probe",
            result="Windows OpenSSH resolves and connects to devmgmt-wsl." if transport_ready and bool(ssh_resolve.get("ok")) else "Windows OpenSSH still fails to resolve or connect to devmgmt-wsl.",
            remaining_user_action="" if transport_ready and bool(ssh_resolve.get("ok")) else ui_action,
        ),
        build_candidate(
            "C",
            "Codex App bootstrap feature flags missing",
            status="PASS" if bootstrap_after.get("bootstrap_features_ready") else "BLOCKED",
            evidence=[
                f"config_path={bootstrap_after.get('config_path', str(WINDOWS_APP_CONFIG))}",
                f"remote_control_enabled={bootstrap_after.get('remote_control_enabled', False)}",
                f"remote_connections_enabled={bootstrap_after.get('remote_connections_enabled', False)}",
                f"minimal_bootstrap={bootstrap_after.get('minimal_bootstrap', False)}",
            ],
            repairable_by_agent=False,
            action_taken="Removed inert Windows AGENTS residue" if bootstrap_changed else "Inspected Windows app bootstrap config without editing external app state",
            result=(
                "remote_control=true and remote_connections=true are enabled in the Windows app bootstrap config, but Dev-Management does not preserve or repair this file."
                if bootstrap_after.get("bootstrap_features_ready")
                else "Windows app bootstrap config is missing remote_control=true or remote_connections=true."
            ),
            remaining_user_action="" if bootstrap_after.get("bootstrap_features_ready") else ui_action,
        ),
        build_candidate(
            "D",
            "Codex App not fully restarted",
            status="UNOBSERVED" if bootstrap_changed and project_status != "OPENED" else "PASS" if project_status == "OPENED" else "UNOBSERVED",
            evidence=[f"bootstrap_changed={bootstrap_changed}", f"app_remote_project_status={project_status}"],
            repairable_by_agent=False,
            action_taken="Prepared restart-required bootstrap repair" if bootstrap_changed else "No bootstrap restart dependency introduced",
            result="A full app restart is still required to validate the repaired bootstrap." if bootstrap_changed and project_status != "OPENED" else "No restart blocker remains in the observed evidence." if project_status == "OPENED" else "App restart state has not been re-observed yet.",
            remaining_user_action=ui_action if project_status != "OPENED" else "",
        ),
        build_candidate(
            "E",
            "Connections UI cannot auto-discover host",
            status="PASS" if listed is True else "WARN" if manual_add is True else "BLOCKED" if manual_add is False else "UNOBSERVED",
            evidence=[f"app_host_listed_in_connections={listed}", f"manual_add_host_worked={manual_add}"],
            repairable_by_agent=False,
            action_taken="Classified UI host discovery from user evidence",
            result="Host auto-discovery works." if listed is True else "Host auto-discovery failed but manual add worked." if manual_add is True else "Host auto-discovery failed and manual add also failed." if manual_add is False else "UI discovery result has not been re-observed.",
            remaining_user_action=ui_action if listed is not True else "",
        ),
        build_candidate(
            "F",
            "Manual Add host failure",
            status="PASS" if manual_add is True or listed is True else "BLOCKED" if manual_add is False else "UNOBSERVED",
            evidence=[f"manual_add_host_worked={manual_add}"],
            repairable_by_agent=False,
            action_taken="Classified manual Add host result from user evidence",
            result="Manual Add host is no longer needed or it worked." if manual_add is True or listed is True else "Manual Add host failed." if manual_add is False else "Manual Add host has not been re-observed.",
            remaining_user_action=ui_action if manual_add is not True and listed is not True else "",
        ),
        build_candidate(
            "G",
            "Remote project path selection failure",
            status="PASS" if project_status == "OPENED" else "BLOCKED" if project_status == "NOT_OPENED" else "UNOBSERVED",
            evidence=[f"app_remote_project_status={project_status}", f"app_remote_project_path={remote_project}"],
            repairable_by_agent=False,
            action_taken="Required explicit project-open proof in readiness evidence",
            result="Codex App opened the canonical remote project." if project_status == "OPENED" else "Codex App did not open the canonical remote project." if project_status == "NOT_OPENED" else "Project-open proof is still missing.",
            remaining_user_action=ui_action if project_status != "OPENED" else "",
        ),
        build_candidate(
            "H",
            "Remote app-server startup failure",
            status="PASS" if project_status == "OPENED" and remote_codex_ready else "UNOBSERVED" if route_e.get("ok") else "WARN",
            evidence=[f"app_server_help_ok={route_e.get('ok')}", f"remote_codex_status={remote_codex.get('status', 'WARN')}"],
            repairable_by_agent=False,
            action_taken="Verified codex app-server capability without exposing a listener",
            result="Remote codex supports app-server tooling and the project-open proof supersedes startup suspicion." if project_status == "OPENED" and remote_codex_ready else "Remote codex exposes app-server help, but app-side startup is still unobserved." if route_e.get("ok") else "codex app-server capability probe did not return successfully.",
            remaining_user_action=ui_action if project_status != "OPENED" else "",
        ),
        build_candidate(
            "I",
            "Remote authentication issue",
            status="PASS" if project_status == "OPENED" else "UNOBSERVED",
            evidence=[f"auth_surface_ready={transport_ready}", f"app_remote_project_status={project_status}"],
            repairable_by_agent=False,
            action_taken="Reserved auth blocker classification for explicit sign-in evidence only",
            result="No auth blocker remained once the project opened." if project_status == "OPENED" else "No sign-in blocker has been observed yet.",
            remaining_user_action=ui_action if project_status != "OPENED" else "",
        ),
        build_candidate(
            "J",
            "App-side bug / external app state",
            status="BLOCKED" if transport_ready and bootstrap_after.get("bootstrap_features_ready") and manual_add is False else "UNOBSERVED",
            evidence=[
                f"ssh_transport_status={windows.get('ssh_transport_status', 'BLOCKED')}",
                f"bootstrap_features_ready={bootstrap_after.get('bootstrap_features_ready', False)}",
                f"manual_add_host_worked={manual_add}",
            ],
            repairable_by_agent=False,
            action_taken="Separated SSH/bootstrap remediation from app-only failure classification",
            result="If manual Add host still fails after SSH PASS and both required bootstrap features are enabled, the remaining blocker is app-side external state." if transport_ready and bootstrap_after.get("bootstrap_features_ready") and manual_add is False else "App-only external state is not yet proven because post-repair UI evidence is still missing.",
            remaining_user_action=ui_action if project_status != "OPENED" else "",
        ),
        build_candidate(
            "K",
            "Dev-Management regression",
            status="PASS" if runtime_ready and remote_codex_ready and policy_surfaces_absent else "BLOCKED",
            evidence=[
                f"canonical_execution_status={runtime.get('canonical_execution_status', 'BLOCKED')}",
                f"remote_native_codex_status={remote_codex.get('status', 'WARN')}",
                f"windows_policy_surfaces_absent={policy_surfaces_absent}",
            ],
            repairable_by_agent=True,
            action_taken="Verified Dev-Management readiness tooling against canonical runtime and Windows policy surfaces",
            result="Dev-Management keeps Linux-native codex and does not recreate forbidden Windows policy mirrors." if runtime_ready and remote_codex_ready and policy_surfaces_absent else "Readiness tooling or Windows policy surface behavior regressed.",
            remaining_user_action="" if runtime_ready and remote_codex_ready and policy_surfaces_absent else ui_action,
        ),
    ]
    routes = [
        {
            "id": "A",
            "label": "Connections auto-listed host",
            "status": "supported" if listed is True else "unsupported" if listed is False else "unobservable",
            "evidence": f"app_host_listed_in_connections={listed}",
            "satisfies_hard_acceptance": listed is True and project_status == "OPENED",
        },
        {
            "id": "B",
            "label": "Connections manual Add host",
            "status": "supported" if manual_add is True else "unsupported" if manual_add is False else "unobservable",
            "evidence": f"manual_add_host_worked={manual_add}",
            "satisfies_hard_acceptance": manual_add is True and project_status == "OPENED",
        },
        {
            "id": "C",
            "label": "Direct remote project open after host exists",
            "status": "supported" if project_status == "OPENED" else "unsupported" if project_status == "NOT_OPENED" else "unobservable",
            "evidence": f"app_remote_project_status={project_status}",
            "satisfies_hard_acceptance": project_status == "OPENED",
        },
        {
            "id": "D",
            "label": "WSL filesystem fallback",
            "status": "supported" if route_d.get("ok") else "unsupported",
            "evidence": f"path={route_d.get('path', '')}",
            "satisfies_hard_acceptance": False,
        },
        {
            "id": "E",
            "label": "CLI app-server diagnostic fallback",
            "status": "supported" if route_e.get("ok") else "unsupported",
            "evidence": "codex app-server --help",
            "satisfies_hard_acceptance": False,
        },
    ]
    unresolved = [
        item
        for item in candidates
        if str(item.get("status")) in {"BLOCKED", "UNOBSERVED", "WARN"}
        and str(item.get("id")) not in {"D", "H", "I"}
    ]
    status = "PASS" if project_status == "OPENED" and remote_codex_ready else "BLOCKED"
    return {
        "status": status,
        "host_alias": host_alias,
        "remote_project_path": remote_project,
        "ssh_transport_status": windows.get("ssh_transport_status", "BLOCKED"),
        "app_remote_project_status": project_status,
        "remote_codex_status": remote_codex.get("status", "WARN"),
        "bootstrap_status": bootstrap.get("status", "WARN"),
        "candidates": candidates,
        "routes": routes,
        "remaining_user_action": "" if project_status == "OPENED" and remote_codex_ready else ui_action,
        "unresolved_candidates": [item["id"] for item in unresolved],
        "evidence_refs": [
            str(root / "reports" / "windows-app-ssh-remote-readiness.final.json"),
            str(root / "reports" / "global-runtime.final.json"),
            str(WINDOWS_APP_CONFIG),
            str(WINDOWS_APP_AGENTS),
            str(root / "reports" / "codex-app-usability-final.json"),
        ],
    }


def render_blocker_analysis_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# App Remote Access Blocker Analysis",
        "",
        f"- Status: {report.get('status', 'BLOCKED')}",
        f"- Host alias: {report.get('host_alias', 'devmgmt-wsl')}",
        f"- Remote project path: {report.get('remote_project_path', '')}",
        f"- SSH transport: {report.get('ssh_transport_status', 'BLOCKED')}",
        f"- App remote project: {report.get('app_remote_project_status', 'UNOBSERVED')}",
        f"- Remote codex: {report.get('remote_codex_status', 'WARN')}",
        f"- Bootstrap status: {report.get('bootstrap_status', 'WARN')}",
    ]
    if report.get("remaining_user_action"):
        lines.append(f"- Remaining user action: {report['remaining_user_action']}")
    lines.extend(["", "## Candidates"])
    for item in report.get("candidates", []):
        lines.append(f"- {item['id']}. {item['label']}: {item['status']} - {item['result']}")
    lines.extend(["", "## Routes"])
    for route in report.get("routes", []):
        lines.append(
            f"- Route {route['id']}: {route['label']} => {route['status']} (hard acceptance: {str(route['satisfies_hard_acceptance']).lower()})"
        )
    return "\n".join(lines) + "\n"


def install_linux_codex_cli(*, host_alias: str, allow_install: bool, runtime: dict[str, Any]) -> dict[str, Any]:
    remote_native = runtime.get("remote_native_codex_status", {})
    if str(remote_native.get("status", "WARN")) == "PASS":
        return {
            "status": "PASS",
            "applied": False,
            "path": str(remote_native.get("selected_path", "")),
            "version": str(remote_native.get("version", "")),
            "reason": "Linux-native Codex CLI is already present on the canonical remote PATH.",
        }
    if not allow_install:
        return {
            "status": "WARN",
            "applied": False,
            "path": str(LINUX_CODEX_PREFIX / "bin" / "codex"),
            "version": "",
            "reason": "Linux-native Codex CLI install is allowed only when --allow-linux-codex-install is passed.",
        }
    if str(runtime.get("canonical_execution_status", "BLOCKED")) != "PASS":
        return {
            "status": "BLOCKED",
            "applied": False,
            "path": str(LINUX_CODEX_PREFIX / "bin" / "codex"),
            "version": "",
            "reason": "Canonical SSH runtime is not ready for Linux-native Codex CLI installation.",
        }
    command = (
        'set -eu; '
        'PREFIX="$HOME/.local/share/dev-management/codex-npm"; '
        'mkdir -p "$PREFIX"; '
        'npm install --prefix "$PREFIX" -g @openai/codex@latest; '
        '"$PREFIX/bin/codex" --version'
    )
    cached_probe = runtime.get("canonical_ssh_probe_cache", {})
    cache_ready = (
        isinstance(cached_probe, dict)
        and str(cached_probe.get("host_alias", "")).strip() == host_alias
        and str(cached_probe.get("status", "")).strip() == "PASS"
    )
    result = run_ssh(host_alias, command, cwd=cached_probe.get("repo_root") if cache_ready else None)
    version = str(result.get("stdout", "")).strip().splitlines()
    return {
        "status": "PASS" if result.get("ok") else "BLOCKED",
        "applied": bool(result.get("ok")),
        "path": str(LINUX_CODEX_PREFIX / "bin" / "codex"),
        "version": version[-1] if version else "",
        "reason": "" if result.get("ok") else str(result.get("stderr", "")).strip(),
    }


def render_app_usability_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Codex App Usability",
        "",
        f"- Status: {report['status']}",
        f"- Windows App SSH readiness: {report['windows_app_ssh_status']}",
        f"- Canonical SSH runtime: {report['canonical_ssh_runtime_status']}",
        f"- Remote codex: {report['remote_codex_status']}",
        f"- App remote project: {report.get('app_remote_project_status', 'UNOBSERVED')}",
        f"- App remote project path: {report.get('app_remote_project_path', '')}",
        f"- Linux-native Codex CLI: {report['linux_native_codex_cli_status']}",
        f"- Config provenance: {report['config_provenance_status']}",
        f"- Active config smoke: {report['active_config_smoke_status']}",
        f"- Windows policy surface: {report['windows_policy_surface_status']}",
        f"- Windows app evidence: {report['windows_app_evidence_status']}",
        f"- Windows app bootstrap: {report.get('windows_app_bootstrap_status', 'WARN')}",
        f"- Control thread: {report.get('control_thread_status', 'WARN')}",
        f"- Canonical repo root: {report.get('canonical_repo_root', '')}",
        f"- Active worktree root: {report.get('active_worktree_root', '')}",
        f"- Auth readiness: {report['auth_status']}",
        f"- Serena status: {report['serena_status']}",
        f"- Git surface: {report.get('git_surface_status', 'WARN')}",
        f"- Score status: {report['score_status']}",
        f"- Audit status: {report['audit_status']}",
        f"- Windows SSH probe source: {report.get('windows_app_ssh_probe_source', 'unknown')}",
        f"- Windows SSH cache status: {report.get('windows_app_ssh_cache_status', 'unknown')}",
    ]
    if report.get("status_reasons"):
        lines.extend(["", "## Status Reasons"])
        lines.extend(f"- {item}" for item in report["status_reasons"])
    if report.get("user_action_required"):
        lines.extend(["", "## User Actions"])
        lines.extend(f"- {item}" for item in report["user_action_required"])
    return "\n".join(lines) + "\n"


def run_audit_cli(
    root: Path,
    *,
    purpose: str,
    output_file: Path,
    windows_ssh_readiness_report: Path | None = None,
) -> dict[str, Any]:
    command = [
        "python3",
        str(root / "scripts" / "audit_workspace.py"),
        "--json",
        "--purpose",
        purpose,
        "--output-file",
        str(output_file),
    ]
    if windows_ssh_readiness_report is not None:
        command.extend(
            [
                "--windows-ssh-readiness-report",
                str(windows_ssh_readiness_report),
                "--no-live-windows-ssh-probe",
            ]
        )
    result = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", cwd=str(root))
    if output_file.exists():
        return load_json(output_file, default={})
    if result.stdout.strip():
        return json.loads(result.stdout)
    return {"status": "FAIL", "gate_status": "BLOCKED", "reason": result.stderr.strip() or "audit failed to run"}


def evaluate_app_usability(
    repo_root: str | Path | None = None,
    *,
    apply_user_level: bool = False,
    allow_linux_codex_install: bool = False,
    refresh_windows_ssh: bool = False,
    windows_ssh_readiness_report: str | Path | None = None,
    no_live_windows_ssh_probe: bool = False,
    app_host_listed_in_connections: bool | None = None,
    manual_add_host_worked: bool | None = None,
    app_remote_project_opened: bool | None = None,
    app_remote_project_not_opened: bool | None = None,
    app_remote_project_unobserved: bool | None = None,
    app_remote_project_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    authority = load_authority(root)
    app_policy = load_app_policy()
    reports_root = root / "reports"
    reports_created: list[str] = []
    files_touched: list[str] = []
    backups_created: list[str] = []
    agent_actions_applied: list[str] = []
    agent_actions_skipped: list[str] = []

    windows_path = Path(windows_ssh_readiness_report).expanduser().resolve() if windows_ssh_readiness_report else reports_root / "windows-app-ssh-remote-readiness.final.json"
    windows = evaluate_windows_app_ssh_readiness(
        root,
        apply_user_level=apply_user_level,
        refresh_windows_ssh=refresh_windows_ssh,
        windows_ssh_readiness_report=windows_path,
        no_live_windows_ssh_probe=no_live_windows_ssh_probe,
        allow_cache_miss_live_probe=False,
        app_host_listed_in_connections=app_host_listed_in_connections,
        manual_add_host_worked=manual_add_host_worked,
        app_remote_project_opened=app_remote_project_opened,
        app_remote_project_not_opened=app_remote_project_not_opened,
        app_remote_project_unobserved=app_remote_project_unobserved,
        app_remote_project_path=str(app_remote_project_path or root),
    )
    bootstrap_force_minimal = (
        str(windows.get("ssh_transport_status", windows.get("status", "BLOCKED"))) == "PASS"
        and str(windows.get("blocking_domain", "none")) in {"app_discovery", "app_bootstrap"}
    )
    bootstrap = normalize_windows_app_bootstrap(apply=apply_user_level, force_minimal=bootstrap_force_minimal)
    if bootstrap.get("applied"):
        files_touched.extend(item for item in bootstrap.get("changed_files", []) if item)
        backups_created.extend(item for item in bootstrap.get("backups_created", []) if item)
        agent_actions_applied.extend(str(item) for item in bootstrap.get("actions_applied", []))
        windows = reassess_windows_readiness(windows)
    else:
        agent_actions_skipped.extend(str(item) for item in bootstrap.get("actions_planned", []))
    save_json(windows_path, windows)
    save_markdown(windows_path.with_suffix(".md"), render_windows_markdown(windows))
    reports_created.extend([str(windows_path), str(windows_path.with_suffix(".md"))])
    files_touched.extend([windows["windows_ssh_config"]] if windows.get("applied") else [])
    backups_created.extend(windows.get("backups", []))
    if windows.get("applied"):
        agent_actions_applied.append("Windows user SSH alias repaired")
    else:
        agent_actions_skipped.append("Windows user SSH alias unchanged")

    runtime = evaluate_global_runtime(
        root,
        windows_app_ssh_readiness=windows,
        windows_ssh_readiness_report=windows_path,
        no_live_windows_ssh_probe=True,
    )
    runtime_path = reports_root / "global-runtime.final.json"
    save_json(runtime_path, runtime)
    reports_created.append(str(runtime_path))
    save_json(root / "reports" / "global-runtime.json", runtime)

    config = evaluate_config_provenance(root)
    config_path = reports_root / "config-provenance.final.json"
    save_json(config_path, config)
    save_markdown(config_path.with_suffix(".md"), render_config_markdown(config))
    reports_created.extend([str(config_path), str(config_path.with_suffix(".md"))])

    active_config = evaluate_active_config_smoke(root)
    active_config_path = reports_root / "active-config-smoke.final.json"
    save_json(active_config_path, active_config)
    save_markdown(active_config_path.with_suffix(".md"), render_active_config_markdown(active_config))
    reports_created.extend([str(active_config_path), str(active_config_path.with_suffix(".md"))])

    toolchain = evaluate_toolchain_surface(root)
    toolchain_path = reports_root / "toolchain-surface.final.json"
    save_json(toolchain_path, toolchain)
    save_markdown(toolchain_path.with_suffix(".md"), render_toolchain_markdown(toolchain))
    reports_created.extend([str(toolchain_path), str(toolchain_path.with_suffix(".md"))])

    git_surface = evaluate_git_surfaces()
    management_git_report = next((item for item in git_surface.get("repo_reports", []) if str(item.get("repo_root", "")).endswith("/Dev-Management")), {})
    git_surface_path = reports_root / "git-surface.final.json"
    save_json(git_surface_path, git_surface)
    save_markdown(git_surface_path.with_suffix(".md"), render_git_surface_summary(git_surface) + "\n")
    reports_created.extend([str(git_surface_path), str(git_surface_path.with_suffix(".md"))])

    hooks = evaluate_hook_readiness(root)
    hooks_path = reports_root / "hook-readiness.final.json"
    save_json(hooks_path, hooks)
    save_markdown(hooks_path.with_suffix(".md"), render_hook_markdown(hooks))
    reports_created.extend([str(hooks_path), str(hooks_path.with_suffix(".md"))])

    host_alias = str(canonical_surface(authority).get("host_alias", "devmgmt-wsl"))
    remote_project = str(app_remote_project_path or app_policy.get("settings_flow", {}).get("remote_project", str(root)))
    linux_cli = install_linux_codex_cli(host_alias=host_alias, allow_install=allow_linux_codex_install, runtime=runtime)
    if linux_cli.get("applied"):
        agent_actions_applied.append("Linux-native Codex CLI installed on canonical remote runtime")
    elif allow_linux_codex_install and linux_cli.get("status") != "PASS":
        agent_actions_skipped.append("Linux-native Codex CLI install failed or remained blocked")
    else:
        agent_actions_skipped.append("Linux-native Codex CLI install skipped")

    launcher = repair_linux_launcher_shim(authority, apply=apply_user_level)
    launcher_report = {
        "status": launcher.get("status", "WARN"),
        "preview_path": launcher.get("preview_path", ""),
        "live_write_allowed": launcher.get("live_write_allowed", False),
        "current_target": launcher.get("current_target", ""),
        "expected_target": launcher.get("expected_target", ""),
        "reasons": launcher.get("reasons", []),
    }
    launcher_path = reports_root / "linux-native-codex-cli-activation.final.json"
    save_json(launcher_path, launcher_report)
    save_markdown(
        launcher_path.with_suffix(".md"),
        "\n".join(
            [
                "# Linux-native Codex CLI Activation",
                "",
                f"- Status: {launcher_report['status']}",
                f"- Preview path: {launcher_report['preview_path']}",
                f"- Live write allowed: {str(launcher_report['live_write_allowed']).lower()}",
                f"- Current target: {launcher_report['current_target'] or '(unset)'}",
                f"- Expected target: {launcher_report['expected_target'] or '(unset)'}",
            ]
            + [f"- Reason: {item}" for item in launcher_report.get("reasons", [])]
        )
        + "\n",
    )
    reports_created.extend([str(launcher_path), str(launcher_path.with_suffix(".md"))])
    if launcher.get("changed"):
        files_touched.append(str(authority.get("generation_targets", {}).get("global_runtime", {}).get("linux", {}).get("launcher", "")))
        agent_actions_applied.append("Live ~/.local/bin/codex wrapper updated")
    else:
        agent_actions_skipped.append("Live ~/.local/bin/codex wrapper unchanged")

    serena_repair = repair_serena(apply_serena=apply_user_level, repo_root=root)
    startup = evaluate_startup_workflow(root, mode="ssh-managed", purpose="app-usability")
    startup_path = reports_root / "startup-workflow.final.json"
    save_json(startup_path, startup)
    reports_created.append(str(startup_path))
    serena_path = reports_root / ("serena-startup.final-apply.json" if apply_user_level else "serena-startup.final-dry-run.json")
    save_json(serena_path, serena_repair)
    reports_created.append(str(serena_path))
    if serena_repair.get("actions_applied"):
        agent_actions_applied.extend(f"Serena repair: {item}" for item in serena_repair["actions_applied"])
    elif serena_repair.get("actions_planned"):
        agent_actions_skipped.extend(f"Serena repair planned only: {item}" for item in serena_repair["actions_planned"])

    hygiene = evaluate_artifact_hygiene(root)
    hygiene_path = reports_root / "artifact-hygiene.final.json"
    save_json(hygiene_path, hygiene)
    reports_created.append(str(hygiene_path))

    audit_path = reports_root / "audit.final.json"
    _pre_score_audit = run_audit_cli(root, purpose="app-usability", output_file=audit_path, windows_ssh_readiness_report=windows_path)
    score = evaluate_score_layer(root, purpose="app-usability")
    score_path = reports_root / "score-layer.final.json"
    save_json(score_path, score)
    save_markdown(score_path.with_suffix(".md"), render_score_markdown(score))
    reports_created.extend([str(score_path), str(score_path.with_suffix(".md"))])

    audit = run_audit_cli(root, purpose="app-usability", output_file=audit_path, windows_ssh_readiness_report=windows_path)
    reports_created.append(str(audit_path))

    status_reasons: list[str] = []
    warning_reasons: list[str] = []
    ui_action = build_single_ui_action(app_policy.get("settings_flow", {}), host_alias, remote_project)
    app_remote_project_status = str(windows.get("app_remote_project_status", "UNOBSERVED"))
    blocker_analysis = build_app_remote_access_blocker_analysis(
        root=root,
        windows=windows,
        runtime=runtime,
        bootstrap=bootstrap,
        host_alias=host_alias,
        remote_project=remote_project,
        ui_action=ui_action,
    )
    blocker_path = root / "reports" / "app-remote-access-blocker-analysis.final.json"
    save_json(blocker_path, blocker_analysis)
    save_markdown(blocker_path.with_suffix(".md"), render_blocker_analysis_markdown(blocker_analysis))
    save_json(root / "reports" / "app-remote-access-blocker-analysis.json", blocker_analysis)
    save_markdown(root / "reports" / "app-remote-access-blocker-analysis.md", render_blocker_analysis_markdown(blocker_analysis))
    reports_created.extend(
        [
            str(blocker_path),
            str(blocker_path.with_suffix(".md")),
            str(root / "reports" / "app-remote-access-blocker-analysis.json"),
            str(root / "reports" / "app-remote-access-blocker-analysis.md"),
        ]
    )
    if windows["status"] == "BLOCKED":
        status_reasons.extend(
            item for item in windows.get("blocking_reasons", []) if isinstance(item, str) and item.strip()
        )
        if not status_reasons:
            status_reasons.append("Windows App-side SSH discovery is blocked.")
    elif windows["status"] == "WARN":
        warning_reasons.extend(
            item for item in windows.get("warning_reasons", []) if isinstance(item, str) and item.strip()
        )
        if not warning_reasons:
            warning_reasons.append("Windows App-side SSH discovery still needs manual verification.")
    if app_remote_project_status != "OPENED":
        status_reasons.append("Codex App remote project open proof is missing or failed.")
    if str(runtime.get("canonical_execution_status", "BLOCKED")) != "PASS":
        status_reasons.append("Canonical SSH runtime is not PASS.")
    remote_codex_status = str(runtime.get("remote_codex_resolution_status", {}).get("status", runtime.get("remote_codex_resolution_status", "WARN")))
    if remote_codex_status == "BLOCKED":
        status_reasons.append("Remote codex still resolves through a forbidden Windows launcher.")
    if str(runtime.get("remote_native_codex_status", {}).get("status", "WARN")) == "BLOCKED":
        status_reasons.append("Linux-native Codex CLI is not available on the canonical remote PATH.")
    if str(config.get("gate_status", config.get("status", "WARN"))) == "BLOCKED":
        status_reasons.append("Config provenance is blocked.")
    windows_policy_surface_status = str(config.get("windows_policy_surface_status", "PASS"))
    windows_app_evidence_status = str(active_config.get("windows_app_evidence_status", config.get("app_state_surface", {}).get("status", "WARN")))
    if str(active_config.get("gate_status", active_config.get("status", "WARN"))) == "BLOCKED":
        status_reasons.append("Active config smoke is blocked.")
    if windows_policy_surface_status == "BLOCKED":
        status_reasons.append("Windows policy-bearing .codex surface is still present on an app-readable active settings or instruction surface.")
    elif windows_policy_surface_status == "WARN":
        warning_reasons.append("Windows .codex still contains non-generated policy-like user or app content; treat it as evidence-only and review manually before cleanup.")
    auth_status = "PASS" if str(windows.get("ssh_transport_status", "BLOCKED")) == "PASS" else "BLOCKED"
    if auth_status == "BLOCKED":
        status_reasons.append("App auth or sign-in flow cannot proceed until the SSH connection is repaired.")
    if str(score.get("status", "PASS")) == "BLOCKED":
        status_reasons.append("Score layer is blocked for app-usability.")
    if str(audit.get("status", "PASS")) in {"FAIL", "BLOCKED"}:
        status_reasons.append("Audit remains blocked for app-usability.")

    if runtime.get("overall_status") == "WARN":
        warning_reasons.append("Canonical runtime is usable with warnings.")
    if startup["status"] == "WARN":
        warning_reasons.append("Serena still blocks general code modification, but app setup/readiness can proceed.")
    if str(toolchain.get("status", "PASS")) == "WARN":
        warning_reasons.append("Toolchain surface still reports warnings.")
    if str(hooks.get("status", "PASS")) == "WARN":
        warning_reasons.append("Hooks remain trigger-only advisory surfaces.")
    if str(hygiene.get("status", "PASS")) == "WARN":
        warning_reasons.append("Artifact hygiene still reports warnings.")
    if str(audit.get("status", "PASS")) == "WARN":
        warning_reasons.append("Audit still reports warnings.")
    if str(score.get("status", "PASS")) == "WARN":
        warning_reasons.append("Score layer still reports warnings.")
    if str(git_surface.get("status", "PASS")) == "WARN":
        warning_reasons.append("Git surface still reports warnings.")

    if status_reasons:
        status = "APP_NOT_READY"
    elif warning_reasons:
        status = "APP_READY_WITH_WARNINGS"
    else:
        status = "APP_READY"

    steps = app_policy.get("settings_flow", {})
    control_thread = app_policy.get("control_thread", {}) if isinstance(app_policy.get("control_thread"), dict) else {}
    if not control_thread:
        fallback_control_thread = authority.get("control_thread_policy", {})
        control_thread = fallback_control_thread if isinstance(fallback_control_thread, dict) else {}
    user_actions = [ui_action]
    if status_reasons:
        user_actions.append("프로젝트가 열리면 sign-in이 뜰 경우 로그인 후 같은 경로를 다시 열어 달라.")

    report = {
        "status": status,
        "status_reasons": status_reasons if status_reasons else warning_reasons,
        "user_action_required": user_actions,
        "app_settings_steps": user_actions[:1],
        "agent_actions_applied": agent_actions_applied,
        "agent_actions_skipped": agent_actions_skipped,
        "files_touched": sorted(item for item in files_touched if item),
        "backups_created": backups_created,
        "reports_created": reports_created,
        "windows_app_ssh_status": windows["status"],
        "windows_app_ssh_probe_source": str(windows.get("probe_source", "")),
        "windows_app_ssh_cache_status": str(windows.get("cache_status", "")),
        "canonical_ssh_runtime_status": str(runtime.get("ssh_runtime_status", runtime.get("canonical_execution_status", "WARN"))),
        "remote_codex_status": remote_codex_status,
        "app_remote_project_status": app_remote_project_status,
        "app_remote_project_path": remote_project,
        "linux_native_codex_cli_status": str(runtime.get("remote_native_codex_status", {}).get("status", linux_cli.get("status", "WARN"))),
        "config_provenance_status": str(config.get("gate_status", config.get("status", "WARN"))),
        "active_config_smoke_status": str(active_config.get("gate_status", active_config.get("status", "WARN"))),
        "windows_policy_surface_status": windows_policy_surface_status,
        "windows_app_evidence_status": windows_app_evidence_status,
        "windows_app_bootstrap_status": str(bootstrap.get("after", {}).get("status", bootstrap.get("status", "WARN"))),
        "windows_app_bootstrap": bootstrap,
        "control_thread_status": "PASS" if control_thread.get("name") else "WARN",
        "auth_status": auth_status,
        "serena_status": startup["status"],
        "score_status": str(score.get("status", "WARN")),
        "audit_status": str(audit.get("status", audit.get("gate_status", "WARN"))),
        "git_surface_status": str(git_surface.get("status", "WARN")),
        "canonical_repo_root": str(management_git_report.get("canonical_repo_root", root)),
        "active_worktree_root": str(management_git_report.get("active_worktree_root", root)),
        "final_user_instructions": ui_action,
        "remaining_user_action": "" if status in {"APP_READY", "APP_READY_WITH_WARNINGS"} else ui_action,
        "hard_acceptance": {
            "codex_app_remote_project_opened": app_remote_project_status == "OPENED",
            "linux_native_codex_executes": str(runtime.get("remote_native_codex_status", {}).get("status", linux_cli.get("status", "WARN"))) == "PASS",
            "status": "PASS"
            if app_remote_project_status == "OPENED"
            and str(runtime.get("remote_native_codex_status", {}).get("status", linux_cli.get("status", "WARN"))) == "PASS"
            else "BLOCKED",
        },
        "app_remote_access_blocker_analysis": str(blocker_path),
    }
    report["reports_created"].extend(
        [
            str(root / "reports" / "codex-app-usability-final.json"),
            str(root / "reports" / "codex-app-usability-final.md"),
        ]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestrate the modular Dev-Management app-usability readiness flow.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply-user-level", action="store_true")
    parser.add_argument("--allow-linux-codex-install", action="store_true")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--refresh-windows-ssh", action="store_true")
    parser.add_argument("--windows-ssh-readiness-report", default="")
    parser.add_argument("--no-live-windows-ssh-probe", action="store_true")
    app_listing = parser.add_mutually_exclusive_group()
    app_listing.add_argument("--app-host-listed", action="store_true")
    app_listing.add_argument("--app-host-not-listed", action="store_true")
    manual_add = parser.add_mutually_exclusive_group()
    manual_add.add_argument("--manual-add-host-worked", action="store_true")
    manual_add.add_argument("--manual-add-host-failed", action="store_true")
    remote_project = parser.add_mutually_exclusive_group()
    remote_project.add_argument("--app-remote-project-opened", action="store_true")
    remote_project.add_argument("--app-remote-project-not-opened", action="store_true")
    remote_project.add_argument("--app-remote-project-unobserved", action="store_true")
    parser.add_argument("--app-remote-project-path", default=str(ROOT))
    args = parser.parse_args()

    report = evaluate_app_usability(
        args.repo_root,
        apply_user_level=bool(args.apply_user_level),
        allow_linux_codex_install=bool(args.allow_linux_codex_install),
        refresh_windows_ssh=bool(args.refresh_windows_ssh),
        windows_ssh_readiness_report=args.windows_ssh_readiness_report or None,
        no_live_windows_ssh_probe=bool(args.no_live_windows_ssh_probe),
        app_host_listed_in_connections=True if args.app_host_listed else False if args.app_host_not_listed else None,
        manual_add_host_worked=True if args.manual_add_host_worked else False if args.manual_add_host_failed else None,
        app_remote_project_opened=True if args.app_remote_project_opened else None,
        app_remote_project_not_opened=True if args.app_remote_project_not_opened else None,
        app_remote_project_unobserved=True if args.app_remote_project_unobserved else None,
        app_remote_project_path=args.app_remote_project_path,
    )
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    save_markdown(output_path.with_suffix(".md"), render_app_usability_markdown(report))
    canonical_final = Path(args.repo_root).expanduser().resolve() / "reports" / "codex-app-usability-final.json"
    save_json(canonical_final, report)
    save_markdown(canonical_final.with_suffix(".md"), render_app_usability_markdown(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_app_usability_markdown(report), end="")
    return status_exit_code("PASS" if report["status"] == "APP_READY" else "WARN" if report["status"] == "APP_READY_WITH_WARNINGS" else "BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
