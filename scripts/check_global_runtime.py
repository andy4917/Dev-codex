#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from check_config_provenance import evaluate_config_provenance
from check_windows_app_ssh_readiness import evaluate_windows_app_ssh_readiness
from render_codex_runtime import GENERATED_RUNTIME_HEADER, preview_linux_launcher_path, render_linux_launcher


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "global-runtime.json"
PATH_NORMALIZER = Path.home() / ".config" / "shell" / "wsl-runtime-paths.sh"
LOCAL_SHELL = os.environ.get("SHELL", "/bin/zsh")
TYPE_A_PATTERN = re.compile(r"^codex\s+is\s+(?P<path>.+)$")


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def collapse_status(values: list[str]) -> str:
    filtered = [value for value in values if value]
    if any(value == "BLOCKED" for value in filtered):
        return "BLOCKED"
    if any(value == "WARN" for value in filtered):
        return "WARN"
    return "PASS"


def authority_path_for(repo_root: str | Path | None = None) -> Path:
    if repo_root is not None:
        candidate = Path(repo_root).expanduser().resolve() / "contracts" / "workspace_authority.json"
        if candidate.exists():
            return candidate
    return AUTHORITY_PATH


def load_authority(repo_root: str | Path | None = None) -> dict[str, Any]:
    return load_json(authority_path_for(repo_root), default={})


def canonical_surface(authority: dict[str, Any]) -> dict[str, Any]:
    return authority.get("canonical_remote_execution_surface", authority.get("canonical_execution_surface", {}))


def run_local_shell(command: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [LOCAL_SHELL, "-lc", command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc), "command": command}
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
    }


def run_ssh(host: str, command: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc), "command": command}
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
    }


def runtime_paths(authority: dict[str, Any]) -> dict[str, Path]:
   runtime = authority.get("generation_targets", {}).get("global_runtime", {})
   linux = runtime.get("linux", {})
   windows = runtime.get("windows_mirror", {})
   return {
       "linux_config": Path(str(linux.get("config", Path.home() / ".codex" / "config.toml"))).expanduser(),
        "linux_user_override_config": Path(str(linux.get("user_override_config", Path.home() / ".codex" / "user-config.toml"))).expanduser(),
       "windows_config": Path(str(windows.get("config", "/mnt/c/Users/anise/.codex/config.toml"))).expanduser(),
       "linux_launcher": Path(str(linux.get("launcher", Path.home() / ".local" / "bin" / "codex"))).expanduser(),
   }


def forbidden_runtime_paths(authority: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in authority.get("forbidden_primary_runtime_paths", []) if str(item).strip()]


def is_forbidden_runtime_value(value: str, authority: dict[str, Any]) -> bool:
    normalized = value.replace("\\", "/").strip().lower()
    if not normalized:
        return False
    for raw in forbidden_runtime_paths(authority):
        marker = raw.replace("\\", "/").strip().lower()
        if marker == ".codex/bin/wsl/codex" and normalized.endswith(marker):
            return True
        if marker and marker in normalized:
            return True
    return False


