from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Sequence

from .path_authority import load_path_policy, windows_user_home

WINDOWS_PWSH_FALLBACKS = (
    Path(r"C:\Program Files\PowerShell\7\pwsh.exe"),
    Path(r"C:\Users\anise\AppData\Local\Microsoft\WindowsApps\pwsh.exe"),
)


def _windows_local_cwd() -> Path:
    return windows_user_home(load_path_policy())


def _coerce_cwd(cwd: str | Path | None) -> str | None:
    if cwd is None:
        return None
    return str(Path(cwd).expanduser().resolve())


def _result_payload(command: object, result: subprocess.CompletedProcess[str] | None = None, error: Exception | None = None) -> dict[str, object]:
    if error is not None:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(error),
            "command": command,
        }
    assert result is not None
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "command": command,
    }


def run_command(args: Sequence[str], *, cwd: str | Path | None = None) -> dict[str, object]:
    try:
        result = subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=_coerce_cwd(cwd),
        )
    except OSError as exc:
        return _result_payload(list(args), error=exc)
    return _result_payload(list(args), result=result)


def run_ssh(host: str, command: str, *, cwd: str | Path | None = None) -> dict[str, object]:
    if "legacy" in str(host).lower():
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "legacy Linux SSH execution is decommissioned in the Windows-native runtime model",
            "command": ["ssh", host, command],
        }
    return run_command(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command], cwd=cwd)


def powershell_executable() -> str:
    resolved = shutil.which("pwsh")
    if resolved:
        return resolved
    for candidate in WINDOWS_PWSH_FALLBACKS:
        if candidate.exists():
            return str(candidate)
    return "pwsh"


def run_powershell(command: str, *, cwd: str | Path | None = None, set_userprofile: bool = True) -> dict[str, object]:
    wrapped = command
    if set_userprofile:
        wrapped = f'Set-Location $env:USERPROFILE; {command}'
    windows_local_cwd = _windows_local_cwd()
    safe_cwd = cwd or (windows_local_cwd if windows_local_cwd.exists() else None)
    return run_command(
        [
            powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            wrapped,
        ],
        cwd=safe_cwd,
    )
