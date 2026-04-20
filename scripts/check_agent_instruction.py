#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from check_global_runtime import evaluate_global_runtime
from check_startup_workflow import evaluate_startup_workflow


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "contracts" / "instruction_guard_policy.json"


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
    filtered = [value for value in values if value]
    if any(value == "BLOCKED" for value in filtered):
        return "BLOCKED"
    if any(value == "WARN" for value in filtered):
        return "WARN"
    return "PASS"


def git_changed_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        text = line.rstrip()
        if not text:
            continue
        candidate = text[3:] if len(text) >= 4 else text
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        path = candidate.strip()
        if path:
            paths.append(path)
    return sorted(set(paths))


def contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def likely_code_change(text: str) -> bool:
    return contains_any(
        text,
        [
            "implement",
            "fix",
            "change",
            "modify",
            "edit",
            "update",
            "add",
            "refactor",
            "repair",
            "rewrite",
            "정리",
            "수정",
            "구현",
            "추가",
            "변경",
        ],
    )


def likely_activation_task(text: str) -> bool:
    return contains_any(
        text,
        [
            "activation",
            "bootstrap",
            "canonical runtime",
            "canonical ssh",
            "ssh alias",
            "ssh key",
            "authorized_keys",
            "runtime authority",
            "runtime activation",
            "serena startup",
            "serena metadata",
            "serena index",
            "ssh canonical",
            "활성화",
            "ssh",
        ],
    )


def likely_local_execution_request(text: str) -> bool:
    return contains_any(
        text,
        [
            "local shell",
            "run locally",
            "execute locally",
            "use local runtime",
            "use wsl shell",
            "로컬 실행",
            "로컬 shell",
            "local execution",
        ],
    )


def runtime_value(runtime: dict[str, Any], key: str, default: str = "PASS") -> str:
    value = runtime.get(key, default)
    return str(value.get("status", default) if isinstance(value, dict) else value or default)


