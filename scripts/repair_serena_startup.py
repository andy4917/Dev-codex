#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from check_startup_workflow import evaluate_startup_workflow


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "reports" / "serena-startup-repair.json"


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def run(argv: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd) if cwd else None,
        )
    except OSError as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(exc), "argv": argv}
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "argv": argv,
    }


def cli_probe() -> dict[str, Any]:
    binary = shutil.which("serena") or ""
    if not binary:
        return {
            "binary": "",
            "available": False,
            "project_index_available": False,
            "project_create_available": False,
            "index_help": "",
            "create_help": "",
        }
    try:
        index_help = subprocess.run(
            ["serena", "project", "index", "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        create_help = subprocess.run(
            ["serena", "project", "create", "--help"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return {
            "binary": binary,
            "available": True,
            "project_index_available": False,
            "project_create_available": False,
            "index_help": "",
            "create_help": "",
        }
    return {
        "binary": binary,
        "available": True,
        "project_index_available": index_help.returncode == 0 and "Auto-creates project.yml" in str(index_help.stdout),
        "project_create_available": create_help.returncode == 0 and "Create a new Serena project configuration." in str(create_help.stdout),
        "index_help": str(index_help.stdout).strip(),
        "create_help": str(create_help.stdout).strip(),
    }


def inferred_serena_language(repo_root: Path) -> str:
    if (repo_root / "pyproject.toml").exists():
        return "python"
    if any(repo_root.rglob("*.py")):
        return "python"
    return ""


def serena_project_index_command(repo_root: Path) -> list[str]:
    command = ["serena", "project", "index", str(repo_root), "--name", repo_root.name]
    language = inferred_serena_language(repo_root)
    if language:
        command.extend(["--language", language])
    return command


def repair_serena(*, apply_serena: bool, repo_root: Path) -> dict[str, Any]:
    probe = cli_probe()
    startup_before = evaluate_startup_workflow(repo_root, mode="ssh-managed")
    project_yml = repo_root / ".serena" / "project.yml"

    actions_planned: list[str] = []
    actions_applied: list[str] = []
    warnings: list[str] = []

    if not probe["available"]:
        warnings.append("serena CLI is not available; repair remains report-only")
        status = "WARN"
        startup_after = startup_before
    elif not project_yml.exists() and probe["project_index_available"]:
        actions_planned.append(" ".join(serena_project_index_command(repo_root)))
        if apply_serena:
            result = run(serena_project_index_command(repo_root), cwd=repo_root)
            if result["ok"]:
                actions_applied.append("serena project index")
            else:
                warnings.append(str(result["stderr"]).strip() or "serena project index failed")
        startup_after = evaluate_startup_workflow(repo_root, mode="ssh-managed")
        status = "PASS" if project_yml.exists() else "WARN"
    else:
        startup_after = startup_before
        status = "WARN" if startup_before["status"] != "PASS" else "PASS"

    if startup_after.get("serena", {}).get("activation", {}).get("status") != "PASS":
        warnings.append("latest Serena MCP log still shows project activation as blocked")
    if not startup_after.get("serena", {}).get("runtime", {}).get("linux", {}).get("onboarding_performed", False):
        warnings.append("onboarding memory remains report-only until a deterministic CLI surface is confirmed")
    if startup_after.get("status") == "BLOCKED":
        status = "WARN" if actions_applied else "BLOCKED"

    return {
        "status": status,
        "apply_serena": apply_serena,
        "cli_probe": probe,
        "actions_planned": actions_planned,
        "actions_applied": actions_applied,
        "project_yml_path": str(project_yml),
        "project_yml_exists": project_yml.exists(),
        "startup_before": startup_before,
        "startup_after": startup_after,
        "warnings": warnings,
        "repair_boundary": {
            "arbitrary_serena_file_forging_allowed": False,
            "onboarding_auto_repair_allowed": False,
            "deterministic_metadata_repair_available": bool(probe["project_index_available"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Advise or run deterministic Serena startup repair.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--apply-serena", action="store_true")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = repair_serena(apply_serena=bool(args.apply_serena), repo_root=Path(args.repo_root).expanduser().resolve())
    if args.output_file:
        save_json(Path(args.output_file).expanduser().resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
