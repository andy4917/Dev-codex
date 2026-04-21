from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


WINDOWS_LOCAL_CWD = Path("/mnt/c/Users/anise")


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
    return run_command(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, command], cwd=cwd)


def run_powershell(command: str, *, cwd: str | Path | None = None, set_userprofile: bool = True) -> dict[str, object]:
    wrapped = command
    if set_userprofile:
        wrapped = f'Set-Location $env:USERPROFILE; {command}'
    safe_cwd = cwd or (WINDOWS_LOCAL_CWD if WINDOWS_LOCAL_CWD.exists() else None)
    return run_command(["powershell.exe", "-NoProfile", "-Command", wrapped], cwd=safe_cwd)