def parse_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_wrapper_target(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.startswith("target="):
            continue
        _, raw_value = stripped.split("=", 1)
        return raw_value.strip().strip('"').strip("'")
    return ""


def parse_type_a_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in lines:
        matched = TYPE_A_PATTERN.match(line.strip())
        if matched:
            paths.append(matched.group("path").strip())
    deduped: list[str] = []
    for path in paths:
        if path and path not in deduped:
            deduped.append(path)
    return deduped


def config_surface_classification(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    text = read_text(path)
    runtime = runtime_paths(authority)
    windows_target = runtime["windows_config"].resolve()
    linux_target = runtime["linux_config"].resolve()
    user_override_target = runtime["linux_user_override_config"].resolve()
    classification = "unmanaged"
    repairable = False
    if path.exists() and path.resolve() == windows_target:
        classification = "generated"
        repairable = True
    elif path.exists() and path.resolve() == linux_target:
        classification = "generated"
        repairable = True
    elif path.exists() and path.resolve() == user_override_target:
        classification = "user_override"
        repairable = False
    elif text.startswith("# GENERATED - DO NOT EDIT") or text.startswith("GENERATED - DO NOT EDIT"):
        classification = "generated"
        repairable = True
    return {
       "path": str(path),
       "exists": path.exists(),
       "classification": classification,
        "repairable": repairable,
        "has_generated_header": text.startswith("# GENERATED - DO NOT EDIT") or text.startswith("GENERATED - DO NOT EDIT"),
    }


def detect_path_normalizer_surface(authority: dict[str, Any]) -> dict[str, Any]:
    text = read_text(PATH_NORMALIZER)
    authority_text = json.dumps(authority, ensure_ascii=False)
    repo_owned = False
    evidence: list[str] = []
    if GENERATED_RUNTIME_HEADER in text:
        repo_owned = True
        evidence.append("generated marker present")
    if str(AUTHORITY_PATH) in text or str(ROOT) in text:
        repo_owned = True
        evidence.append("authority path referenced")
    if str(PATH_NORMALIZER) in authority_text:
        repo_owned = True
        evidence.append("authority references path normalizer")
    return {
        "path": str(PATH_NORMALIZER),
        "exists": PATH_NORMALIZER.exists(),
        "repo_owned": repo_owned,
        "evidence": evidence,
    }


def local_path_precedence(path_entries: list[str], authority: dict[str, Any], launcher_path: Path) -> dict[str, Any]:
    forbidden_indices = [index for index, entry in enumerate(path_entries) if is_forbidden_runtime_value(entry, authority)]
    try:
        launcher_dir_index = path_entries.index(str(launcher_path.parent))
    except ValueError:
        launcher_dir_index = -1
    reasons: list[str] = []
    status = "PASS"
    if forbidden_indices:
        earliest_forbidden = min(forbidden_indices)
        if launcher_dir_index == -1 or launcher_dir_index > earliest_forbidden:
            status = "BLOCKED"
            reasons.append("local wrapper path is not ahead of forbidden runtime PATH entries")
    elif launcher_dir_index == -1:
        status = "WARN"
        reasons.append("local wrapper directory is not present in PATH")
    return {
        "status": status,
        "launcher_dir_index": launcher_dir_index,
        "forbidden_indices": forbidden_indices,
        "reasons": reasons,
    }


def classify_codex_candidate(
    path_value: str,
    authority: dict[str, Any],
    *,
    local_launcher: Path,
    preview_launcher: Path,
) -> dict[str, Any]:
    normalized = str(path_value).strip()
    payload = {
        "path": normalized,
        "classification": "missing",
        "status": "WARN",
        "exists": False,
        "native_candidate": False,
        "target": "",
        "reason": "",
    }
    if not normalized:
        payload["reason"] = "codex candidate path is empty"
        return payload
    if is_forbidden_runtime_value(normalized, authority):
        payload["classification"] = "forbidden_path"
        payload["status"] = "BLOCKED"
        payload["reason"] = "candidate resolves to a forbidden Windows-mounted runtime path"
        return payload

    candidate = Path(normalized).expanduser()
    exists = candidate.exists()
    payload["exists"] = exists
    text = ""
    if exists and candidate.is_file():
        try:
            if candidate.stat().st_size <= 65536:
                text = read_text(candidate)
        except OSError:
            text = ""
    target = extract_wrapper_target(text)
    payload["target"] = target
    generated_ssh_wrapper = bool(
        text
        and "generated by Dev-Management" in text
        and "exec ssh -o BatchMode=yes" in text
    )

    if exists and candidate.resolve() == preview_launcher.resolve():
        payload["classification"] = "repo_generated_ssh_wrapper"
        payload["reason"] = "preview SSH wrapper is not a Linux-native codex target"
        return payload
    if exists and candidate.resolve() == local_launcher.resolve() and target and is_forbidden_runtime_value(target, authority):
        payload["classification"] = "forbidden_wrapper"
        payload["status"] = "BLOCKED"
        payload["reason"] = "wrapper target resolves to the forbidden Windows-mounted Codex launcher"
        return payload
    if generated_ssh_wrapper:
        payload["classification"] = "repo_generated_ssh_wrapper"
        payload["reason"] = "repo-generated SSH wrapper is not a Linux-native codex target"
        return payload
    if target:
        if is_forbidden_runtime_value(target, authority):
            payload["classification"] = "forbidden_wrapper"
            payload["status"] = "BLOCKED"
            payload["reason"] = "wrapper target resolves to the forbidden Windows-mounted Codex launcher"
            return payload
        payload["classification"] = "wrapper"
        payload["reason"] = "wrapper target is not confirmed Linux-native codex"
        return payload
    if normalized.startswith("/mnt/c/"):
        payload["classification"] = "windows_mounted"
        payload["status"] = "BLOCKED"
        payload["reason"] = "Windows-mounted path is not a canonical Linux-native codex target"
        return payload
    if normalized.startswith("/") and Path(normalized).name == "codex":
        payload["classification"] = "linux_native_candidate"
        payload["status"] = "PASS" if exists or normalized.startswith("/usr/") or normalized.startswith("/opt/") else "WARN"
        payload["native_candidate"] = True
        payload["reason"] = "" if payload["status"] == "PASS" else "native candidate path could not be confirmed on this host"
        return payload
    payload["classification"] = "unknown"
    payload["reason"] = "candidate is not a recognized canonical codex target"
    return payload


def select_native_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [item for item in candidates if item.get("native_candidate")]
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        path = str(item.get("path", "")).strip()
        if not path or path in seen:
            continue
        seen.add(path)
        deduped.append(item)
    return deduped


def render_wrapper_target_safety(authority: dict[str, Any]) -> dict[str, Any]:
    rendered = render_linux_launcher(authority) or ""
    blocked = any(
        is_forbidden_runtime_value(line, authority)
        for line in rendered.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return {
        "status": "BLOCKED" if blocked else "PASS",
        "preview_path": str(preview_linux_launcher_path(authority)),
        "forbidden_reference_found": blocked,
    }


def write_preview_wrapper(authority: dict[str, Any]) -> str:
    preview_path = preview_linux_launcher_path(authority)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_text(render_linux_launcher(authority) or "", encoding="utf-8")
    try:
        preview_path.chmod(preview_path.stat().st_mode | 0o111)
    except OSError:
        pass
    return str(preview_path)


def local_runtime_probe(authority: dict[str, Any]) -> dict[str, Any]:
    command_v = run_local_shell("command -v codex || true")
    type_a = run_local_shell("type -a codex || true")
    path_lines = parse_lines(run_local_shell("printf '%s\\n' \"$PATH\" | tr ':' '\\n'")["stdout"])
    paths = runtime_paths(authority)
    preview_launcher = preview_linux_launcher_path(authority)
    launcher_text = read_text(paths["linux_launcher"])
    launcher_target = extract_wrapper_target(launcher_text)
    contaminated = [entry for entry in path_lines if is_forbidden_runtime_value(entry, authority)]
    command_v_value = str(command_v["stdout"]).strip()
    type_a_lines = parse_lines(str(type_a["stdout"]))
    type_a_paths = parse_type_a_paths(type_a_lines)
    command_info = classify_codex_candidate(
        command_v_value,
        authority,
        local_launcher=paths["linux_launcher"],
        preview_launcher=preview_launcher,
    )
    type_candidates = [
        classify_codex_candidate(
            candidate,
            authority,
            local_launcher=paths["linux_launcher"],
            preview_launcher=preview_launcher,
        )
        for candidate in type_a_paths
    ]
    local_wrapper_status = "PASS"
    local_wrapper_reason = ""
    if not paths["linux_launcher"].exists():
        local_wrapper_status = "WARN"
        local_wrapper_reason = "local wrapper does not exist"
    elif launcher_target and is_forbidden_runtime_value(launcher_target, authority):
        local_wrapper_status = "BLOCKED"
        local_wrapper_reason = "local wrapper still targets the forbidden Windows-mounted launcher"
    live_status = "BLOCKED" if command_info["status"] == "BLOCKED" else ("PASS" if command_v_value else "WARN")
    client_surface_status = {
        "status": "WARN" if contaminated else "PASS",
        "reason": "client session PATH includes injected Codex app runtime paths" if contaminated else "",
    }
    local_shell_status = collapse_status(
        [
            live_status,
            local_path_precedence(path_lines, authority, paths["linux_launcher"])["status"],
            local_wrapper_status,
        ]
    )
    return {
        "command_v": command_v_value,
        "type_a": type_a_lines,
        "type_a_paths": type_a_paths,
        "path_entries": path_lines,
        "contaminated_entries": contaminated,
        "local_live_codex_resolution_status": {
            "status": live_status,
            "reason": command_info["reason"] if live_status == "BLOCKED" else "",
        },
        "local_path_precedence_status": local_path_precedence(path_lines, authority, paths["linux_launcher"]),
        "config_surfaces": {
            "linux": config_surface_classification(paths["linux_config"], authority),
            "windows_mirror": config_surface_classification(paths["windows_config"], authority),
        },
        "local_wrapper_probe": {
            "path": str(paths["linux_launcher"]),
            "exists": paths["linux_launcher"].exists(),
            "target": launcher_target,
            "failure_mode": "exit 127" if "exit 127" in launcher_text else "",
            "status": local_wrapper_status,
            "reason": local_wrapper_reason,
        },
        "client_surface_status": client_surface_status,
        "local_shell_status": {
            "status": local_shell_status,
            "reason": "local shell still resolves or routes through forbidden runtime surfaces" if local_shell_status == "BLOCKED" else "",
        },
        "command_v_candidate": command_info,
        "type_a_candidates": type_candidates,
        "path_normalizer": detect_path_normalizer_surface(authority),
    }


def remote_runtime_probe(authority: dict[str, Any], host_alias: str, repo_root: Path) -> dict[str, Any]:
    repo_q = shlex.quote(str(repo_root))
    hostname_result = run_ssh(host_alias, "hostname")
    pwd_result = run_ssh(host_alias, f"cd {repo_q} && pwd")
    command_v = run_ssh(host_alias, f"cd {repo_q} && command -v codex || true")
    type_a = run_ssh(host_alias, f"cd {repo_q} && type -a codex || true")
    path_result = run_ssh(host_alias, "printf '%s\\n' \"$PATH\" | tr ':' '\\n'")
    path_entries = parse_lines(str(path_result["stdout"]))
    contaminated = [entry for entry in path_entries if is_forbidden_runtime_value(entry, authority)]
    ssh_available = bool(hostname_result["ok"])
    hostname_value = str(hostname_result["stdout"]).strip()
    pwd_value = str(pwd_result["stdout"]).strip()
    command_v_value = str(command_v["stdout"]).strip()
    type_a_lines = parse_lines(str(type_a["stdout"]))
    type_a_paths = parse_type_a_paths(type_a_lines)
    paths = runtime_paths(authority)
    preview_launcher = preview_linux_launcher_path(authority)
    command_info = classify_codex_candidate(
        command_v_value,
        authority,
        local_launcher=paths["linux_launcher"],
        preview_launcher=preview_launcher,
    )
    type_candidates = [
        classify_codex_candidate(
            candidate,
            authority,
            local_launcher=paths["linux_launcher"],
            preview_launcher=preview_launcher,
        )
        for candidate in type_a_paths
    ]
    native_candidates = select_native_candidates([command_info, *type_candidates])
    ssh_runtime_status = {
        "status": "PASS" if ssh_available else "BLOCKED",
        "reason": "" if ssh_available else "canonical SSH runtime is unavailable",
    }
    remote_repo_root_status = {
        "status": "PASS" if ssh_available and pwd_value == str(repo_root) else "BLOCKED",
        "reason": "" if ssh_available and pwd_value == str(repo_root) else "canonical SSH repo root could not be confirmed",
        "observed_repo_root": pwd_value,
    }
    remote_path_contamination_status = {
        "status": "PASS" if ssh_available and not contaminated else "BLOCKED",
        "reason": "" if ssh_available and not contaminated else "remote PATH contains forbidden Windows-mounted Codex paths or SSH is unavailable",
        "contaminated_entries": contaminated,
    }
    if not ssh_available:
        remote_codex_status = "BLOCKED"
        remote_codex_reason = "remote codex resolution could not be checked because SSH is unavailable"
    elif not command_v_value:
        remote_codex_status = "WARN"
        remote_codex_reason = "remote command -v codex did not resolve a codex binary"
    else:
        remote_codex_status = str(command_info["status"])
        remote_codex_reason = str(command_info["reason"])
    remote_codex_resolution_status = {
        "status": remote_codex_status,
        "reason": remote_codex_reason,
        "command_v": command_v_value,
        "command_v_candidate": command_info,
    }
    remote_native_codex_status = {
        "status": (
            "BLOCKED" if not ssh_available else
            "PASS" if native_candidates else
            "WARN"
        ),
        "reason": (
            "SSH is unavailable, so Linux-native codex detection could not be confirmed"
            if not ssh_available
            else ""
            if native_candidates
            else "no Linux-native codex absolute path was confirmed in the canonical SSH runtime"
        ),
        "candidates": native_candidates,
        "selected_path": str(native_candidates[0]["path"]) if native_candidates else "",
    }
    canonical_execution_status = collapse_status(
        [
            ssh_runtime_status["status"],
            remote_repo_root_status["status"],
            remote_path_contamination_status["status"],
        ]
    )
    return {
        "host_alias": host_alias,
        "hostname": hostname_value,
        "ssh_available": ssh_available,
        "stderr": str(hostname_result["stderr"] or pwd_result["stderr"] or command_v["stderr"] or path_result["stderr"]).strip(),
        "type_a": type_a_lines,
        "type_a_paths": type_a_paths,
        "type_a_candidates": type_candidates,
        "path_entries": path_entries,
        "ssh_runtime_status": ssh_runtime_status,
        "canonical_ssh_runtime_status": {
            "status": canonical_execution_status,
            "reason": "" if canonical_execution_status == "PASS" else "canonical SSH runtime is unavailable or contaminated",
        },
        "remote_repo_root_status": remote_repo_root_status,
        "remote_codex_resolution_status": remote_codex_resolution_status,
        "remote_native_codex_status": remote_native_codex_status,
        "remote_path_contamination_status": remote_path_contamination_status,
    }


def skipped_remote_runtime_probe(reason: str) -> dict[str, Any]:
    return {
        "host_alias": "",
        "hostname": "",
        "ssh_available": False,
        "stderr": reason,
        "type_a": [],
        "type_a_paths": [],
        "type_a_candidates": [],
        "path_entries": [],
        "ssh_runtime_status": {
            "status": "WARN",
            "reason": reason,
        },
        "canonical_ssh_runtime_status": {
            "status": "WARN",
            "reason": reason,
        },
        "remote_repo_root_status": {
            "status": "WARN",
            "reason": reason,
            "observed_repo_root": "",
        },
        "remote_codex_resolution_status": {
            "status": "WARN",
            "reason": reason,
            "command_v": "",
            "command_v_candidate": {},
        },
        "remote_native_codex_status": {
            "status": "WARN",
            "reason": reason,
            "candidates": [],
            "selected_path": "",
        },
        "remote_path_contamination_status": {
            "status": "WARN",
            "reason": reason,
            "contaminated_entries": [],
        },
    }


def build_wrapper_apply_readiness(
    *,
    canonical_execution_status: str,
    remote_repo_root_status: dict[str, Any],
    remote_codex_resolution_status: dict[str, Any],
    remote_native_codex_status: dict[str, Any],
    remote_path_contamination_status: dict[str, Any],
    windows_app_ssh_readiness: dict[str, Any],
    config_provenance: dict[str, Any],
    wrapper_target_safety_status: dict[str, Any],
) -> dict[str, Any]:
    provenance_gate_status = str(config_provenance.get("gate_status", config_provenance.get("status", "WARN")))
    gates = {
        "canonical_execution_status": canonical_execution_status,
        "remote_repo_root_status": str(remote_repo_root_status.get("status", "WARN")),
        "remote_codex_resolution_status": str(remote_codex_resolution_status.get("status", "WARN")),
        "remote_native_codex_status": str(remote_native_codex_status.get("status", "WARN")),
        "remote_path_contamination_status": str(remote_path_contamination_status.get("status", "WARN")),
        "windows_app_ssh_readiness": "PASS" if str(windows_app_ssh_readiness.get("status", "WARN")) == "PASS" else "WARN" if str(windows_app_ssh_readiness.get("status", "WARN")) == "WARN" else "BLOCKED",
        "config_provenance": provenance_gate_status,
        "wrapper_target_safety_status": str(wrapper_target_safety_status.get("status", "WARN")),
    }
    ready = all(value == "PASS" for key, value in gates.items() if key != "windows_app_ssh_readiness") and gates["windows_app_ssh_readiness"] in {"PASS", "WARN"}
    return {
        "status": "PASS" if ready else "BLOCKED",
        "ready": ready,
        "gates": gates,
        "remote_native_codex_path": str(remote_native_codex_status.get("selected_path", "")),
        "reason": "" if ready else "live wrapper apply remains gated on canonical SSH readiness, remote codex safety, native codex detection, config provenance, and Windows App-side SSH readiness",
    }


def manual_remediation_lines(runtime_report: dict[str, Any], git_report: dict[str, Any], workspace_dependency_report: dict[str, Any] | None = None) -> list[str]:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    workspace_dependency_report = workspace_dependency_report or {}
    workspace_dependency_status = str(workspace_dependency_report.get("tool_status", "")).strip()
    return [
        "# Manual System Remediation",
        "",
        f"- Generated at: {timestamp}",
        "- Windows Codex app and /mnt/c/Users/anise/.codex/bin/wsl/codex are external dependencies and are not repo repair targets.",
        "- Edit /etc/wsl.conf manually to include:",
        "  [interop]",
        "  enabled=true",
        "  appendWindowsPath=false",
        "  [boot]",
        "  systemd=true",
        "- After editing /etc/wsl.conf, restart WSL manually from PowerShell with: wsl.exe --shutdown",
        "- Add or verify the user-level SSH alias in ~/.ssh/config.d/dev-management.conf and ensure ~/.ssh/config includes ~/.ssh/config.d/*.conf.",
        "- If SSH authentication still fails, review authorized_keys markers, private key permissions, and known_hosts manually.",
        "- Windows PATH is not repo-owned; if Codex app sessions keep injecting .codex/tmp/arg0 or .codex/bin/wsl, treat that as a client-surface warning and correct it outside the repo.",
        "- Reconcile Windows Git and WSL Git config drift manually. Current Git surface status: " + str(git_report.get("status", "UNKNOWN")),
        "- Review Windows Git safe.directory, credential helper, core.autocrlf, and LFS settings against the WSL Git configuration before using mixed surfaces.",
        *([
            "- Current Codex app settings disable workspace dependency tools; enable Codex dependencies in the app before expecting load/install workspace dependency tools to work."
        ] if workspace_dependency_status == "DISABLED_IN_APP_SETTINGS" else []),
        "- Install or expose a Linux-native codex binary inside the canonical SSH runtime if remote native detection remains incomplete.",
        "- The local PATH normalizer at ~/.config/shell/wsl-runtime-paths.sh is currently not repo-owned; update it manually if you want to strip .codex/tmp/arg0 or .codex/bin/wsl entries.",
        "- Rollback for user-level SSH activation: remove ~/.ssh/config.d/dev-management.conf, remove the Dev-Management include block from ~/.ssh/config, remove the marker block from authorized_keys, and delete ~/.ssh/devmgmt_wsl_ed25519(.pub) if it was created solely for this runtime.",
        "- Current canonical execution status: " + str(runtime_report.get("canonical_execution_status", "UNKNOWN")),
    ]


def write_manual_remediation_report(repo_root: Path, runtime_report: dict[str, Any], git_report: dict[str, Any]) -> str:
    reports_dir = repo_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    workspace_dependency_report = load_json(reports_dir / "workspace-dependency-surface.json", default={})
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = reports_dir / f"manual-system-remediation-{timestamp}.md"
    path.write_text("\n".join(manual_remediation_lines(runtime_report, git_report, workspace_dependency_report)) + "\n", encoding="utf-8")
    return str(path)


def git_diff_check_status(repo_root: Path) -> dict[str, Any]:
    if not (repo_root / ".git").exists():
        return {"status": "WARN", "reason": "repo root does not expose .git during this probe"}
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--check"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (result.stdout or "") + (result.stderr or "")
    return {
        "status": "PASS" if result.returncode == 0 else "BLOCKED",
        "reason": "" if result.returncode == 0 else output.strip() or "git diff --check reported problems",
    }


def summarize_path_contamination(local: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    remote_status = str(remote.get("remote_path_contamination_status", {}).get("status", "WARN"))
    client_status = str(local.get("client_surface_status", {}).get("status", "PASS"))
    status = "BLOCKED" if remote_status == "BLOCKED" else "WARN" if client_status != "PASS" else "PASS"
    return {
        "status": status,
        "client_surface_status": client_status,
        "remote_path_status": remote_status,
        "local_contaminated_entries": list(local.get("contaminated_entries", [])),
        "remote_contaminated_entries": list(remote.get("remote_path_contamination_status", {}).get("contaminated_entries", [])),
    }


def evaluate_global_runtime(repo_root: str | Path | None = None, *, mode: str = "auto", ssh_host: str = "") -> dict[str, Any]:
    authority = load_authority(repo_root)
    repo_path = Path(repo_root).expanduser().resolve() if repo_root else ROOT
    surface = canonical_surface(authority)
    selected_mode = mode
    if mode == "auto" and str(surface.get("id", "")).strip() == "ssh-devmgmt-wsl":
        selected_mode = "ssh-managed"
    host_alias = ssh_host or str(surface.get("host_alias", "devmgmt-wsl")).strip()

    local = local_runtime_probe(authority)
    if selected_mode == "ssh-managed":
        remote = remote_runtime_probe(authority, host_alias, repo_path)
    else:
        remote = skipped_remote_runtime_probe("canonical SSH runtime is not the selected execution authority for this workspace")
    config_provenance = evaluate_config_provenance(repo_path)
    windows_app_ssh_readiness = evaluate_windows_app_ssh_readiness(repo_path)
    wrapper_target_safety_status = render_wrapper_target_safety(authority)
    preview_path = write_preview_wrapper(authority)

    ssh_runtime_status = str(remote.get("ssh_runtime_status", {}).get("status", "WARN"))
    canonical_execution_status = (
        collapse_status(
            [
                ssh_runtime_status,
                str(remote.get("remote_repo_root_status", {}).get("status", "WARN")),
                str(remote.get("remote_path_contamination_status", {}).get("status", "WARN")),
            ]
        )
        if selected_mode == "ssh-managed"
        else "WARN"
    )
    client_surface_status = str(local.get("client_surface_status", {}).get("status", "PASS"))
    local_shell_status = str(local.get("local_shell_status", {}).get("status", "PASS"))
    codex_resolution_status = collapse_status(
        [
            str(remote.get("remote_codex_resolution_status", {}).get("status", "WARN")),
            str(remote.get("remote_native_codex_status", {}).get("status", "WARN")),
        ]
        if selected_mode == "ssh-managed"
        else [
            str(local.get("local_live_codex_resolution_status", {}).get("status", "WARN")),
            str(local.get("local_wrapper_probe", {}).get("status", "WARN")),
        ]
    )
    path_contamination_status = summarize_path_contamination(local, remote)
    wrapper_apply_readiness = build_wrapper_apply_readiness(
        canonical_execution_status=canonical_execution_status,
        remote_repo_root_status=remote.get("remote_repo_root_status", {}),
        remote_codex_resolution_status=remote.get("remote_codex_resolution_status", {}),
        remote_native_codex_status=remote.get("remote_native_codex_status", {}),
        remote_path_contamination_status=remote.get("remote_path_contamination_status", {}),
        windows_app_ssh_readiness=windows_app_ssh_readiness,
        config_provenance=config_provenance,
        wrapper_target_safety_status=wrapper_target_safety_status,
    )

    if selected_mode == "local":
        overall_status = "BLOCKED" if local_shell_status == "BLOCKED" or path_contamination_status["status"] == "BLOCKED" else collapse_status([local_shell_status, client_surface_status])
    elif canonical_execution_status != "PASS":
        overall_status = "BLOCKED"
    else:
        secondary_warnings = [
            "WARN" if client_surface_status != "PASS" else "",
            "WARN" if local_shell_status != "PASS" else "",
            "WARN" if codex_resolution_status != "PASS" else "",
            "WARN" if path_contamination_status["status"] != "PASS" else "",
            "WARN" if wrapper_apply_readiness["status"] != "PASS" else "",
        ]
        overall_status = collapse_status(secondary_warnings)

    report = {
        "status": overall_status,
        "overall_status": overall_status,
        "mode_requested": mode,
        "mode_selected": selected_mode,
        "fail_closed": selected_mode == "ssh-managed" and canonical_execution_status != "PASS",
        "canonical_execution_status": canonical_execution_status,
        "client_surface_status": client_surface_status,
        "local_shell_status": local_shell_status,
        "ssh_runtime_status": ssh_runtime_status,
        "windows_app_ssh_readiness": windows_app_ssh_readiness,
        "config_provenance": config_provenance,
        "codex_resolution_status": codex_resolution_status,
        "path_contamination_status": path_contamination_status["status"],
        "wrapper_apply_readiness": wrapper_apply_readiness,
        "canonical_ssh_runtime_status": remote["canonical_ssh_runtime_status"],
        "remote_repo_root_status": remote["remote_repo_root_status"],
        "remote_codex_resolution_status": remote["remote_codex_resolution_status"],
        "remote_native_codex_status": remote.get("remote_native_codex_status", {}),
        "remote_path_contamination_status": remote["remote_path_contamination_status"],
        "local_live_codex_resolution_status": local["local_live_codex_resolution_status"],
        "local_path_precedence_status": local["local_path_precedence_status"],
        "tests_status": {"status": "WARN", "reason": "check_global_runtime.py does not execute the repo test suite"},
        "diff_check_status": git_diff_check_status(repo_path),
        "canonical_execution_surface": surface,
        "observed_remote_evidence": authority.get("observed_remote_evidence", {}),
        "client_surface": {
            "status": client_surface_status,
            "path_entries": local.get("path_entries", []),
            "contaminated_entries": local.get("contaminated_entries", []),
        },
        "local_runtime_surface": local,
        "local_shell_surface": {
            "status": local_shell_status,
            "command_v": local.get("command_v", ""),
            "type_a": local.get("type_a", []),
            "wrapper_probe": local.get("local_wrapper_probe", {}),
        },
        "ssh_activation": {
            "status": ssh_runtime_status,
            "host_alias": host_alias,
            "hostname": remote.get("hostname", ""),
            "stderr": remote.get("stderr", ""),
        },
        "ssh_canonical_runtime": remote,
        "codex_resolution": {
            "status": codex_resolution_status,
            "remote_command_v": remote.get("remote_codex_resolution_status", {}).get("command_v", ""),
            "remote_native_codex_path": remote.get("remote_native_codex_status", {}).get("selected_path", ""),
            "remote_native_candidates": remote.get("remote_native_codex_status", {}).get("candidates", []),
            "local_command_v": local.get("command_v", ""),
        },
        "path_contamination": path_contamination_status,
        "wrapper_target_safety_status": wrapper_target_safety_status,
        "preview_wrapper_path": preview_path,
    }
    return report


def render_text_summary(report: dict[str, Any]) -> str:
    lines = [
        f"global runtime status: {report['overall_status']}",
        f"- selected mode: {report['mode_selected']}",
        f"- canonical execution: {report['canonical_execution_status']}",
        f"- client surface: {report['client_surface_status']}",
        f"- local shell: {report['local_shell_status']}",
        f"- codex resolution: {report['codex_resolution_status']}",
        f"- wrapper apply readiness: {report['wrapper_apply_readiness']['status']}",
        f"- preview wrapper: {report['preview_wrapper_path']}",
    ]
    ssh_detail = report.get("ssh_activation", {}).get("stderr", "")
    if ssh_detail:
        lines.append(f"- ssh detail: {ssh_detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit canonical execution authority, client-surface contamination, and wrapper readiness.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--mode", choices=["auto", "local", "ssh-managed"], default="auto")
    parser.add_argument("--ssh-host", default="")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from check_git_surface import evaluate_git_surfaces

    report = evaluate_global_runtime(args.repo_root, mode=args.mode, ssh_host=args.ssh_host)
    git_report = evaluate_git_surfaces()
    report["manual_remediation_report"] = write_manual_remediation_report(Path(args.repo_root).expanduser().resolve(), report, git_report)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_summary(report))
        print(f"wrote {output_path}")
        print(f"wrote {report['manual_remediation_report']}")
    return status_exit_code(report["overall_status"])


if __name__ == "__main__":
    raise SystemExit(main())
