#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "windows-app-resource-health.final.json"
SERENA_SERVER_MARKER = "start-mcp-server --project-from-cwd --context=codex"
SERENA_LANGUAGE_MARKERS = (
    "TypeScriptLanguageServer",
    "tsserver",
    "typingsInstaller",
    "pyright.langserver",
    "ALLanguageServer",
    "Microsoft.Dynamics.Nav.EditorServices.Host.exe",
)
MANAGED_PROCESS_NAMES = {"serena.exe", "python.exe", "python3.13.exe", "node.exe", "cmd.exe"}
RESOURCE_WATCH_NAMES = (
    "codex",
    "dwm",
    "msmpeng",
    "node",
    "python",
    "python3.13",
    "searchfilterhost",
    "searchindexer",
    "searchprotocolhost",
    "system",
    "wmiprvse",
    "notepad",
    "logioptionsplus_agent",
    "microsoft.cmdpal.ui",
    "powertoys.powerlauncher",
    "powertoys.peek.ui",
    "explorer",
    "flicklift",
    "workloadssessionhost",
)
CODEX_ROLE_CPU_WARN_PCT = 10.0
SYSTEM_PROCESS_CPU_WARN_PCT = 10.0
SEARCH_CPU_WARN_PCT = 5.0
DEFENDER_CPU_WARN_PCT = 5.0
DWM_CPU_WARN_PCT = 10.0
WMI_CPU_WARN_PCT = 5.0
KERNEL_PRIVILEGED_WARN_PCT = 20.0
KERNEL_INTERRUPT_DPC_STORM_PCT = 5.0
WINDOWS_GPU_PREFERENCE_VALUES = {
    "default": "GpuPreference=0;",
    "power_saving": "GpuPreference=1;",
    "high_performance": "GpuPreference=2;",
}
GIT_EOL_HAZARD_WORKTREE_STATES = {"w/crlf", "w/mixed"}
GIT_EOL_LIST_CHUNK_SIZE = 100


def _normalize_command(value: Any) -> str:
    return str(value or "")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    dotnet_match = re.fullmatch(r"/Date\((?P<milliseconds>-?\d+)(?P<offset>[+-]\d{4})?\)/", text)
    if dotnet_match:
        milliseconds = int(dotnet_match.group("milliseconds"))
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _proc_id(proc: dict[str, Any]) -> int:
    return int(proc.get("ProcessId") or proc.get("Id") or 0)


def _parent_id(proc: dict[str, Any]) -> int:
    return int(proc.get("ParentProcessId") or 0)


def _proc_name(proc: dict[str, Any]) -> str:
    return str(proc.get("Name") or proc.get("ProcessName") or "").lower()


def _working_set_mb(proc: dict[str, Any]) -> float:
    return round(float(proc.get("WorkingSetSize") or proc.get("WS") or 0) / 1024 / 1024, 1)


def _age_minutes(proc: dict[str, Any], now: datetime) -> float | None:
    created = _parse_time(proc.get("CreationDate") or proc.get("StartTime"))
    if created is None:
        return None
    return round((now - created).total_seconds() / 60, 1)


