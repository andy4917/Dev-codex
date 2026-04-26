#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json, write_markdown
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "serena-dashboard-repro.final.json"
DEFAULT_MARKDOWN_PATH = ROOT / "reports" / "serena-dashboard-repro.final.md"
DEFAULT_SCRATCH_ROOT = ROOT.parent / ".scratch" / "Dev-Management" / "serena-dashboard-repro"
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
SERENA_CONFIG_PATH = Path.home() / ".serena" / "serena_config.yml"
SERENA_LOG_ROOT = Path.home() / ".serena" / "logs"
DASHBOARD_START_RE = re.compile(r"Starting dashboard .*port=(?P<port>\d+)")
DASHBOARD_URL_RE = re.compile(r"Serena web dashboard started at (?P<url>\S+)")
MCP_LOG_NAME_RE = re.compile(r"mcp_(?P<stamp>\d{8}-\d{6})_(?P<pid>\d+)\.txt$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_text(path: Path, *, tail_bytes: int | None = None) -> str:
    if not path.exists():
        return ""
    if tail_bytes is None:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes), 0)
        return handle.read().decode("utf-8", errors="replace")


def parse_boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def read_codex_serena_config(path: Path = CODEX_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "serena": {}, "args": []}
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    serena = payload.get("mcp_servers", {}).get("serena", {})
    args = list(serena.get("args", [])) if isinstance(serena.get("args", []), list) else []
    return {
        "path": str(path),
        "exists": True,
        "serena": serena,
        "command": serena.get("command"),
        "args": args,
        "open_web_dashboard_arg": open_dashboard_arg_value(args),
    }


def open_dashboard_arg_value(args: list[Any]) -> bool | None:
    for index, arg in enumerate(args):
        text = str(arg)
        if text == "--open-web-dashboard" and index + 1 < len(args):
            return parse_boolish(args[index + 1])
        if text.startswith("--open-web-dashboard="):
            return parse_boolish(text.split("=", 1)[1])
    return None


def read_serena_global_config(path: Path = SERENA_CONFIG_PATH) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw_line in _read_text(path).splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in {"web_dashboard", "web_dashboard_open_on_launch", "gui_log_window"}:
            values[key] = parse_boolish(value)
        elif key in {"web_dashboard_listen_address", "language_backend"}:
            values[key] = value
    return {"path": str(path), "exists": path.exists(), "values": values}


def get_windows_processes() -> list[dict[str, Any]]:
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^(serena|python|python3\\.13|codex|Codex)\\.exe$' } | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate,WorkingSetSize | "
        "ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = completed.stdout.strip()
    if not payload:
        return []
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, list) else [parsed]


def serena_process_snapshot(processes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    language_server_rows = []
    for proc in processes:
        command = str(proc.get("CommandLine") or "")
        name = str(proc.get("Name") or "")
        row = {
            "pid": int(proc.get("ProcessId") or 0),
            "parent_pid": int(proc.get("ParentProcessId") or 0),
            "name": name,
            "creation_date": proc.get("CreationDate"),
            "command_line": command,
            "open_web_dashboard_arg": open_dashboard_arg_value(command.split()),
            "starts_mcp_server": "start-mcp-server" in command,
            "project_from_cwd": "--project-from-cwd" in command,
            "context_codex": "--context=codex" in command,
        }
        if "start-mcp-server" in command or name.lower() == "serena.exe":
            rows.append(row)
        elif "pyright.langserver" in command or "TypeScriptLanguageServer" in command or "tsserver" in command:
            language_server_rows.append(row)
    rows = sorted(rows, key=lambda item: item["pid"])
    return {
        "count": len(rows),
        "parent_pids": sorted({item["parent_pid"] for item in rows}),
        "all_open_web_dashboard_args_false": bool(rows) and all(
            item["open_web_dashboard_arg"] is False for item in rows
        ),
        "processes": rows,
        "language_server_count": len(language_server_rows),
        "language_servers": sorted(language_server_rows, key=lambda item: item["pid"]),
    }


def latest_log_files(log_root: Path = SERENA_LOG_ROOT, limit: int = 12) -> list[Path]:
    if not log_root.exists():
        return []
    files = [path for path in log_root.rglob("mcp_*.txt") if path.is_file()]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def summarize_log(path: Path) -> dict[str, Any]:
    text = _read_text(path, tail_bytes=512_000)
    ports = [int(match.group("port")) for match in DASHBOARD_START_RE.finditer(text)]
    urls = [match.group("url") for match in DASHBOARD_URL_RE.finditer(text)]
    match = MCP_LOG_NAME_RE.search(path.name)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "last_write_time": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        if path.exists()
        else None,
        "pid_from_filename": int(match.group("pid")) if match else None,
        "dashboard_started": bool(ports or urls),
        "dashboard_ports": ports,
        "dashboard_urls": urls,
        "open_dashboard_tool_exposed": "open_dashboard" in text,
        "shutdown_stopped_dashboard": "Stopping the dashboard viewer process" in text,
        "start_mcp_server_logged": "Starting MCP server" in text,
    }


