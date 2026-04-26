#!/usr/bin/env python3
from __future__ import annotations

from codex_managed_process_launcher import SERENA_PROFILE, main


if __name__ == "__main__":
    raise SystemExit(main(["--profile", SERENA_PROFILE]))
