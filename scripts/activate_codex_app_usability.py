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
from check_config_provenance import evaluate_config_provenance, render_markdown as render_config_markdown
from check_global_runtime import evaluate_global_runtime
from check_hook_readiness import evaluate_hook_readiness, render_markdown as render_hook_markdown
from check_startup_workflow import evaluate_startup_workflow
from check_toolchain_surface import evaluate_toolchain_surface, render_markdown as render_toolchain_markdown
from check_windows_app_ssh_readiness import evaluate_windows_app_ssh_readiness, render_markdown as render_windows_markdown
from repair_codex_desktop_runtime import repair_linux_launcher_shim
from repair_serena_startup import repair_serena
from run_score_layer import evaluate_score_layer, render_markdown as render_score_markdown


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "app-usability.final-dry-run.json"
APP_POLICY_PATH = ROOT / "contracts" / "app_surface_policy.json"
LINUX_CODEX_PREFIX = Path("/home/andy4917/.local/share/dev-management/codex-npm")


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_app_policy() -> dict[str, Any]:
    return load_json(APP_POLICY_PATH, default={})


def save_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    result = run_ssh(host_alias, command)
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
        f"- Linux-native Codex CLI: {report['linux_native_codex_cli_status']}",
        f"- Config provenance: {report['config_provenance_status']}",
        f"- Generated AGENTS: {report['generated_agents_status']}",
        f"- Auth readiness: {report['auth_status']}",
        f"- Serena status: {report['serena_status']}",
        f"- Score status: {report['score_status']}",
        f"- Audit status: {report['audit_status']}",
    ]
    if report.get("status_reasons"):
        lines.extend(["", "## Status Reasons"])
        lines.extend(f"- {item}" for item in report["status_reasons"])
    if report.get("user_action_required"):
        lines.extend(["", "## User Actions"])
        lines.extend(f"- {item}" for item in report["user_action_required"])
    return "\n".join(lines) + "\n"