def evaluate_instruction(
    instruction: str,
    *,
    repo_root: Path | None = None,
    activation_bootstrap: bool = False,
    bootstrap_implementation_exception: bool = False,
) -> dict[str, Any]:
    root = repo_root or ROOT
    activation_bootstrap = bool(activation_bootstrap or bootstrap_implementation_exception)
    policy = load_json(POLICY_PATH, default={})
    runtime = evaluate_global_runtime(root, mode="auto")
    startup = evaluate_startup_workflow(root, mode="auto")
    changed_paths = git_changed_paths(root)
    normalized = instruction.lower()

    reasons: list[str] = []
    warnings: list[str] = []
    reminders: list[str] = []

    runtime_overall = runtime_value(runtime, "overall_status", runtime_value(runtime, "status", "PASS"))
    canonical_status = runtime_value(runtime, "canonical_execution_status", runtime_overall)
    client_surface_status = runtime_value(runtime, "client_surface_status", "PASS")
    local_shell_status = runtime_value(runtime, "local_shell_status", runtime_overall)
    startup_status = runtime_value(startup, "status", "PASS")
    context7_blockers = list(startup.get("context7", {}).get("blockers", []))
    activation_task = likely_activation_task(normalized)
    code_change = likely_code_change(normalized)
    local_execution_request = likely_local_execution_request(normalized)

    if "codex app" in normalized and any(token in normalized for token in ["runtime", "authority", "primary"]):
        reasons.append("Codex App is a user surface only and cannot become the execution authority.")
        reminders.append(policy["required_reminders"]["runtime_authority_conflict"])
    if "/mnt/c/users/anise/.codex/bin/wsl/codex" in normalized or ("windows launcher" in normalized and "primary" in normalized):
        reasons.append("Windows-side Codex launcher cannot become the primary runtime.")
        reminders.append(policy["required_reminders"]["runtime_authority_conflict"])
    if "/mnt/c/users/anise/.codex/bin/wsl" in normalized or (".codex/tmp/arg0" in normalized and "path" in normalized):
        reasons.append("Forbidden Windows-mounted Codex paths cannot be reintroduced into PATH or wrapper targets.")
        reminders.append(policy["required_reminders"]["runtime_authority_conflict"])
    if any(token in normalized for token in ["manual edit", "수동 편집", "~/.local/bin/codex", "generated config", "generated shim"]):
        reasons.append("Generated config, wrapper, and mirror files must not be manually edited.")
    if any(token in normalized for token in ["git reset", "git clean", "rm -rf", "sudo ", "apt install", "npm install", "pip install", "wsl --shutdown", "systemctl restart"]):
        reasons.append("Destructive or system-changing commands are blocked by authority.")
        reminders.append(policy["required_reminders"]["destructive_blocked"])
    if any(token in normalized for token in ["approval policy never", "approval_policy = \"never\"", "danger-full-access", "sandbox_mode = \"danger-full-access\""]):
        reasons.append("Sandbox or approval weakening is blocked by authority.")
        reminders.append(policy["required_reminders"]["sandbox_blocked"])
    if "git.exe" in normalized and "git " in normalized:
        reasons.append("Instructions must not force mixed Windows Git and WSL Git execution.")
    if any(token in normalized for token in ["clean up unrelated", "cleanup unrelated", "revert unrelated", "format unrelated", "revert dirty", "unrelated dirty"]):
        reasons.append("Unrelated dirty changes must remain untouched.")
        reminders.append(policy["required_reminders"]["unrelated_dirty_present"])

    if startup_status == "BLOCKED" and code_change:
        if activation_task and activation_bootstrap:
            warnings.append("Activation bootstrap waived the Serena gate for this process only.")
            reminders.append(policy["required_reminders"]["serena_first_unmet"])
        else:
            reasons.append("Normal code modification is blocked while Serena startup activation is incomplete.")
            reminders.append(policy["required_reminders"]["serena_first_unmet"])

    if context7_blockers and code_change:
        reasons.append("Protected changes require actual Context7 evidence.")
        reminders.append(policy["required_reminders"]["context7_missing"])

    if local_execution_request and local_shell_status == "BLOCKED":
        reasons.append("Local shell execution remains blocked while live codex resolution or PATH safety is contaminated.")
        reminders.append(policy["required_reminders"]["runtime_authority_conflict"])

    if runtime_overall == "BLOCKED":
        if activation_task and activation_bootstrap:
            warnings.append("Canonical runtime activation is allowed to repair a blocked authority surface in this process only.")
            reminders.append(policy["required_reminders"]["runtime_authority_conflict"])
        elif not reasons:
            warnings.append("Current runtime authority remains blocked and should be treated as diagnostic only.")
            reminders.append(policy["required_reminders"]["runtime_authority_conflict"])

    if canonical_status == "PASS" and client_surface_status != "PASS" and activation_task:
        warnings.append("Client-surface PATH contamination remains a warning while canonical activation work is in progress.")
    if any(token in normalized for token in ["refactor", "hardening", "entire", "전체"]) and not any(token in normalized for token in ["test", "verify", "검증"]):
        warnings.append("Large scope instruction does not include an explicit test plan.")
    if any(token in normalized for token in ["app", "cli", "ide", "runtime"]) and "surface" not in normalized:
        warnings.append("Instruction mixes app, CLI, IDE, or runtime surfaces without explicit boundaries.")

    status = collapse_status(["BLOCKED" if reasons else "", "WARN" if warnings else ""])
    if status == "PASS" and activation_task and activation_bootstrap and startup_status == "BLOCKED":
        status = "WARN"
    return {
        "status": status,
        "instruction": instruction,
        "activation_bootstrap": activation_bootstrap,
        "bootstrap_implementation_exception": activation_bootstrap,
        "reasons": reasons,
        "warnings": warnings,
        "required_reminders": sorted(set(reminders)),
        "evidence": {
            "changed_paths": changed_paths,
            "runtime_status": runtime_overall,
            "canonical_execution_status": canonical_status,
            "client_surface_status": client_surface_status,
            "local_shell_status": local_shell_status,
            "startup_status": startup_status,
            "context7_blockers": context7_blockers,
        },
        "recommended_next_action": (
            "Proceed only with scoped activation/bootstrap repair and keep authority results reported as WARN or BLOCKED."
            if activation_bootstrap and activation_task and not reasons
            else "Resolve blocked runtime or startup gates before normal code changes."
            if reasons
            else "Proceed with scoped work and keep unrelated dirty files untouched."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether a user instruction conflicts with runtime authority guardrails.")
    parser.add_argument("--instruction", default="")
    parser.add_argument("--instruction-file", default="")
    parser.add_argument("--output-file", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--activation-bootstrap", action="store_true")
    parser.add_argument("--bootstrap-implementation-exception", action="store_true")
    args = parser.parse_args()

    instruction = args.instruction
    if args.instruction_file:
        instruction = Path(args.instruction_file).expanduser().read_text(encoding="utf-8")
    report = evaluate_instruction(
        instruction,
        activation_bootstrap=bool(args.activation_bootstrap),
        bootstrap_implementation_exception=bool(args.bootstrap_implementation_exception),
    )
    if args.output_file:
        save_json(Path(args.output_file).expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