def summarize_recent_logs(limit: int = 12) -> dict[str, Any]:
    logs = [summarize_log(path) for path in latest_log_files(limit=limit)]
    return {
        "root": str(SERENA_LOG_ROOT),
        "count": len(logs),
        "logs": logs,
        "dashboard_start_count": sum(1 for item in logs if item["dashboard_started"]),
        "dashboard_ports": sorted({port for item in logs for port in item["dashboard_ports"]}),
    }


def run_launch_probe(
    *,
    scratch_root: Path = DEFAULT_SCRATCH_ROOT,
    timeout_seconds: float = 8,
    command_args: list[str] | None = None,
) -> dict[str, Any]:
    scratch_root.mkdir(parents=True, exist_ok=True)
    before = {str(path) for path in latest_log_files(limit=50)}
    args = command_args or [
        "serena",
        "start-mcp-server",
        "--project",
        str(ROOT),
        "--context=codex",
        "--open-web-dashboard",
        "False",
    ]
    started_at = _utc_now()
    proc = subprocess.Popen(
        args,
        cwd=str(scratch_root),
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(timeout_seconds)
    return_code: int | None = proc.poll()
    terminated_by_probe = False
    if return_code is None:
        proc.terminate()
        terminated_by_probe = True
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
    else:
        stdout, stderr = proc.communicate(timeout=5)
    after_paths = latest_log_files(limit=50)
    new_logs = [path for path in after_paths if str(path) not in before and path.stat().st_mtime >= started_at.timestamp() - 2]
    return {
        "enabled": True,
        "scratch_root": str(scratch_root),
        "command": args,
        "started_at": started_at.isoformat(),
        "timeout_seconds": timeout_seconds,
        "pid": proc.pid,
        "return_code": return_code,
        "terminated_by_probe": terminated_by_probe,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "new_logs": [summarize_log(path) for path in new_logs],
        "dashboard_created": any(summarize_log(path)["dashboard_started"] for path in new_logs),
    }


def classify(report: dict[str, Any]) -> dict[str, Any]:
    codex_arg = report["codex_serena_config"].get("open_web_dashboard_arg")
    global_values = report["serena_global_config"].get("values", {})
    web_dashboard = global_values.get("web_dashboard")
    open_on_launch = global_values.get("web_dashboard_open_on_launch")
    recent_dashboard = report["recent_serena_logs"].get("dashboard_start_count", 0) > 0
    mcp_process_count = report.get("serena_process_snapshot", {}).get("count", 0)
    mcp_false_args = report.get("serena_process_snapshot", {}).get("all_open_web_dashboard_args_false")
    probe = report.get("launch_probe") or {"enabled": False}
    probe_created = bool(probe.get("dashboard_created"))
    findings: list[str] = []
    evidence: list[str] = []

    if codex_arg is False:
        evidence.append("Codex MCP config passes --open-web-dashboard False.")
    elif codex_arg is True:
        findings.append("local_workflow_requests_dashboard_open")
    else:
        findings.append("local_workflow_has_no_dashboard_open_override")

    if web_dashboard is True:
        evidence.append("Serena global config keeps web_dashboard enabled, so a dashboard server is expected.")
    elif web_dashboard is False:
        evidence.append("Serena global config disables web_dashboard.")

    if open_on_launch is False:
        evidence.append("Serena global config disables auto-opening the dashboard window/browser tab.")
    elif open_on_launch is True:
        findings.append("serena_global_config_requests_dashboard_open_on_launch")

    if recent_dashboard:
        evidence.append("Recent Serena MCP logs contain dashboard server creation events.")
    if mcp_process_count > 1:
        evidence.append(f"Live process snapshot contains {mcp_process_count} Serena MCP server processes.")
    if mcp_process_count > 1 and mcp_false_args:
        evidence.append("All live Serena MCP server processes pass --open-web-dashboard False.")
    if probe.get("enabled") and probe_created:
        evidence.append("Isolated launch probe created a dashboard while passing --open-web-dashboard False.")

    if mcp_process_count > 1 and mcp_false_args and web_dashboard is True:
        verdict = "WARN"
        root_cause = "LOCAL_CONTROL_PLANE_REPEATS_SERENA_MCP_STARTS_AND_SERENA_CREATES_ONE_DASHBOARD_SERVER_PER_ROOT"
        findings.append("local_control_plane_repeated_serena_mcp_roots")
        findings.append("serena_dashboard_server_creation_per_mcp_root")
    elif codex_arg is False and probe.get("enabled") and probe_created:
        verdict = "WARN"
        root_cause = "SERENA_DASHBOARD_SERVER_STARTS_DESPITE_LOCAL_OPEN_SUPPRESSION"
        findings.append("serena_side_dashboard_server_creation_reproduced")
    elif codex_arg is False and recent_dashboard and web_dashboard is True:
        verdict = "WARN"
        root_cause = "SERENA_CONFIG_ENABLES_DASHBOARD_SERVER_LOCAL_CONFIG_ONLY_SUPPRESSES_OPENING"
        findings.append("dashboard_server_creation_explained_by_serena_global_web_dashboard")
    elif codex_arg is True or open_on_launch is True:
        verdict = "WARN"
        root_cause = "LOCAL_WORKFLOW_OR_CONFIG_REQUESTS_DASHBOARD_OPENING"
    elif recent_dashboard:
        verdict = "WARN"
        root_cause = "DASHBOARD_CREATION_OBSERVED_WITHOUT_COMPLETE_TRIGGER_PROOF"
    else:
        verdict = "PASS"
        root_cause = "NO_DASHBOARD_CREATION_OBSERVED"

    return {
        "status": verdict,
        "root_cause": root_cause,
        "findings": findings,
        "evidence": evidence,
        "semantics": {
            "dashboard_server_creation": "controlled by Serena web_dashboard/global behavior",
            "dashboard_window_or_tab_opening": "controlled by web_dashboard_open_on_launch or --open-web-dashboard",
        },
    }


def build_report(*, run_probe: bool = False, log_limit: int = 12) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "WARN",
        "checked_at": _utc_now().isoformat(),
        "purpose": "Deterministically capture the trigger surface for repeated Serena dashboard creation.",
        "evidence_gaps": [],
        "codex_serena_config": read_codex_serena_config(),
        "serena_global_config": read_serena_global_config(),
        "serena_process_snapshot": serena_process_snapshot(get_windows_processes()),
        "recent_serena_logs": summarize_recent_logs(limit=log_limit),
        "context7_doc_evidence": {
            "library": "/oraios/serena",
            "summary": "Context7 reported that --open-web-dashboard False and web_dashboard_open_on_launch False disable automatic dashboard opening; Serena still starts a localhost web dashboard by default when web_dashboard is enabled.",
        },
        "serena_mcp_evidence": {
            "project_activation": "current session activated Dev-Management",
            "onboarding": "check_onboarding_performed reported no onboarding, and the current exposed tool namespace did not provide an onboarding callable.",
        },
    }
    if run_probe:
        report["launch_probe"] = run_launch_probe()
    else:
        report["launch_probe"] = {
            "enabled": False,
            "reason": "Use --launch-probe to start one isolated Serena process and stop only that probe process.",
        }
        report["evidence_gaps"].append("launch_probe_not_run")
    classification = classify(report)
    report["status"] = classification["status"]
    report["diagnosis"] = classification
    return report


