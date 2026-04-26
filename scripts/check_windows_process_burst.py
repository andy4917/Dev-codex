#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.reports import save_json
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "windows-process-burst.final.json"
DEFAULT_TARGET_NAMES = ("python.exe", "python3.13.exe", "node.exe", "ssh.exe")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_command(value: Any) -> str:
    return " ".join(str(value or "").split())


def _proc_id(proc: dict[str, Any]) -> int:
    return int(proc.get("ProcessId") or proc.get("Id") or 0)


def _parent_id(proc: dict[str, Any]) -> int:
    return int(proc.get("ParentProcessId") or 0)


def _proc_name(proc: dict[str, Any]) -> str:
    return _normalize_name(proc.get("Name") or proc.get("ProcessName"))


def _working_set_mb(proc: dict[str, Any]) -> float:
    return round(float(proc.get("WorkingSetSize") or proc.get("WS") or 0) / 1024 / 1024, 1)


def get_windows_processes() -> list[dict[str, Any]]:
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance -ClassName Win32_Process | "
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


def sample_processes(*, duration_seconds: float, interval_seconds: float) -> list[dict[str, Any]]:
    if duration_seconds <= 0:
        return [{"sampled_at": _utc_now(), "processes": get_windows_processes()}]
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration_seconds
    while True:
        samples.append({"sampled_at": _utc_now(), "processes": get_windows_processes()})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))
    return samples


def ancestry_for(proc: dict[str, Any], by_pid: dict[int, dict[str, Any]], *, max_depth: int = 8) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[int] = set()
    parent_pid = _parent_id(proc)
    while parent_pid and parent_pid not in seen and len(chain) < max_depth:
        seen.add(parent_pid)
        parent = by_pid.get(parent_pid)
        if parent is None:
            chain.append({"pid": parent_pid, "name": "<exited-or-inaccessible>", "command_line": ""})
            break
        chain.append(
            {
                "pid": _proc_id(parent),
                "parent_pid": _parent_id(parent),
                "name": parent.get("Name") or parent.get("ProcessName"),
                "command_line": _normalize_command(parent.get("CommandLine")),
            }
        )
        parent_pid = _parent_id(parent)
    return chain


def _parent_key(proc: dict[str, Any], by_pid: dict[int, dict[str, Any]]) -> tuple[int, str, str]:
    parent = by_pid.get(_parent_id(proc))
    if parent is None:
        return (_parent_id(proc), "<exited-or-inaccessible>", "")
    return (
        _proc_id(parent),
        _proc_name(parent),
        _normalize_command(parent.get("CommandLine")),
    )


def evaluate_samples(
    samples: list[dict[str, Any]],
    *,
    target_names: tuple[str, ...] = DEFAULT_TARGET_NAMES,
    min_fanout: int = 3,
) -> dict[str, Any]:
    targets = {_normalize_name(name) for name in target_names}
    groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    timeline: list[dict[str, Any]] = []
    sample_count = len(samples)

    for sample in samples:
        processes = sample.get("processes") or []
        by_pid = {_proc_id(proc): proc for proc in processes if _proc_id(proc)}
        children_by_parent: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
        for proc in processes:
            if _proc_name(proc) not in targets:
                continue
            key = _parent_key(proc, by_pid)
            children_by_parent[key].append(proc)
            if key not in groups:
                groups[key] = {
                    "parent_pid": key[0],
                    "parent_name": key[1],
                    "parent_command_line": key[2],
                    "observed_child_pids": set(),
                    "observed_child_names": set(),
                    "max_children_in_sample": 0,
                    "sample_hits": 0,
                    "first_seen_at": sample.get("sampled_at"),
                    "last_seen_at": sample.get("sampled_at"),
                    "example_children": {},
                }

        sample_groups: list[dict[str, Any]] = []
        for key, children in children_by_parent.items():
            group = groups[key]
            group["sample_hits"] += 1
            group["last_seen_at"] = sample.get("sampled_at")
            group["max_children_in_sample"] = max(group["max_children_in_sample"], len(children))
            for child in children:
                pid = _proc_id(child)
                group["observed_child_pids"].add(pid)
                group["observed_child_names"].add(_proc_name(child))
                group["example_children"].setdefault(
                    str(pid),
                    {
                        "pid": pid,
                        "parent_pid": _parent_id(child),
                        "name": child.get("Name") or child.get("ProcessName"),
                        "working_set_mb": _working_set_mb(child),
                        "command_line": _normalize_command(child.get("CommandLine")),
                        "ancestry": ancestry_for(child, by_pid),
                    },
                )
            sample_groups.append(
                {
                    "parent_pid": key[0],
                    "parent_name": key[1],
                    "children_in_sample": len(children),
                    "child_names": sorted({_proc_name(child) for child in children}),
                }
            )
        timeline.append({"sampled_at": sample.get("sampled_at"), "groups": sample_groups})

    burst_groups = []
    for group in groups.values():
        burst_groups.append(
            {
                "parent_pid": group["parent_pid"],
                "parent_name": group["parent_name"],
                "parent_command_line": group["parent_command_line"],
                "max_children_in_sample": group["max_children_in_sample"],
                "observed_child_count": len(group["observed_child_pids"]),
                "observed_child_names": sorted(group["observed_child_names"]),
                "sample_hits": group["sample_hits"],
                "first_seen_at": group["first_seen_at"],
                "last_seen_at": group["last_seen_at"],
                "example_children": sorted(group["example_children"].values(), key=lambda item: item["pid"])[:20],
            }
        )
    burst_groups.sort(key=lambda item: (item["max_children_in_sample"], item["observed_child_count"]), reverse=True)
    responsible = [group for group in burst_groups if group["max_children_in_sample"] >= min_fanout]
    status = "WARN" if responsible else "PASS"
    return {
        "status": status,
        "checked_at": _utc_now(),
        "target_process_names": sorted(targets),
        "min_fanout": min_fanout,
        "sample_count": sample_count,
        "burst_group_count": len(responsible),
        "top_responsible_parent": responsible[0] if responsible else None,
        "burst_groups": burst_groups,
        "timeline": timeline,
        "warnings": [f"process fan-out burst detected from {len(responsible)} parent command line(s)"] if responsible else [],
        "blockers": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture short Windows Python/Node/ssh.exe fan-out bursts by parent command line.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--duration-seconds", type=float, default=5)
    parser.add_argument("--interval-seconds", type=float, default=0.25)
    parser.add_argument("--min-fanout", type=int, default=3)
    parser.add_argument("--target-name", action="append", dest="target_names", default=[])
    args = parser.parse_args()

    target_names = tuple(args.target_names) if args.target_names else DEFAULT_TARGET_NAMES
    report = evaluate_samples(
        sample_processes(duration_seconds=args.duration_seconds, interval_seconds=args.interval_seconds),
        target_names=target_names,
        min_fanout=args.min_fanout,
    )
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        parent = report.get("top_responsible_parent") or {}
        command = parent.get("parent_command_line") or "none"
        print(f"{report['status']}: burst_groups={report['burst_group_count']} top_parent={command}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