def get_windows_processes() -> list[dict[str, Any]]:
    command = (
        "$ErrorActionPreference='Stop'; "
        "$query = 'Win32_Process'; "
        "try { $rows = Get-CimInstance $query } "
        "catch { $rows = Get-WmiObject $query }; "
        "$rows | "
        "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate,WorkingSetSize | "
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


def get_cpu_samples(sample_seconds: int = 3) -> dict[str, float]:
    return get_cpu_snapshot(sample_seconds).get("aggregate", {})


def get_kernel_cpu_snapshot(sample_count: int = 0) -> dict[str, Any]:
    if sample_count <= 0:
        return {}
    counters = {
        "processor_pct": r"\Processor Information(_Total)\% Processor Time",
        "privileged_pct": r"\Processor Information(_Total)\% Privileged Time",
        "interrupt_pct": r"\Processor Information(_Total)\% Interrupt Time",
        "dpc_pct": r"\Processor Information(_Total)\% DPC Time",
        "processor_queue_length": r"\System\Processor Queue Length",
    }
    try:
        completed = subprocess.run(
            ["typeperf", *counters.values(), "-sc", str(sample_count)],
            check=True,
            text=True,
            capture_output=True,
            timeout=max(15, sample_count + 10),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"failed": True, "error": str(exc)}
    rows = [row for row in csv.reader(io.StringIO(completed.stdout)) if row]
    if len(rows) < 2:
        return {"failed": True, "error": "typeperf returned no counter rows"}
    header = rows[0]
    values_by_key: dict[str, list[float]] = {key: [] for key in counters}
    for row in rows[1:]:
        if len(row) != len(header):
            continue
        for index, column in enumerate(header[1:], start=1):
            for key, counter in counters.items():
                if column.lower().endswith(counter.lower()):
                    try:
                        values_by_key[key].append(float(row[index]))
                    except ValueError:
                        pass
    averages = {
        key: round(sum(values) / len(values), 1)
        for key, values in values_by_key.items()
        if values
    }
    return {
        "failed": False,
        "sample_count": sample_count,
        "averages": averages,
    }


def get_cpu_snapshot(sample_seconds: int = 3) -> dict[str, Any]:
    if sample_seconds <= 0:
        return {"aggregate": {}, "processes": [], "logical_processors": None}
    command = (
        "$ErrorActionPreference='Stop'; "
        "$logicalProcessors = [Environment]::ProcessorCount; "
        "$names = @('" + "','".join(RESOURCE_WATCH_NAMES) + "'); "
        "$before = @{}; "
        "Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $names -contains $_.ProcessName.ToLowerInvariant() } | "
        "ForEach-Object { $before[$_.Id] = [pscustomobject]@{Name=$_.ProcessName.ToLowerInvariant(); CPU=$_.CPU} }; "
        f"Start-Sleep -Seconds {sample_seconds}; "
        "$rows = foreach ($p in Get-Process -ErrorAction SilentlyContinue) { "
        "if ($before.ContainsKey($p.Id)) { "
        "$b=$before[$p.Id]; "
        "[pscustomobject]@{ProcessId=$p.Id; Instance=$b.Name; AvgCpuPct=[math]::Round((($p.CPU-$b.CPU)/"
        f"{sample_seconds}"
        ")*100,1)} "
        "} }; "
        "$aggregate = $rows | Group-Object Instance | ForEach-Object { "
        "[pscustomobject]@{Instance=$_.Name; AvgCpuPct=[math]::Round((($_.Group | Measure-Object AvgCpuPct -Sum).Sum),1)} "
        "}; "
        "[pscustomobject]@{Aggregate=$aggregate; Processes=$rows; LogicalProcessors=$logicalProcessors} | ConvertTo-Json -Depth 4"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = completed.stdout.strip()
    if not payload:
        return {"aggregate": {}, "processes": []}
    parsed = json.loads(payload)
    aggregate_rows = parsed.get("Aggregate") or []
    process_rows = parsed.get("Processes") or []
    if isinstance(aggregate_rows, dict):
        aggregate_rows = [aggregate_rows]
    if isinstance(process_rows, dict):
        process_rows = [process_rows]
    return {
        "aggregate": {str(row["Instance"]): float(row["AvgCpuPct"]) for row in aggregate_rows},
        "processes": [
            {
                "pid": int(row.get("ProcessId") or 0),
                "instance": str(row.get("Instance") or ""),
                "avg_cpu_pct": float(row.get("AvgCpuPct") or 0),
            }
            for row in process_rows
        ],
        "logical_processors": int(parsed.get("LogicalProcessors") or 0) or None,
    }


def children_by_parent(processes: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    children: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for proc in processes:
        children[_parent_id(proc)].append(proc)
    return children


def descendants(root_pid: int, children: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    stack = list(children.get(root_pid, []))
    seen: set[int] = set()
    while stack:
        proc = stack.pop()
        pid = _proc_id(proc)
        if pid in seen:
            continue
        seen.add(pid)
        found.append(proc)
        stack.extend(children.get(pid, []))
    return found


def is_serena_root(proc: dict[str, Any]) -> bool:
    return _proc_name(proc) == "serena.exe" and SERENA_SERVER_MARKER in _normalize_command(proc.get("CommandLine"))


def is_stale_al_language_process(proc: dict[str, Any]) -> bool:
    command = _normalize_command(proc.get("CommandLine"))
    return "ALLanguageServer" in command or "Microsoft.Dynamics.Nav.EditorServices.Host.exe" in command


def codex_process_role(proc: dict[str, Any]) -> str:
    command = _normalize_command(proc.get("CommandLine")).lower()
    name = _proc_name(proc)
    if name == "codex.exe" and "app-server" in command:
        return "app_server"
    if "--type=renderer" in command:
        return "renderer"
    if "--type=gpu-process" in command:
        return "gpu_process"
    if "--type=utility" in command:
        return "utility"
    if "--type=crashpad-handler" in command:
        return "crashpad"
    if name == "codex.exe":
        return "main"
    return "other"


def codex_disable_gpu_enabled(processes: list[dict[str, Any]]) -> bool:
    for proc in processes:
        if codex_process_role(proc) != "main":
            continue
        if "--disable-gpu" in _normalize_command(proc.get("CommandLine")).lower():
            return True
    return False


def process_executable_path(proc: dict[str, Any]) -> str:
    executable = str(proc.get("ExecutablePath") or "").strip()
    if executable:
        return executable
    command = _normalize_command(proc.get("CommandLine")).strip()
    quoted = re.match(r'^"(?P<path>[^"]+\.exe)"', command, re.IGNORECASE)
    if quoted:
        return quoted.group("path")
    plain = re.match(r"^(?P<path>\S+\.exe)", command, re.IGNORECASE)
    return plain.group("path") if plain else ""


def codex_executable_paths(processes: list[dict[str, Any]]) -> list[str]:
    paths = {
        process_executable_path(proc)
        for proc in processes
        if _proc_name(proc) == "codex.exe" and process_executable_path(proc)
    }
    return sorted(paths, key=str.lower)


def set_codex_gpu_preference(
    processes: list[dict[str, Any]],
    *,
    preference: str = "power_saving",
) -> dict[str, Any]:
    value = WINDOWS_GPU_PREFERENCE_VALUES.get(preference)
    if value is None:
        return {
            "attempted": [],
            "changed": [],
            "failed": [],
            "preference": preference,
            "blocked": True,
            "reason": f"unknown Windows GPU preference: {preference}",
        }
    paths = codex_executable_paths(processes)
    if not paths:
        return {"attempted": [], "changed": [], "failed": [], "preference": preference, "value": value}
    command = (
        "$ErrorActionPreference='Stop'; "
        "$paths = ConvertFrom-Json @'\n"
        + json.dumps(paths, ensure_ascii=False)
        + "\n'@; "
        "$key='HKCU:\\Software\\Microsoft\\DirectX\\UserGpuPreferences'; "
        "New-Item -Path $key -Force | Out-Null; "
        "$rows = foreach ($path in $paths) { "
        "try { "
        f"New-ItemProperty -Path $key -Name $path -PropertyType String -Value '{value}' -Force | Out-Null; "
        "[pscustomobject]@{path=$path; value=(Get-ItemPropertyValue -Path $key -Name $path); status='changed'} "
        "} catch { "
        "[pscustomobject]@{path=$path; error=$_.Exception.Message; status='failed'} "
        "} "
        "}; "
        "$rows | ConvertTo-Json -Depth 3"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        return {
            "attempted": paths,
            "changed": [],
            "failed": [
                {
                    "path": path,
                    "status": "failed",
                    "error": (exc.stderr or exc.stdout or str(exc)).strip(),
                }
                for path in paths
            ],
            "preference": preference,
            "value": value,
            "blocked": True,
            "requires_restart": False,
        }
    payload = completed.stdout.strip()
    try:
        rows = json.loads(payload) if payload else []
    except json.JSONDecodeError as exc:
        return {
            "attempted": paths,
            "changed": [],
            "failed": [
                {
                    "path": path,
                    "status": "failed",
                    "error": f"failed to parse registry update output: {exc}",
                }
                for path in paths
            ],
            "preference": preference,
            "value": value,
            "blocked": True,
            "requires_restart": False,
            "stdout": payload,
        }
    rows = rows if isinstance(rows, list) else [rows]
    return {
        "attempted": paths,
        "changed": [row for row in rows if row.get("status") == "changed"],
        "failed": [row for row in rows if row.get("status") == "failed"],
        "preference": preference,
        "value": value,
        "requires_restart": True,
    }


def parse_git_eol_line(line: str) -> dict[str, str] | None:
    match = re.match(
        r"^(?P<index>i/\S+)\s+(?P<worktree>w/\S+)\s+(?P<attr>attr/[^\t]+)\t(?P<path>.+)$",
        line,
    )
    if not match:
        return None
    return {
        "index": match.group("index"),
        "worktree": match.group("worktree"),
        "attr": match.group("attr").strip(),
        "path": match.group("path"),
    }


def is_git_eol_hazard(row: dict[str, str]) -> bool:
    attr = row.get("attr", "")
    return (
        row.get("worktree") in GIT_EOL_HAZARD_WORKTREE_STATES
        and "eol=lf" in attr
        and "-text" not in attr
    )


def get_dirty_git_eol_hazards(repo_root: Path = ROOT, *, limit: int = 50) -> dict[str, Any]:
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "--"],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {
            "count": 0,
            "files": [],
            "failed": True,
            "error": str(exc),
        }
    dirty_files = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    if not dirty_files:
        return {"count": 0, "files": [], "failed": False, "truncated": False}

    rows: list[dict[str, str]] = []
    for offset in range(0, len(dirty_files), GIT_EOL_LIST_CHUNK_SIZE):
        chunk = dirty_files[offset : offset + GIT_EOL_LIST_CHUNK_SIZE]
        try:
            eol = subprocess.run(
                ["git", "ls-files", "--eol", "--", *chunk],
                cwd=repo_root,
                check=True,
                text=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            return {
                "count": 0,
                "files": [],
                "failed": True,
                "error": str(exc),
            }
        for line in eol.stdout.splitlines():
            parsed = parse_git_eol_line(line)
            if parsed and is_git_eol_hazard(parsed):
                rows.append(parsed)

    return {
        "count": len(rows),
        "files": rows[:limit],
        "failed": False,
        "truncated": len(rows) > limit,
    }


def refresh_report_status(report: dict[str, Any]) -> None:
    report["status"] = "BLOCKED" if report.get("blockers") else "WARN" if report.get("warnings") else "PASS"


def append_requested_action_issues(report: dict[str, Any], action_key: str, label: str) -> None:
    result = report.get(action_key)
    if not isinstance(result, dict):
        return
    failed = [item for item in result.get("failed", []) if isinstance(item, dict)]
    if bool(result.get("blocked", False)):
        reason = str(result.get("reason", "")).strip()
        if not reason and failed:
            reason = str(failed[0].get("error", "")).strip()
        report.setdefault("blockers", []).append(f"{label} blocked: {reason or 'unknown error'}")
        return
    if failed:
        report.setdefault("warnings", []).append(f"{label} had failed target(s): {len(failed)}")


def managed_cleanup_targets(
    processes: list[dict[str, Any]],
    *,
    now: datetime,
    stale_minutes: float,
    keep_serena_roots: int,
    duplicate_serena_grace_minutes: float = 10,
    cleanup_duplicate_serena_roots: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_parent = children_by_parent(processes)
    roots = sorted(
        [proc for proc in processes if is_serena_root(proc)],
        key=lambda proc: _parse_time(proc.get("CreationDate")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    keep = {_proc_id(proc) for proc in roots[:keep_serena_roots]}
    selected: dict[int, dict[str, Any]] = {}
    reasons: dict[int, str] = {}

    protected_duplicate_roots: list[dict[str, Any]] = []
    for proc in roots[keep_serena_roots:]:
        pid = _proc_id(proc)
        age = _age_minutes(proc, now)
        if age is not None and age >= duplicate_serena_grace_minutes and cleanup_duplicate_serena_roots:
            selected[pid] = proc
            reasons[pid] = f"duplicate_serena_root_age_{age}m"
            for child in descendants(pid, by_parent):
                child_pid = _proc_id(child)
                selected[child_pid] = child
                reasons[child_pid] = f"descendant_of_serena_root_{pid}"
        else:
            protected_duplicate_roots.append(proc)

    for proc in processes:
        pid = _proc_id(proc)
        age = _age_minutes(proc, now)
        if pid in keep or age is None or age < stale_minutes:
            continue
        if is_stale_al_language_process(proc):
            selected[pid] = proc
            reasons[pid] = f"stale_al_language_server_age_{age}m"

    targets = [
        proc
        for proc in selected.values()
        if _proc_name(proc) in MANAGED_PROCESS_NAMES or is_stale_al_language_process(proc)
    ]
    details = {
        "kept_serena_roots": sorted(keep),
        "duplicate_serena_root_cleanup_enabled": cleanup_duplicate_serena_roots,
        "protected_duplicate_serena_roots": [
            {
                "pid": _proc_id(proc),
                "age_minutes": _age_minutes(proc, now),
                "reason": "duplicate_serena_cleanup_disabled"
                if not cleanup_duplicate_serena_roots
                else "duplicate_serena_grace_period",
            }
            for proc in protected_duplicate_roots
        ],
        "candidate_reasons": {str(pid): reasons[pid] for pid in sorted(reasons)},
    }
    return sorted(targets, key=_proc_id), details


def evaluate_processes(
    processes: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    cpu_samples: dict[str, float] | None = None,
    process_cpu_samples: list[dict[str, Any]] | None = None,
    logical_processors: int | None = None,
    kernel_samples: dict[str, Any] | None = None,
    stale_minutes: float = 10,
    keep_serena_roots: int = 1,
    duplicate_serena_grace_minutes: float = 10,
    cleanup_duplicate_serena_roots: bool = False,
    codex_memory_warn_mb: float = 1800,
    codex_cpu_warn_pct: float = 25,
    serena_roots_warn: int = 1,
    node_count_warn: int = 12,
    python_count_warn: int = 12,
    serena_roots_max: int = 1,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    warnings: list[str] = []
    blockers: list[str] = []

    names = [_proc_name(proc) for proc in processes]
    codex = [proc for proc in processes if _proc_name(proc) in {"codex.exe"}]
    node = [proc for proc in processes if _proc_name(proc) == "node.exe"]
    python = [proc for proc in processes if _proc_name(proc) in {"python.exe", "python3.13.exe"}]
    serena_roots = [proc for proc in processes if is_serena_root(proc)]
    stale_al = [
        proc
        for proc in processes
        if is_stale_al_language_process(proc)
        and (_age_minutes(proc, now) is not None and _age_minutes(proc, now) >= stale_minutes)
    ]
    cleanup_targets, cleanup_details = managed_cleanup_targets(
        processes,
        now=now,
        stale_minutes=stale_minutes,
        keep_serena_roots=keep_serena_roots,
        duplicate_serena_grace_minutes=duplicate_serena_grace_minutes,
        cleanup_duplicate_serena_roots=cleanup_duplicate_serena_roots,
    )
    codex_mb = round(sum(_working_set_mb(proc) for proc in codex), 1)

    if "codex.exe" not in names:
        blockers.append("Codex App process is not running.")
    if len(serena_roots) > serena_roots_warn:
        warnings.append(f"duplicate Serena MCP roots detected: {len(serena_roots)}")
    if len(serena_roots) > serena_roots_max:
        blockers.append(f"Serena MCP root count exceeds maximum: {len(serena_roots)} > {serena_roots_max}")
    if stale_al:
        warnings.append(f"stale Serena AL language server processes detected: {len(stale_al)}")
    if len(node) > node_count_warn:
        warnings.append(f"Node.js process count is high: {len(node)}")
    if len(python) > python_count_warn:
        warnings.append(f"Python process count is high: {len(python)}")
    if codex_mb > codex_memory_warn_mb:
        warnings.append(f"Codex App working set is high: {codex_mb} MB")
    cpu_samples = cpu_samples or {}
    process_cpu_samples = process_cpu_samples or []
    codex_cpu = round(
        sum(value for instance, value in cpu_samples.items() if instance == "codex" or instance.startswith("codex#")),
        1,
    )
    if codex_cpu > codex_cpu_warn_pct:
        warnings.append(f"Codex App sampled CPU is high: {codex_cpu}% of one logical CPU")
    codex_system_cpu_pct = (
        round(codex_cpu / logical_processors, 1)
        if logical_processors and logical_processors > 0
        else None
    )
    codex_by_pid = {_proc_id(proc): proc for proc in codex}
    codex_cpu_by_role: dict[str, float] = defaultdict(float)
    codex_process_cpu_details: list[dict[str, Any]] = []
    for sample in process_cpu_samples:
        pid = int(sample.get("pid") or 0)
        proc = codex_by_pid.get(pid)
        if proc is None:
            continue
        role = codex_process_role(proc)
        value = round(float(sample.get("avg_cpu_pct") or 0), 1)
        codex_cpu_by_role[role] += value
        codex_process_cpu_details.append(
            {
                "pid": pid,
                "role": role,
                "avg_cpu_pct": value,
                "working_set_mb": _working_set_mb(proc),
                "command_line": _normalize_command(proc.get("CommandLine")),
            }
        )
    for role, value in sorted(codex_cpu_by_role.items(), key=lambda item: item[1], reverse=True):
        value = round(value, 1)
        if value > CODEX_ROLE_CPU_WARN_PCT:
            warnings.append(f"Codex App {role} sampled CPU is high: {value}%")
    search_cpu = round(
        sum(
            value
            for instance, value in cpu_samples.items()
            if instance in {"searchindexer", "searchprotocolhost", "searchfilterhost"}
        ),
        1,
    )
    defender_cpu = round(float(cpu_samples.get("msmpeng", 0)), 1)
    system_cpu = round(float(cpu_samples.get("system", 0)), 1)
    dwm_cpu = round(float(cpu_samples.get("dwm", 0)), 1)
    wmi_cpu = round(float(cpu_samples.get("wmiprvse", 0)), 1)
    if search_cpu > SEARCH_CPU_WARN_PCT:
        warnings.append(
            "Windows Search indexing sampled CPU is high: "
            f"{search_cpu}%; exclude high-churn development and Codex app-state paths."
        )
    if defender_cpu > DEFENDER_CPU_WARN_PCT:
        warnings.append(
            "Microsoft Defender sampled CPU is high: "
            f"{defender_cpu}%; add measured dev-path exclusions before broad code/log scans."
        )
    if system_cpu > SYSTEM_PROCESS_CPU_WARN_PCT:
        warnings.append(
            f"Windows System sampled CPU is high: {system_cpu}%; inspect kernel/file-system/driver pressure."
        )
    if wmi_cpu > WMI_CPU_WARN_PCT:
        warnings.append(f"WMI Provider Host sampled CPU is high: {wmi_cpu}%; avoid repeated CIM polling.")
    codex_gpu_cpu = round(codex_cpu_by_role.get("gpu_process", 0.0), 1)
    codex_renderer_cpu = round(codex_cpu_by_role.get("renderer", 0.0), 1)
    if dwm_cpu > DWM_CPU_WARN_PCT and (codex_gpu_cpu > CODEX_ROLE_CPU_WARN_PCT or codex_renderer_cpu > CODEX_ROLE_CPU_WARN_PCT):
        warnings.append(
            "Desktop Window Manager CPU is high alongside Codex GPU/renderer load; "
            "suspect Chromium compositor or graphics-driver interaction."
        )
    disable_gpu_active = codex_disable_gpu_enabled(processes)
    if codex_gpu_cpu > CODEX_ROLE_CPU_WARN_PCT and not disable_gpu_active:
        warnings.append(
            "Codex App GPU process is hot while DisableGpu mode is not active; "
            "defer app restart until safe, then relaunch with DisableGpu and cleared render cache."
        )
    kernel_samples = kernel_samples or {}
    kernel_averages = kernel_samples.get("averages", {}) if isinstance(kernel_samples, dict) else {}
    privileged_pct = float(kernel_averages.get("privileged_pct") or 0)
    interrupt_pct = float(kernel_averages.get("interrupt_pct") or 0)
    dpc_pct = float(kernel_averages.get("dpc_pct") or 0)
    if (
        privileged_pct > KERNEL_PRIVILEGED_WARN_PCT
        and interrupt_pct < KERNEL_INTERRUPT_DPC_STORM_PCT
        and dpc_pct < KERNEL_INTERRUPT_DPC_STORM_PCT
    ):
        warnings.append(
            "Kernel privileged CPU is high while interrupt/DPC stay low; "
            "this fits file-system, graphics, WMI, or antivirus pressure more than a pure ISR/DPC storm."
        )
    if cleanup_targets:
        warnings.append(f"managed cleanup candidates available: {len(cleanup_targets)}")
    protected_duplicate_count = len(cleanup_details.get("protected_duplicate_serena_roots", []))
    if protected_duplicate_count:
        warnings.append(
            "duplicate Serena MCP roots observed but protected from default cleanup: "
            f"{protected_duplicate_count}"
        )

    status = "BLOCKED" if blockers else "WARN" if warnings else "PASS"
    process_counts = {
        "codex": len(codex),
        "node": len(node),
        "python": len(python),
        "serena_roots": len(serena_roots),
        "stale_al_language_servers": len(stale_al),
    }
    working_sets = {
        "codex_mb": codex_mb,
        "node_mb": round(sum(_working_set_mb(proc) for proc in node), 1),
        "python_mb": round(sum(_working_set_mb(proc) for proc in python), 1),
    }
    return {
        "status": status,
        "checked_at": now.isoformat(),
        "stale_minutes": stale_minutes,
        "keep_serena_roots": keep_serena_roots,
        "serena_roots_max": serena_roots_max,
        "duplicate_serena_grace_minutes": duplicate_serena_grace_minutes,
        "process_counts": process_counts,
        "working_sets": working_sets,
        "cpu_samples": {
            "codex_cpu_pct": codex_cpu,
            "codex_cpu_unit": "pct_of_one_logical_cpu",
            "logical_processors": logical_processors,
            "codex_system_cpu_pct": codex_system_cpu_pct,
            "system_pressure": {
                "system_cpu_pct": system_cpu,
                "windows_search_cpu_pct": search_cpu,
                "defender_cpu_pct": defender_cpu,
                "dwm_cpu_pct": dwm_cpu,
                "wmi_cpu_pct": wmi_cpu,
                "codex_disable_gpu_active": disable_gpu_active,
            },
            "codex_by_role": {
                role: round(value, 1)
                for role, value in sorted(codex_cpu_by_role.items(), key=lambda item: item[1], reverse=True)
            },
            "codex_processes": sorted(
                codex_process_cpu_details,
                key=lambda item: item["avg_cpu_pct"],
                reverse=True,
            ),
            "top": [
                {"instance": instance, "avg_cpu_pct": value}
                for instance, value in sorted(cpu_samples.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
        },
        "kernel_samples": kernel_samples,
        "warnings": warnings,
        "blockers": blockers,
        "cleanup_candidates": [
            {
                "pid": _proc_id(proc),
                "parent_pid": _parent_id(proc),
                "name": proc.get("Name") or proc.get("ProcessName"),
                "age_minutes": _age_minutes(proc, now),
                "working_set_mb": _working_set_mb(proc),
                "command_line": _normalize_command(proc.get("CommandLine")),
            }
            for proc in cleanup_targets
        ],
        "cleanup_candidate_summary": {
            "count": len(cleanup_targets),
            "working_set_mb": round(sum(_working_set_mb(proc) for proc in cleanup_targets), 1),
            **cleanup_details,
        },
    }


def stop_processes(processes: list[dict[str, Any]]) -> dict[str, Any]:
    pids = sorted({_proc_id(proc) for proc in processes if _proc_id(proc)})
    if not pids:
        return {"attempted": [], "succeeded": [], "failed": []}
    command = (
        "$ErrorActionPreference='Continue'; "
        "$pids = @(" + ",".join(str(pid) for pid in pids) + "); "
        "$ok = @(); $fail = @(); "
        "foreach ($pidValue in $pids) { "
        "try { Stop-Process -Id $pidValue -Force -ErrorAction Stop; $ok += $pidValue } "
        "catch { $fail += $pidValue } "
        "}; "
        "[pscustomobject]@{attempted=$pids; succeeded=$ok; failed=$fail} | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout.strip() or "{}")


def throttle_codex_priority(processes: list[dict[str, Any]], priority: str = "BelowNormal") -> dict[str, Any]:
    codex_pids = sorted({_proc_id(proc) for proc in processes if _proc_name(proc) == "codex.exe" and _proc_id(proc)})
    if not codex_pids:
        return {"attempted": [], "changed": [], "failed": []}
    command = (
        "$ErrorActionPreference='Continue'; "
        "$pids = @(" + ",".join(str(pid) for pid in codex_pids) + "); "
        "$rows = foreach ($pidValue in $pids) { "
        "try { "
        "$p = Get-Process -Id $pidValue -ErrorAction Stop; "
        "$old = $p.PriorityClass.ToString(); "
        f"$p.PriorityClass = '{priority}'; "
        "try { $p.PriorityBoostEnabled = $false } catch {}; "
        "[pscustomobject]@{pid=$pidValue; old_priority=$old; new_priority=$p.PriorityClass.ToString(); priority_boost_enabled=$p.PriorityBoostEnabled; status='changed'} "
        "} catch { "
        "[pscustomobject]@{pid=$pidValue; error=$_.Exception.Message; status='failed'} "
        "} "
        "}; "
        "$rows | ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = completed.stdout.strip()
    rows = json.loads(payload) if payload else []
    rows = rows if isinstance(rows, list) else [rows]
    return {
        "attempted": codex_pids,
        "changed": [row for row in rows if row.get("status") == "changed"],
        "failed": [row for row in rows if row.get("status") == "failed"],
    }


def duplicate_serena_cleanup_risk_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempted": [],
        "succeeded": [],
        "failed": [],
        "blocked": True,
        "reason": (
            "duplicate Serena MCP roots cannot be safely mapped to the active Codex MCP transport; "
            "killing an apparently stale duplicate can close the current session transport"
        ),
        "candidate_count": report.get("cleanup_candidate_summary", {}).get("count", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Codex App resource health and safe Serena cleanup candidates.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--stale-minutes", type=float, default=10)
    parser.add_argument("--keep-serena-roots", type=int, default=1)
    parser.add_argument(
        "--duplicate-serena-grace-minutes",
        type=float,
        default=10,
        help="Minimum age before duplicate Serena MCP roots are eligible for cleanup.",
    )
    parser.add_argument(
        "--cleanup-duplicate-serena-roots",
        action="store_true",
        help="Prepare duplicate Serena MCP root cleanup candidates. Default execution is blocked unless force is also set.",
    )
    parser.add_argument(
        "--force-kill-duplicate-serena-roots",
        action="store_true",
        help="Actually stop duplicate Serena MCP roots and descendants. Use only after commit/push or explicit user approval.",
    )
    parser.add_argument("--cpu-sample-seconds", type=int, default=0)
    parser.add_argument(
        "--kernel-sample-count",
        type=int,
        default=0,
        help="Sample kernel/system PDH counters with typeperf without using WMI/CIM.",
    )
    parser.add_argument("--cleanup-stale-serena", action="store_true")
    parser.add_argument(
        "--throttle-codex-priority",
        action="store_true",
        help="Set live Codex App subprocess priority to BelowNormal and disable priority boost.",
    )
    parser.add_argument(
        "--prefer-low-power-gpu",
        action="store_true",
        help="Set Windows per-app GPU preference for live Codex executables to Power Saving. Takes effect on next app launch.",
    )
    args = parser.parse_args()

    processes = get_windows_processes()
    now = datetime.now(timezone.utc)
    cpu_snapshot = get_cpu_snapshot(args.cpu_sample_seconds)
    kernel_snapshot = get_kernel_cpu_snapshot(args.kernel_sample_count)
    report = evaluate_processes(
        processes,
        now=now,
        cpu_samples=cpu_snapshot.get("aggregate", {}),
        process_cpu_samples=cpu_snapshot.get("processes", []),
        logical_processors=cpu_snapshot.get("logical_processors"),
        kernel_samples=kernel_snapshot,
        stale_minutes=args.stale_minutes,
        keep_serena_roots=args.keep_serena_roots,
        duplicate_serena_grace_minutes=args.duplicate_serena_grace_minutes,
        cleanup_duplicate_serena_roots=args.cleanup_duplicate_serena_roots,
    )
    if args.force_kill_duplicate_serena_roots and not args.cleanup_duplicate_serena_roots:
        report.setdefault("blockers", []).append(
            "--force-kill-duplicate-serena-roots requires --cleanup-duplicate-serena-roots"
        )
    if args.cleanup_stale_serena:
        if args.cleanup_duplicate_serena_roots:
            if args.force_kill_duplicate_serena_roots:
                targets, _details = managed_cleanup_targets(
                    processes,
                    now=now,
                    stale_minutes=args.stale_minutes,
                    keep_serena_roots=args.keep_serena_roots,
                    duplicate_serena_grace_minutes=args.duplicate_serena_grace_minutes,
                    cleanup_duplicate_serena_roots=True,
                )
                report["cleanup_result"] = stop_processes(targets)
                report["warnings"].append("duplicate Serena MCP root cleanup was forced by explicit request")
            else:
                report["cleanup_result"] = duplicate_serena_cleanup_risk_report(report)
                report["warnings"].append("duplicate Serena MCP root cleanup was blocked to protect the active transport")
        else:
            targets, _details = managed_cleanup_targets(
                processes,
                now=now,
                stale_minutes=args.stale_minutes,
                keep_serena_roots=args.keep_serena_roots,
                duplicate_serena_grace_minutes=args.duplicate_serena_grace_minutes,
                cleanup_duplicate_serena_roots=False,
            )
            report["cleanup_result"] = stop_processes(targets)
        refreshed = evaluate_processes(
            get_windows_processes(),
            now=datetime.now(timezone.utc),
            cpu_samples=(refreshed_cpu_snapshot := get_cpu_snapshot(args.cpu_sample_seconds)).get("aggregate", {}),
            process_cpu_samples=refreshed_cpu_snapshot.get("processes", []),
            logical_processors=refreshed_cpu_snapshot.get("logical_processors"),
            kernel_samples=get_kernel_cpu_snapshot(args.kernel_sample_count),
            stale_minutes=args.stale_minutes,
            keep_serena_roots=args.keep_serena_roots,
            duplicate_serena_grace_minutes=args.duplicate_serena_grace_minutes,
            cleanup_duplicate_serena_roots=False,
        )
        report["post_cleanup"] = refreshed
        report["status"] = refreshed["status"]
    if args.throttle_codex_priority:
        report["codex_priority_throttle"] = throttle_codex_priority(get_windows_processes())
        refreshed_processes = get_windows_processes()
        refreshed_cpu_snapshot = get_cpu_snapshot(args.cpu_sample_seconds)
        refreshed = evaluate_processes(
            refreshed_processes,
            now=datetime.now(timezone.utc),
            cpu_samples=refreshed_cpu_snapshot.get("aggregate", {}),
            process_cpu_samples=refreshed_cpu_snapshot.get("processes", []),
            logical_processors=refreshed_cpu_snapshot.get("logical_processors"),
            kernel_samples=get_kernel_cpu_snapshot(args.kernel_sample_count),
            stale_minutes=args.stale_minutes,
            keep_serena_roots=args.keep_serena_roots,
            duplicate_serena_grace_minutes=args.duplicate_serena_grace_minutes,
            cleanup_duplicate_serena_roots=False,
        )
        report["post_priority_throttle"] = refreshed
        report["status"] = refreshed["status"]
    if args.prefer_low_power_gpu:
        report["codex_gpu_preference"] = set_codex_gpu_preference(
            get_windows_processes(),
            preference="power_saving",
        )
    append_requested_action_issues(report, "codex_priority_throttle", "Codex App priority throttle")
    append_requested_action_issues(report, "codex_gpu_preference", "Codex App low-power GPU preference")
    report["git_eol_hazards"] = get_dirty_git_eol_hazards()
    if report["git_eol_hazards"].get("failed"):
        report["warnings"].append(
            "Git EOL hazard check failed: " + str(report["git_eol_hazards"].get("error", "unknown error"))
        )
    elif report["git_eol_hazards"].get("count"):
        report["warnings"].append(
            "dirty tracked files have CRLF/mixed endings despite eol=lf: "
            f"{report['git_eol_hazards']['count']}"
        )
    refresh_report_status(report)

    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['status']}: cleanup_candidates={report['cleanup_candidate_summary']['count']}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