def run_audit_cli(root: Path, *, purpose: str, output_file: Path) -> dict[str, Any]:
    command = [
        "python3",
        str(root / "scripts" / "audit_workspace.py"),
        "--json",
        "--purpose",
        purpose,
        "--output-file",
        str(output_file),
    ]
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

    runtime = evaluate_global_runtime(root)
    runtime_path = reports_root / "global-runtime.final.json"
    save_json(runtime_path, runtime)
    reports_created.append(str(runtime_path))
    save_json(root / "reports" / "global-runtime.json", runtime)

    windows = evaluate_windows_app_ssh_readiness(root, apply_user_level=apply_user_level)
    windows_path = reports_root / "windows-app-ssh-remote-readiness.final.json"
    save_json(windows_path, windows)
    save_markdown(windows_path.with_suffix(".md"), render_windows_markdown(windows))
    reports_created.extend([str(windows_path), str(windows_path.with_suffix(".md"))])
    files_touched.extend([windows["windows_ssh_config"]] if windows.get("applied") else [])
    backups_created.extend(windows.get("backups", []))
    if windows.get("applied"):
        agent_actions_applied.append("Windows user SSH alias repaired")
    else:
        agent_actions_skipped.append("Windows user SSH alias unchanged")

    config = evaluate_config_provenance(root)
    config_path = reports_root / "config-provenance.final.json"
    save_json(config_path, config)
    save_markdown(config_path.with_suffix(".md"), render_config_markdown(config))
    reports_created.extend([str(config_path), str(config_path.with_suffix(".md"))])

    toolchain = evaluate_toolchain_surface(root)
    toolchain_path = reports_root / "toolchain-surface.final.json"
    save_json(toolchain_path, toolchain)
    save_markdown(toolchain_path.with_suffix(".md"), render_toolchain_markdown(toolchain))
    reports_created.extend([str(toolchain_path), str(toolchain_path.with_suffix(".md"))])

    hooks = evaluate_hook_readiness(root)
    hooks_path = reports_root / "hook-readiness.final.json"
    save_json(hooks_path, hooks)
    save_markdown(hooks_path.with_suffix(".md"), render_hook_markdown(hooks))
    reports_created.extend([str(hooks_path), str(hooks_path.with_suffix(".md"))])

    host_alias = str(canonical_surface(authority).get("host_alias", "devmgmt-wsl"))
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
    _pre_score_audit = run_audit_cli(root, purpose="app-usability", output_file=audit_path)
    score = evaluate_score_layer(root, purpose="app-usability")
    score_path = reports_root / "score-layer.final.json"
    save_json(score_path, score)
    save_markdown(score_path.with_suffix(".md"), render_score_markdown(score))
    reports_created.extend([str(score_path), str(score_path.with_suffix(".md"))])

    audit = run_audit_cli(root, purpose="app-usability", output_file=audit_path)
    reports_created.append(str(audit_path))

    status_reasons: list[str] = []
    warning_reasons: list[str] = []
    if windows["status"] == "BLOCKED":
        status_reasons.append("Windows App-side SSH discovery is blocked.")
    if str(runtime.get("canonical_execution_status", "BLOCKED")) != "PASS":
        status_reasons.append("Canonical SSH runtime is not PASS.")
    remote_codex_status = str(runtime.get("remote_codex_resolution_status", {}).get("status", runtime.get("remote_codex_resolution_status", "WARN")))
    if remote_codex_status == "BLOCKED":
        status_reasons.append("Remote codex still resolves through a forbidden Windows launcher.")
    if str(runtime.get("remote_native_codex_status", {}).get("status", "WARN")) == "BLOCKED":
        status_reasons.append("Linux-native Codex CLI is not available on the canonical remote PATH.")
    if str(config.get("gate_status", config.get("status", "WARN"))) == "BLOCKED":
        status_reasons.append("Config provenance is blocked.")
    generated_agents_status = "PASS"
    for path_text, payload in config.get("generated_headers", {}).items():
        if path_text.endswith("AGENTS.md") and str(payload.get("status", "PASS")) != "PASS":
            generated_agents_status = "WARN"
    if generated_agents_status != "PASS":
        status_reasons.append("Generated AGENTS mirrors are not current.")
    auth_status = "PASS" if windows["status"] != "BLOCKED" else "BLOCKED"
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

    if status_reasons:
        status = "APP_NOT_READY"
    elif warning_reasons:
        status = "APP_READY_WITH_WARNINGS"
    else:
        status = "APP_READY"

    steps = app_policy.get("settings_flow", {})
    user_actions = [
        "Restart Codex App.",
        f"Open {steps.get('settings_path', 'Settings > Connections')}.",
        f"Enable or select {steps.get('host_alias', host_alias)}.",
        f"Open remote project {steps.get('remote_project', str(root))}.",
        "Complete sign-in if prompted.",
        "Send the readiness prompt in the app.",
    ]
    if status == "APP_READY":
        user_actions = user_actions[:]
    elif status == "APP_READY_WITH_WARNINGS":
        user_actions = user_actions[:]
    else:
        user_actions.extend(item for item in [windows.get("simple_user_instruction")] if item)

    report = {
        "status": status,
        "status_reasons": status_reasons if status_reasons else warning_reasons,
        "user_action_required": user_actions,
        "app_settings_steps": user_actions[:6],
        "agent_actions_applied": agent_actions_applied,
        "agent_actions_skipped": agent_actions_skipped,
        "files_touched": sorted(item for item in files_touched if item),
        "backups_created": backups_created,
        "reports_created": reports_created,
        "windows_app_ssh_status": windows["status"],
        "canonical_ssh_runtime_status": str(runtime.get("ssh_runtime_status", runtime.get("canonical_execution_status", "WARN"))),
        "remote_codex_status": remote_codex_status,
        "linux_native_codex_cli_status": str(runtime.get("remote_native_codex_status", {}).get("status", linux_cli.get("status", "WARN"))),
        "config_provenance_status": str(config.get("gate_status", config.get("status", "WARN"))),
        "generated_agents_status": generated_agents_status,
        "auth_status": auth_status,
        "serena_status": startup["status"],
        "score_status": str(score.get("status", "WARN")),
        "audit_status": str(audit.get("status", audit.get("gate_status", "WARN"))),
        "final_user_instructions": "Restart Codex App, open Settings > Connections, select devmgmt-wsl, open /home/andy4917/Dev-Management, sign in if prompted, and send the readiness prompt.",
    }
    report["reports_created"].extend(
        [
            str(ROOT / "reports" / "codex-app-usability-final.json"),
            str(ROOT / "reports" / "codex-app-usability-final.md"),
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
    args = parser.parse_args()

    report = evaluate_app_usability(
        args.repo_root,
        apply_user_level=bool(args.apply_user_level),
        allow_linux_codex_install=bool(args.allow_linux_codex_install),
    )
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    save_markdown(output_path.with_suffix(".md"), render_app_usability_markdown(report))
    canonical_final = ROOT / "reports" / "codex-app-usability-final.json"
    save_json(canonical_final, report)
    save_markdown(canonical_final.with_suffix(".md"), render_app_usability_markdown(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_app_usability_markdown(report), end="")
    return status_exit_code("PASS" if report["status"] == "APP_READY" else "WARN" if report["status"] == "APP_READY_WITH_WARNINGS" else "BLOCKED")


if __name__ == "__main__":
    raise SystemExit(main())
