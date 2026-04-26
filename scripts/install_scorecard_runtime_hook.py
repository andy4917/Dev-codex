#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.path_authority import load_path_policy, windows_codex_home
from devmgmt_runtime.reports import save_json
from devmgmt_runtime.scorecard_hook import install_scorecard_hook, installed_hook_status
from devmgmt_runtime.status import status_exit_code


DEFAULT_OUTPUT_PATH = ROOT / "reports" / "scorecard-runtime-hook.final.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or verify the global scorecard UserPromptSubmit hook.")
    parser.add_argument("--apply", action="store_true", help="Write config.toml feature flag and hooks.json.")
    parser.add_argument("--codex-home", default="")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    authority = load_authority(ROOT)
    path_policy = load_path_policy(ROOT)
    codex_home = Path(args.codex_home).expanduser().resolve() if args.codex_home else windows_codex_home(path_policy)
    report = install_scorecard_hook(codex_home, authority, apply=args.apply) if args.apply else installed_hook_status(codex_home, authority)
    save_json(Path(args.output_file).expanduser().resolve(), report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['status']}: codex_hooks={report['codex_hooks_enabled']} hooks_exact={report['hooks_json_exact']}")
    return status_exit_code(str(report["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
