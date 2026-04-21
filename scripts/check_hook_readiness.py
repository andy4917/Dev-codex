#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.paths import runtime_paths
from render_codex_runtime import render_hooks, windows_hook_generation_enabled

AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "hook-readiness.unified-phase.json"


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
    values = [value for value in values if value]
    if any(value == "BLOCKED" for value in values):
        return "BLOCKED"
    if any(value == "WARN" for value in values):
        return "WARN"
    return "PASS"


def text_matches_expected(path: Path | None, expected: str | None) -> bool:
    if expected is None:
        return path is None or not path.exists()
    if path is None:
        return False
    if not path.exists() or not path.is_file():
        return False
    return path.read_text(encoding="utf-8") == expected


def load_authority(repo_root: str | Path | None = None) -> dict[str, Any]:
    authority_path = AUTHORITY_PATH if repo_root is None else Path(repo_root).expanduser().resolve() / "contracts" / "workspace_authority.json"
    return load_json(authority_path, default={})


def evaluate_hook_readiness(repo_root: str | Path | None = None) -> dict[str, Any]:
    authority = load_authority(repo_root)
    paths = runtime_paths(authority)
    runtime_hook = authority.get("generation_targets", {}).get("scorecard", {}).get("runtime_hook", {})
    runtime_hook_role = str(runtime_hook.get("role", "")).strip()
    windows_enabled = windows_hook_generation_enabled(authority)
    linux_hooks_path = paths["linux_hooks"]
    windows_hooks_path = paths["observed_windows_policy_hooks"]
    expected_linux = render_hooks(authority, windows=False)
    linux_ok = text_matches_expected(linux_hooks_path, expected_linux)
    windows_generated = bool(expected_linux) and text_matches_expected(windows_hooks_path, expected_linux)
    windows_present = windows_hooks_path.exists()
    trigger_only = runtime_hook_role in {"", "trigger_only"}
    hook_only_enforcement_claim = bool(runtime_hook_role) and runtime_hook_role != "trigger_only"
    warnings = [
        "Hooks are trigger-only. Audit, tests, and score layer remain the final enforcement gates.",
        "Windows app state remains evidence only, but Windows ~/.codex is still app-readable when present and must not carry repo-generated policy hooks.",
    ]
    if not windows_enabled:
        warnings.append("Windows hook generation is disabled because Windows policy-bearing hook files are forbidden app-readable surfaces, not authority outputs.")
    status = collapse_status(
        [
            "BLOCKED" if hook_only_enforcement_claim else "",
            "BLOCKED" if windows_generated else "",
            "WARN" if windows_present and not windows_generated else "",
            "WARN" if not linux_ok else "",
        ]
    )
    return {
        "status": status,
        "runtime_hook_role": runtime_hook_role or "unset",
        "trigger_only": trigger_only,
        "hook_only_enforcement_claim": hook_only_enforcement_claim,
        "windows_generation_enabled": windows_enabled,
        "windows_generation_reason": "Windows policy-bearing hooks are violations, not generated outputs, because Codex App can read Windows ~/.codex surfaces when they exist.",
        "linux_hooks": {"path": str(linux_hooks_path), "configured": expected_linux is not None, "matches_generated": linux_ok},
        "windows_policy_hooks": {
            "path": str(windows_hooks_path),
            "present": windows_present,
            "classification": "known_generated_cleanup_candidate" if windows_generated else "unknown_policy_surface" if windows_present else "absent",
            "status": "BLOCKED" if windows_generated else "WARN" if windows_present else "PASS",
        },
        "warnings": warnings,
    }


def render_markdown(report: dict[str, Any]) -> str:
    linux_hooks = report.get("linux_hooks", {}) if isinstance(report.get("linux_hooks"), dict) else {}
    windows_hooks = report.get("windows_policy_hooks", {}) if isinstance(report.get("windows_policy_hooks"), dict) else {}
    return "\n".join([
        "# Hook Readiness",
        "",
        f"- Status: {report.get('status', 'WARN')}",
        f"- Runtime hook role: {report.get('runtime_hook_role', 'unset')}",
        f"- Trigger only: {str(report.get('trigger_only', True)).lower()}",
        f"- Windows generation enabled: {str(report.get('windows_generation_enabled', True)).lower()}",
        f"- Windows generation reason: {report.get('windows_generation_reason', '') or '(none)'}",
        f"- Linux hooks match generated: {str(linux_hooks.get('matches_generated', False)).lower()}",
        f"- Windows policy hooks present: {str(windows_hooks.get('present', False)).lower()}",
    ]) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether generated Codex hooks are present and treat them as trigger-only.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate_hook_readiness(args.repo_root)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    output_path.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