def markdown_report(report: dict[str, Any]) -> str:
    diagnosis = report["diagnosis"]
    lines = [
        "# Serena Dashboard Repro",
        "",
        f"- status: {report['status']}",
        f"- checked_at: {report['checked_at']}",
        f"- root_cause: {diagnosis['root_cause']}",
        f"- codex_args: `{report['codex_serena_config'].get('args')}`",
        f"- codex_open_web_dashboard_arg: `{report['codex_serena_config'].get('open_web_dashboard_arg')}`",
        f"- serena_web_dashboard: `{report['serena_global_config'].get('values', {}).get('web_dashboard')}`",
        f"- serena_web_dashboard_open_on_launch: `{report['serena_global_config'].get('values', {}).get('web_dashboard_open_on_launch')}`",
        f"- recent_dashboard_start_count: `{report['recent_serena_logs'].get('dashboard_start_count')}`",
        f"- recent_dashboard_ports: `{report['recent_serena_logs'].get('dashboard_ports')}`",
        f"- launch_probe_enabled: `{report['launch_probe'].get('enabled')}`",
        f"- launch_probe_dashboard_created: `{report['launch_probe'].get('dashboard_created')}`",
        "",
        "## Diagnosis Evidence",
    ]
    for item in diagnosis["evidence"]:
        lines.append(f"- {item}")
    if report["evidence_gaps"]:
        lines.extend(["", "## Evidence Gaps"])
        for item in report["evidence_gaps"]:
            lines.append(f"- {item}")
    lines.extend(["", "## Recent Logs"])
    for item in report["recent_serena_logs"].get("logs", [])[:6]:
        lines.append(
            f"- `{item['path']}` dashboard_started={item['dashboard_started']} ports={item['dashboard_ports']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce and diagnose Serena dashboard creation trigger surface.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--launch-probe", action="store_true", help="Start one isolated Serena process and stop it after observation.")
    parser.add_argument("--log-limit", type=int, default=12)
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--markdown-file", default=str(DEFAULT_MARKDOWN_PATH))
    args = parser.parse_args()

    report = build_report(run_probe=args.launch_probe, log_limit=args.log_limit)
    output_path = Path(args.output_file).expanduser().resolve()
    markdown_path = Path(args.markdown_file).expanduser().resolve()
    save_json(output_path, report)
    write_markdown(markdown_path, markdown_report(report))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['status']}: {report['diagnosis']['root_cause']}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
