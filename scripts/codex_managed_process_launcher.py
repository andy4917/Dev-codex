#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


SERENA_PROFILE = "serena-mcp"
SERENA_SIGNATURE = "start-mcp-server --project-from-cwd --context=codex"
SERENA_PROCESS_NAMES = frozenset(
    {
        "cmd.exe",
        "node.exe",
        "py.exe",
        "python.exe",
        "python3.13.exe",
        "python3.14.exe",
        "serena.exe",
        "uv.exe",
        "uvx.exe",
    }
)
SERENA_ORPHAN_MARKERS = (
    "TypeScriptLanguageServer",
    "tsserver",
    "typingsInstaller",
    "pyright.langserver",
    "ALLanguageServer",
    "Microsoft.Dynamics.Nav.EditorServices.Host.exe",
)
DEFAULT_SERENA_ARGS = (
    "--prerelease",
    "allow",
    "--from",
    "serena-agent==1.1.2",
    "serena",
    "start-mcp-server",
    "--project-from-cwd",
    "--context=codex",
    "--open-web-dashboard",
    "False",
)


@dataclass(frozen=True)
class ProcessRow:
    pid: int
    parent_pid: int
    name: str
    command_line: str


@dataclass(frozen=True)
class ManagedProfile:
    name: str
    signature: str
    process_names: frozenset[str]
    command: tuple[str, ...]
    orphan_markers: tuple[str, ...]
    env_defaults: dict[str, str]
    lock_path: Path


@dataclass
class SingletonLock:
    path: Path
    fd: int

    def release(self) -> None:
        with suppress(OSError):
            os.close(self.fd)
        with suppress(FileNotFoundError):
            self.path.unlink()


def normalize_command(value: Any) -> str:
    return str(value or "")


def resolve_uvx() -> str:
    uvx = shutil.which("uvx")
    if uvx:
        return uvx
    winget_uvx = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links" / "uvx.exe"
    return str(winget_uvx)


def build_serena_profile() -> ManagedProfile:
    lock_path = Path(
        os.environ.get(
            "CODEX_SERENA_SINGLETON_LOCK",
            str(Path.home() / ".codex" / "managed-process-locks" / "serena-mcp.lock"),
        )
    )
    return ManagedProfile(
        name=SERENA_PROFILE,
        signature=SERENA_SIGNATURE,
        process_names=SERENA_PROCESS_NAMES,
        command=(resolve_uvx(), *DEFAULT_SERENA_ARGS),
        orphan_markers=SERENA_ORPHAN_MARKERS,
        env_defaults={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        lock_path=lock_path,
    )


def build_profile(name: str) -> ManagedProfile:
    if name == SERENA_PROFILE:
        return build_serena_profile()
    raise ValueError(f"unknown managed process profile: {name}")


def _wql_like_literal(value: str) -> str:
    return value.replace("'", "''")


def list_windows_processes(profile: ManagedProfile) -> list[ProcessRow]:
    markers = [profile.signature, *profile.orphan_markers]
    filters = " OR ".join(f"CommandLine LIKE '%{_wql_like_literal(marker)}%'" for marker in markers)
    command = (
        "$ErrorActionPreference='Stop'; "
        f"Get-CimInstance Win32_Process -Filter \"{filters}\" | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Depth 3"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
        timeout=15,
    )
    payload = completed.stdout.strip()
    if not payload:
        return []
    parsed = json.loads(payload)
    items = parsed if isinstance(parsed, list) else [parsed]
    rows: list[ProcessRow] = []
    for item in items:
        rows.append(
            ProcessRow(
                pid=int(item.get("ProcessId") or 0),
                parent_pid=int(item.get("ParentProcessId") or 0),
                name=str(item.get("Name") or ""),
                command_line=normalize_command(item.get("CommandLine")),
            )
        )
    return rows


def is_profile_process(row: ProcessRow, profile: ManagedProfile) -> bool:
    name = row.name.lower()
    command = normalize_command(row.command_line)
    if name not in profile.process_names:
        return False
    return profile.signature in command or any(marker in command for marker in profile.orphan_markers)


def cleanup_roots(rows: list[ProcessRow], profile: ManagedProfile, current_pid: int) -> list[int]:
    candidates = {
        row.pid: row
        for row in rows
        if row.pid > 0 and row.pid != current_pid and is_profile_process(row, profile)
    }
    return sorted(pid for pid, row in candidates.items() if row.parent_pid not in candidates)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        return False
    return any(line.startswith('"') and f'","{pid}",' in line for line in completed.stdout.splitlines())


def read_lock_owner(lock_path: Path) -> int | None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    pid = payload.get("pid")
    return int(pid) if isinstance(pid, int) and pid > 0 else None


def acquire_singleton_lock(
    profile: ManagedProfile,
    *,
    lock_path: Path | None = None,
    current_pid: int | None = None,
) -> SingletonLock | None:
    pid = current_pid or os.getpid()
    path = lock_path or profile.lock_path
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            owner = read_lock_owner(path)
            if owner and owner != pid and process_exists(owner):
                print(
                    f"{profile.name} already active under wrapper PID {owner}; exiting duplicate launcher",
                    file=sys.stderr,
                )
                return None
            with suppress(FileNotFoundError):
                path.unlink()
            continue
        payload = {"pid": pid, "profile": profile.name, "signature": profile.signature}
        os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
        return SingletonLock(path, fd)
    raise RuntimeError(f"failed to acquire managed process singleton lock: {path}")


def stop_process_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )


def cleanup_existing_profile_roots(profile: ManagedProfile) -> list[int]:
    try:
        roots = cleanup_roots(list_windows_processes(profile), profile, os.getpid())
    except Exception as exc:  # pragma: no cover - defensive startup guard
        print(f"{profile.name} cleanup skipped: {exc}", file=sys.stderr)
        return []
    for pid in roots:
        stop_process_tree(pid)
    return roots


def run_profile(profile: ManagedProfile, *, lock_path: Path | None = None) -> int:
    lock = acquire_singleton_lock(profile, lock_path=lock_path)
    if lock is None:
        return 0
    process: subprocess.Popen[str] | None = None
    try:
        cleanup_existing_profile_roots(profile)
        env = os.environ.copy()
        env.update({key: value for key, value in profile.env_defaults.items() if key not in env})
        process = subprocess.Popen(
            list(profile.command),
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=env,
        )
        return process.wait()
    finally:
        if process is not None and process.poll() is None:
            stop_process_tree(process.pid)
        lock.release()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Codex app-server helper process with singleton lifecycle control.")
    parser.add_argument("--profile", default=SERENA_PROFILE, choices=[SERENA_PROFILE])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return run_profile(build_profile(args.profile))


if __name__ == "__main__":
    raise SystemExit(main())
