#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_global_runtime import evaluate_global_runtime


STARTUP_REPORT_NAME = "startup-workflow.json"
SERENA_ACTIVATION_FAILURE_PATTERNS = (
    re.compile(r"no project root found", re.IGNORECASE),
    re.compile(r"not activating any project", re.IGNORECASE),
)
STARTUP_OPTIONAL_GLOBS = (
    "docs/**",
    "reports/**",
    "quarantine/**",
    "**/*.md",
    "**/*.txt",
)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def matches_any(path_value: str, patterns: Iterable[str]) -> bool:
    normalized = path_value.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern.replace("\\", "/")) for pattern in patterns)


def git_changed_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        text = line.rstrip()
        if not text:
            continue
        candidate = text[3:] if len(text) >= 4 else text
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        path = candidate.strip()
        if path:
            paths.append(path)
    return sorted(set(paths))


def status_exit_code(status: str) -> int:
    if status in {"PASS", "WAIVED"}:
        return 0
    if status == "BLOCKED":
        return 2
    return 1


def repo_root_from_arg(repo_root: str | Path | None) -> Path:
    if repo_root is None:
        return Path(__file__).resolve().parents[1]
    return Path(repo_root).expanduser().resolve()


def runtime_config_paths(authority: dict[str, Any]) -> dict[str, Path | None]:
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    linux = runtime.get("linux", {})
    windows = runtime.get("windows_mirror", {})
    return {
        "global": Path(str(linux.get("config", Path.home() / ".codex" / "config.toml"))).expanduser().resolve(),
        "windows_mirror": Path(str(windows.get("config", ""))).expanduser().resolve() if windows.get("config") else None,
        "agents": Path(str(linux.get("agents", Path.home() / ".codex" / "AGENTS.md"))).expanduser().resolve(),
    }


def read_mcp_block(config_path: Path, server_name: str) -> dict[str, Any]:
    payload = load_toml(config_path)
    mcp_servers = payload.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return {}
    block = mcp_servers.get(server_name, {})
    return block if isinstance(block, dict) else {}


