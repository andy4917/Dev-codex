#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

from check_global_runtime import evaluate_global_runtime


ROOT = Path(__file__).resolve().parents[1]


def build_remote_command(repo_root: str, argv: list[str]) -> str:
    quoted = " ".join(shlex.quote(arg) for arg in argv)
    return f"cd {shlex.quote(repo_root)} && exec {quoted}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a command on the canonical SSH runtime without local fallback.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("BLOCKED: no command was provided for canonical execution", file=sys.stderr)
        return 2

    runtime = evaluate_global_runtime(ROOT, mode="ssh-managed")
    if str(runtime.get("canonical_execution_status", "BLOCKED")) != "PASS":
        print("BLOCKED: canonical SSH runtime is unavailable", file=sys.stderr)
        detail = str(runtime.get("ssh_activation", {}).get("stderr", "")).strip()
        if detail:
            print(detail, file=sys.stderr)
        return 2

    surface = runtime.get("canonical_execution_surface", {})
    host_alias = str(surface.get("host_alias", "devmgmt-wsl")).strip() or "devmgmt-wsl"
    repo_root = str(surface.get("repo_root", ROOT))
    remote_command = build_remote_command(repo_root, command)
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", host_alias, remote_command], check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