def context7_block_matches(block: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not block:
        return False
    for key, value in expected.items():
        if block.get(key) != value:
            return False
    return True


def serena_forbidden_keys(policy: dict[str, Any]) -> set[str]:
    override = policy.get("override_policy", {})
    return {str(item).strip() for item in override.get("forbidden_keys", []) if str(item).strip()}


def serena_block_matches(block: dict[str, Any], expected: dict[str, Any], policy: dict[str, Any]) -> bool:
    if not block:
        return False
    for key, value in expected.items():
        if block.get(key) != value:
            return False
    return not any(key in block for key in serena_forbidden_keys(policy))


def context7_api_key_source() -> str:
    if os.environ.get("CONTEXT7_API_KEY"):
        return "process_env"
    return ""


def workflow_relevant_changes(changed_paths: list[str]) -> list[str]:
    return [path for path in changed_paths if not matches_any(path, STARTUP_OPTIONAL_GLOBS)]


def context7_protected_changes(policy: dict[str, Any], changed_paths: list[str]) -> list[str]:
    return sorted({path for path in changed_paths if matches_any(path, policy.get("protected_change_globs", []))})


def self_config_changes(policy: dict[str, Any], changes: list[str]) -> bool:
    return bool(changes) and all(matches_any(path, policy.get("self_config_globs", [])) for path in changes)


def autogenerated_context7_entry(key_source: str) -> dict[str, Any]:
    return {
        "query": "Context7 MCP remote HTTP configuration for Codex",
        "resolved_library_id": "context7-remote-http",
        "docs_retrieved": [
            "management:contracts/context7_policy.json",
            "management:docs/CONTEXT7_USAGE.md",
        ],
        "version_evidence": (
            "Remote HTTP endpoint https://mcp.context7.com/mcp is configured with CONTEXT7_API_KEY header mapping; "
            f"detected key source is {key_source or 'unconfirmed runtime environment'}."
        ),
        "decision_summary": "Use Context7 before protected dependency, API, configuration, or migration changes.",
    }


def evaluate_context7(
    repo_root: Path,
    authority: dict[str, Any],
    policy: dict[str, Any],
    changed_paths: list[str],
) -> dict[str, Any]:
    config_paths = runtime_config_paths(authority)
    global_config = config_paths["global"]
    expected = dict(policy.get("remote_template", {}))
    global_ok = context7_block_matches(read_mcp_block(global_config, "context7"), expected)
    detected_changes = context7_protected_changes(policy, changed_paths)
    report_path = repo_root / "reports" / "context7-usage.json"
    report = load_json(report_path, default={})
    raw_entries = report.get("entries", [])
    entries = [dict(item) for item in raw_entries if isinstance(item, dict)]
    missing_fields: list[str] = []
    for index, entry in enumerate(entries):
        for field in policy.get("required_report_fields", []):
            if not entry.get(field):
                missing_fields.append(f"entries[{index}].{field}")
    if detected_changes and not entries and self_config_changes(policy, detected_changes):
        entries = [autogenerated_context7_entry(context7_api_key_source())]
        missing_fields = []

    warnings: list[str] = []
    blockers: list[str] = []
    required = bool(detected_changes)
    if not global_ok:
        if required:
            blockers.append("global Context7 config does not match the canonical remote HTTP template")
        else:
            warnings.append("global Context7 config does not match the canonical remote HTTP template")
    if required and not entries:
        blockers.append("protected changes require reports/context7-usage.json evidence")
    if required and missing_fields:
        blockers.append(f"Context7 evidence is missing required fields: {', '.join(missing_fields)}")

    status = "PASS" if not blockers else "BLOCKED"
    summary = "Context7 evidence is ready for the current diff." if status == "PASS" else "Context7 evidence is incomplete for the current diff."
    step_status = "WAIVED" if not required else status
    step_reason = ""
    if not required:
        step_reason = "current diff does not touch Context7-protected files"
    elif blockers:
        step_reason = blockers[0]

    return {
        "status": status,
        "summary": summary,
        "required": required,
        "report_path": str(report_path),
        "detected_changes": detected_changes,
        "entries": entries,
        "warnings": warnings,
        "blockers": blockers,
        "config": {
            "global_config_path": str(global_config),
            "global_matches_canonical": global_ok,
        },
        "step": {
            "id": "context7_consulted_before_protected_changes",
            "status": step_status,
            "reason": step_reason,
            "evidence_refs": [str(report_path)] if entries else [],
        },
    }


def serena_home_path() -> Path:
    return Path.home() / ".serena"


def latest_serena_log(home: Path) -> Path | None:
    logs_root = home / "logs"
    if not logs_root.exists():
        return None
    candidates = [path for path in logs_root.glob("*/mcp_*.txt") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def serena_activation_status(home: Path) -> dict[str, Any]:
    log_path = latest_serena_log(home)
    if log_path is None:
        return {
            "status": "BLOCKED",
            "reason": "no Serena MCP log was found, so project activation could not be verified",
            "log_path": "",
            "matched_lines": [],
        }
    content = log_path.read_text(encoding="utf-8", errors="ignore")
    matched_lines = [
        line.strip()
        for line in content.splitlines()
        if any(pattern.search(line) for pattern in SERENA_ACTIVATION_FAILURE_PATTERNS)
    ]
    if matched_lines:
        return {
            "status": "BLOCKED",
            "reason": "latest Serena MCP log shows the session started without activating a project",
            "log_path": str(log_path),
            "matched_lines": matched_lines,
        }
    return {
        "status": "PASS",
        "reason": "",
        "log_path": str(log_path),
        "matched_lines": [],
    }


def serena_required_actions(policy: dict[str, Any], repo_root: Path) -> list[str]:
    actions = [str(item).replace("<repo>", str(repo_root)) for item in policy.get("required_actions", []) if str(item).strip()]
    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped


def serena_deterministic_repair_available() -> dict[str, Any]:
    binary = shutil.which("serena")
    if not binary:
        return {
            "available": False,
            "binary": "",
            "project_index_available": False,
            "reason": "serena binary is not available on Linux PATH",
        }
    try:
        result = subprocess.run(
            ["serena", "project", "index", "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "binary": binary,
            "project_index_available": False,
            "reason": "serena project index --help timed out",
        }
    available = result.returncode == 0 and "Auto-creates project.yml" in (result.stdout or "")
    return {
        "available": available,
        "binary": binary,
        "project_index_available": available,
        "reason": "" if available else "deterministic Serena project index help was not confirmed",
    }


def evaluate_serena(
    repo_root: Path,
    authority: dict[str, Any],
    policy: dict[str, Any],
    changed_paths: list[str],
) -> dict[str, Any]:
    config_paths = runtime_config_paths(authority)
    global_config = config_paths["global"]
    windows_config = config_paths["windows_mirror"]
    expected = dict(policy.get("template", {}))
    global_ok = serena_block_matches(read_mcp_block(global_config, "serena"), expected, policy)
    windows_present = isinstance(windows_config, Path) and windows_config.exists()
    windows_ok = windows_present and serena_block_matches(read_mcp_block(windows_config, "serena"), expected, policy)

    home = serena_home_path()
    project_dir = repo_root / ".serena"
    memories_dir = project_dir / "memories"
    onboarding_performed = memories_dir.exists() and any(memories_dir.rglob("*.md"))
    activation = serena_activation_status(home)
    deterministic_repair = serena_deterministic_repair_available()

    required = bool(changed_paths)
    warnings: list[str] = []
    blockers: list[str] = []

    if not global_ok:
        if required:
            blockers.append("global Serena config does not match the canonical template")
        else:
            warnings.append("global Serena config does not match the canonical template")
    if not shutil.which("serena"):
        if required:
            blockers.append("serena binary is not available on Linux PATH")
        else:
            warnings.append("serena binary is not available on Linux PATH")
    if not home.exists() or not (home / "serena_config.yml").exists():
        if required:
            blockers.append("serena init has not been completed")
        else:
            warnings.append("serena init has not been completed")
    if required and not (project_dir / "project.yml").exists():
        blockers.append("Serena project metadata is missing for the current repo")
    if required and not onboarding_performed:
        blockers.append("Serena onboarding has not been performed for the current repo")
    if required and activation["status"] != "PASS":
        blockers.append(activation["reason"])
    if not windows_ok:
        warnings.append("Windows Serena config parity is not confirmed.")

    status = "PASS" if not blockers else "BLOCKED"
    summary = "Serena startup sequence is ready for the current diff." if status == "PASS" else "Serena startup sequence is incomplete for the current diff."

    return {
        "status": status,
        "summary": summary,
        "required": required,
        "warnings": warnings,
        "blockers": blockers,
        "required_actions": serena_required_actions(policy, repo_root),
        "config": {
            "global": {
                "path": str(global_config),
                "present": global_config.exists(),
                "matches_canonical": global_ok,
            },
            "windows_mirror": {
                "path": str(windows_config) if isinstance(windows_config, Path) else "",
                "present": windows_present,
                "matches_canonical": windows_ok,
            },
        },
        "runtime": {
            "linux": {
                "serena_home": str(home),
                "binary_found": shutil.which("serena") is not None,
                "home_initialized": home.exists() and (home / "serena_config.yml").exists(),
                "project_dir": str(project_dir),
                "project_configured": (project_dir / "project.yml").exists(),
                "onboarding_performed": onboarding_performed,
            },
        },
        "repair_advice": {
            "can_auto_repair": bool(deterministic_repair["available"] and required and not (project_dir / "project.yml").exists()),
            "reason": (
                ""
                if deterministic_repair["available"] and required and not (project_dir / "project.yml").exists()
                else "Deterministic Serena onboarding repair is not confirmed; use serena project index only for metadata/index and keep onboarding manual."
            ),
            "deterministic_cli": deterministic_repair,
        },
        "activation": activation,
        "steps": [
            {
                "id": "serena_global_config_ready",
                "status": "PASS" if global_ok else ("BLOCKED" if required else "WAIVED"),
                "reason": "" if global_ok else "global Serena config does not match the canonical template",
                "evidence_refs": [str(global_config)] if global_config.exists() else [],
            },
            {
                "id": "serena_project_metadata_present",
                "status": "WAIVED" if not required else ("PASS" if (project_dir / "project.yml").exists() else "BLOCKED"),
                "reason": "" if (project_dir / "project.yml").exists() or not required else "Serena project metadata is missing for the current repo",
                "evidence_refs": [str(project_dir / "project.yml")] if (project_dir / "project.yml").exists() else [],
            },
            {
                "id": "serena_onboarding_completed",
                "status": "WAIVED" if not required else ("PASS" if onboarding_performed else "BLOCKED"),
                "reason": "" if onboarding_performed or not required else "Serena onboarding has not been performed for the current repo",
                "evidence_refs": [str(memories_dir)] if memories_dir.exists() else [],
            },
            {
                "id": "serena_project_activated",
                "status": "WAIVED" if not required else activation["status"],
                "reason": "" if not required else activation["reason"],
                "evidence_refs": [activation["log_path"]] if activation.get("log_path") else [],
            },
        ],
    }


def expected_sequence() -> list[str]:
    return [
        "Activate the current project or worktree with Serena before code work.",
        "Verify Serena onboarding and project memories before major code changes.",
        "Use Context7 before protected dependency, API, configuration, or migration changes.",
    ]


def selected_startup_mode(authority: dict[str, Any], requested_mode: str) -> str:
    canonical = authority.get("canonical_remote_execution_surface", authority.get("canonical_execution_surface", {}))
    if requested_mode == "auto" and str(canonical.get("id", "")).strip() == "ssh-devmgmt-wsl":
        return "ssh-managed"
    return requested_mode


def evaluate_startup_workflow(repo_root: str | Path | None = None, *, mode: str = "auto") -> dict[str, Any]:
    root = repo_root_from_arg(repo_root)
    authority = load_json(root / "contracts" / "workspace_authority.json", default={})
    context7_policy = load_json(root / "contracts" / "context7_policy.json", default={})
    serena_policy = load_json(root / "contracts" / "serena_policy.json", default={})
    changed_paths = git_changed_paths(root)
    startup_changes = workflow_relevant_changes(changed_paths)
    selected_mode = selected_startup_mode(authority, mode)
    runtime_gate = evaluate_global_runtime(root, mode=selected_mode)

    serena = evaluate_serena(root, authority, serena_policy, startup_changes)
    context7 = evaluate_context7(root, authority, context7_policy, changed_paths)
    blockers = [*serena["blockers"], *context7["blockers"]]
    warnings = [*serena["warnings"], *context7["warnings"]]
    if selected_mode == "ssh-managed" and runtime_gate.get("ssh_canonical_runtime", {}).get("canonical_ssh_runtime_status", {}).get("status") != "PASS":
        blockers.append("canonical SSH runtime is unavailable for startup verification")
    status = "PASS" if not blockers else "BLOCKED"
    summary = "Serena-first and Context7-first startup workflow is ready for the current diff." if status == "PASS" else "Serena-first and Context7-first startup workflow is incomplete for the current diff."

    return {
        "status": status,
        "summary": summary,
        "generated_at": utc_timestamp(),
        "mode_requested": mode,
        "mode_selected": selected_mode,
        "repo_root": str(root),
        "expected_sequence": expected_sequence(),
        "changed_paths": changed_paths,
        "workflow_changes": startup_changes,
        "blocking_reasons": blockers,
        "warnings": warnings,
        "runtime_gate": {
            "canonical_ssh_runtime_status": runtime_gate.get("ssh_canonical_runtime", {}).get("canonical_ssh_runtime_status", {}),
            "fail_closed": bool(selected_mode == "ssh-managed" and runtime_gate.get("ssh_canonical_runtime", {}).get("canonical_ssh_runtime_status", {}).get("status") != "PASS"),
        },
        "serena": serena,
        "context7": context7,
        "sequence": [*serena["steps"], context7["step"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Serena-first and Context7-first startup workflow expectations.")
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--mode", choices=["auto", "local", "ssh-managed"], default="auto")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo_root = repo_root_from_arg(args.repo_root or None)
    report = evaluate_startup_workflow(repo_root, mode=args.mode)
    output_path = Path(args.output_file).expanduser().resolve() if args.output_file else repo_root / "reports" / STARTUP_REPORT_NAME
    save_json(output_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
