#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.windows_policy import windows_policy_surface_report


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_paths(authority: dict[str, Any], linux_codex_home: Path | None, windows_codex_home: Path | None) -> dict[str, Any]:
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    linux = runtime.get("linux", {})
    windows_state = authority.get("windows_app_state", {}) if isinstance(authority.get("windows_app_state"), dict) else {}

    linux_root = linux_codex_home.resolve() if linux_codex_home else None
    windows_root = windows_codex_home.resolve() if windows_codex_home else Path(str(windows_state.get("codex_home", ""))).expanduser().resolve()

    linux_agents = (linux_root / "AGENTS.md") if linux_root else Path(linux.get("agents", ""))
    linux_config = (linux_root / "config.toml") if linux_root else Path(linux.get("config", ""))
    linux_hooks = (linux_root / "hooks.json") if linux_root else Path(linux.get("hooks_config", ""))
    linux_user_override_config = (linux_root / "user-config.toml") if linux_root else Path(linux.get("user_override_config", ""))
    windows_policy_paths = {
        "agents": windows_root / "AGENTS.md",
        "config": windows_root / "config.toml",
        "hooks": windows_root / "hooks.json",
        "skills": windows_root / "skills" / "dev-workflow",
    }

    return {
        "linux_agents": linux_agents,
        "linux_config": linux_config,
        "linux_hooks": linux_hooks,
        "linux_user_override_config": linux_user_override_config,
        "windows_codex_home": windows_root,
        "windows_policy_paths": windows_policy_paths,
    }


def top_level_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted(child.name for child in path.iterdir() if not child.name.startswith("."))


def build_canonical_tree(repo_root: Path, authority: dict[str, Any], inventory_after: dict[str, Any]) -> dict[str, Any]:
    roots = authority.get("canonical_roots", {})
    management_root = Path(roots.get("management", repo_root))
    workflow_root = Path(roots.get("workflow", repo_root.parent / "Dev-Workflow"))
    product_root = Path(roots.get("product", repo_root.parent / "Dev-Product"))
    return {
        "canonical_roots": roots,
        "management": {
            "root": str(management_root),
            "exists": management_root.exists(),
            "top_level_entries": top_level_entries(management_root),
        },
        "workflow": {
            "root": str(workflow_root),
            "exists": workflow_root.exists(),
            "top_level_entries": top_level_entries(workflow_root),
        },
        "product": {
            "root": str(product_root),
            "exists": product_root.exists(),
            "top_level_entries": top_level_entries(product_root),
        },
        "inventory_after_report": inventory_after,
    }


def explain_survivor(path: Path, authority: dict[str, Any], runtime: dict[str, Any], kind: str) -> str:
    product_root = Path(authority.get("canonical_roots", {}).get("product", ROOT))
    linux_path = runtime[f"linux_{kind}"]
    windows_path = runtime["windows_policy_paths"][kind]

    if path.resolve() == linux_path.resolve():
        return f"Allowed because it is the generated Linux runtime {kind} target from workspace authority."
    if path.resolve() == windows_path.resolve():
        return f"Observed because it is a Windows policy-surface {kind} file that should be removed, not a canonical authority target."
    try:
        path.resolve().relative_to(product_root.resolve())
        return "Allowed because project-specific rules are allowed only inside Dev-Product/<project>."
    except Exception:
        return "Observed in the audit report; authority-based justification was not recognized automatically."


def build_survivor_entries(paths: list[str], authority: dict[str, Any], runtime: dict[str, Any], kind: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for raw in paths:
        path = Path(raw)
        entries.append(
            {
                "path": str(path),
                "justification": explain_survivor(path, authority, runtime, kind),
            }
        )
    return entries


def cleanup_counts(cleanup: dict[str, Any]) -> dict[str, int]:
    return {
        "moved_to_management": len(cleanup.get("moved_to_management", [])),
        "moved_to_workflow": len(cleanup.get("moved_to_workflow", [])),
        "quarantined": len(cleanup.get("quarantined", [])),
        "deleted": len(cleanup.get("deleted", [])),
    }


def parse_markers(config_path: Path) -> list[str]:
    if not config_path.exists():
        return []
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    markers = payload.get("project_root_markers", [])
    return [str(item) for item in markers]


def strip_generated_header(text: str) -> str:
    lines = text.splitlines()
    while lines and lines[0].strip() in {"GENERATED - DO NOT EDIT", "# GENERATED - DO NOT EDIT"}:
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_git_root_marker_proof(authority: dict[str, Any], runtime: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    expected_markers = [
        str(item)
        for item in authority.get("generation_targets", {}).get("global_config", {}).get("project_root_markers", [])
    ]
    linux_markers = parse_markers(runtime["linux_config"])
    status = (
        "PASS"
        if expected_markers == [".git"]
        and linux_markers == expected_markers
        and audit.get("project_root_markers_git_only") is True
        else "FAIL"
    )
    return {
        "expected_markers": expected_markers,
        "linux_config_path": str(runtime["linux_config"]),
        "linux_config_markers": linux_markers,
        "audit_report_value": audit.get("project_root_markers_git_only"),
        "status": status,
    }


def build_windows_policy_surface_proof(authority: dict[str, Any], runtime: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    observed = dict(runtime["windows_policy_paths"])
    shared_paths = {
        "observed_windows_policy_config": Path(observed["config"]),
        "observed_windows_policy_agents": Path(observed["agents"]),
        "observed_windows_policy_hooks": Path(observed["hooks"]),
        "observed_windows_policy_skills": Path(observed["skills"]),
    }
    expected_linux_hooks = read_text(runtime["linux_hooks"]) if runtime["linux_hooks"].exists() else None
    classifier = windows_policy_surface_report(shared_paths, authority, expected_linux_hooks=expected_linux_hooks)
    findings = [dict(item) for item in classifier.get("findings", []) if isinstance(item, dict)]
    present_paths = [str(path) for path in observed.values() if path.exists()]
    audit_status = str(audit.get("windows_policy_surface_status", "")).strip().upper()
    status = str(classifier.get("status", "PASS"))
    if status == "PASS" and audit_status in {"PASS", "WARN", "BLOCKED"}:
        status = audit_status
    return {
        "windows_codex_home": str(runtime["windows_codex_home"]),
        "observed_paths": {name: str(path) for name, path in observed.items()},
        "present_paths": present_paths,
        "audit_report_value": audit.get("windows_policy_surface_status"),
        "audit_windows_app_evidence_status": audit.get("windows_app_evidence_status"),
        "findings": findings,
        "unknown_windows_policy_files_blocking": classifier.get("unknown_blocking", []),
        "manual_remediation_candidates": classifier.get("manual_remediation_candidates", []),
        "remove_now_candidates": classifier.get("remove_now_candidates", []),
        "known_generated_cleanup_candidates": classifier.get("known_generated_cleanup_candidates", []),
        "source_of_truth_proof": audit.get("linux_source_of_truth_proof", {}),
        "status": status,
    }


def build_hardcoding_audit(audit: dict[str, Any]) -> dict[str, Any]:
    violations = audit.get("violations", {})
    status = (
        "PASS"
        if not violations.get("unexpected_agents")
        and not violations.get("unexpected_configs")
        and not violations.get("unexpected_contract_dirs")
        and not audit.get("project_rule_leaks")
        and not audit.get("old_path_refs_outside_quarantine")
        else "FAIL"
    )
    return {
        "violations": violations,
        "project_rule_leaks": audit.get("project_rule_leaks", []),
        "old_path_refs_outside_quarantine": audit.get("old_path_refs_outside_quarantine", []),
        "status": status,
    }


def command_status(exit_code: int) -> str:
    if exit_code == 0:
        return "PASS"
    if exit_code == 2:
        return "BLOCKED"
    return "FAIL"


def collapse_statuses(statuses: list[str]) -> str:
    normalized = [str(status).strip().upper() for status in statuses if str(status).strip()]
    if any(status in {"FAIL", "SECURITY_INCIDENT"} for status in normalized):
        return "FAIL"
    if any(status == "BLOCKED" for status in normalized):
        return "BLOCKED"
    if normalized:
        return "PASS"
    return "FAIL"


def status_exit_code(status: str) -> int:
    normalized = str(status).strip().upper()
    if normalized in {"PASS", "WAIVED"}:
        return 0
    if normalized == "BLOCKED":
        return 2
    return 1


def run_command(name: str, argv: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return {
        "name": name,
        "command": " ".join(shlex.quote(part) for part in argv),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": command_status(completed.returncode),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the required verification chain and assemble migration evidence in one report."
    )
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--output-file", default="")
    parser.add_argument("--linux-codex-home", default="")
    parser.add_argument("--windows-codex-home", default="")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    output_path = Path(args.output_file).expanduser().resolve() if args.output_file else repo_root / "reports" / "migration-verification.json"
    linux_codex_home = Path(args.linux_codex_home).expanduser().resolve() if args.linux_codex_home else None
    windows_codex_home = Path(args.windows_codex_home).expanduser().resolve() if args.windows_codex_home else None

    authority_path = repo_root / "contracts" / "workspace_authority.json"
    manifest_path = repo_root / "migration_manifest.json"
    cleanup_path = repo_root / "reports" / "cleanup_report.json"
    inventory_after_path = repo_root / "reports" / "inventory.after.json"
    scorecard_path = repo_root / "reports" / "user-scorecard.json"
    audit_path = repo_root / "reports" / "audit.final.json"

    delivery_gate_result = run_command(
        "delivery_gate_verify",
        [
            sys.executable,
            str(repo_root / "scripts" / "delivery_gate.py"),
            "--mode",
            "verify",
            "--workspace-root",
            str(repo_root),
        ],
        repo_root,
    )
    summary_result = run_command(
        "export_user_score_summary",
        [
            sys.executable,
            str(repo_root / "scripts" / "export_user_score_summary.py"),
        ],
        repo_root,
    )
    audit_result = run_command(
        "audit_workspace_write_report",
        [
            sys.executable,
            str(repo_root / "scripts" / "audit_workspace.py"),
            "--write-report",
        ],
        repo_root,
    )

    authority = load_json(authority_path)
    if isinstance(authority, dict):
        authority["_authority_path"] = str(authority_path)
    manifest = load_json(manifest_path)
    cleanup = load_json(cleanup_path)
    inventory_after = load_json(inventory_after_path)
    scorecard = load_json(scorecard_path)
    audit = load_json(audit_path)
    runtime = runtime_paths(authority, linux_codex_home, windows_codex_home)

    hardcoding_audit = build_hardcoding_audit(audit)
    git_root_marker_proof = build_git_root_marker_proof(authority, runtime, audit)
    windows_policy_surface_proof = build_windows_policy_surface_proof(authority, runtime, audit)
    report_status = collapse_statuses(
        [
            scorecard.get("gate_status") or delivery_gate_result["status"],
            command_status(summary_result["exit_code"]),
            audit.get("status") or audit_result["status"],
            hardcoding_audit["status"],
            git_root_marker_proof["status"],
            windows_policy_surface_proof["status"],
        ]
    )

    report = {
        "generated_at": utc_timestamp(),
        "repo_root": str(repo_root),
        "authority_path": str(authority_path),
        "status": report_status,
        "command_results": {
            "delivery_gate_verify": {
                **delivery_gate_result,
                "report_path": str(scorecard_path),
                "gate_status": scorecard.get("gate_status", ""),
                "final_decision": scorecard.get("final_decision", ""),
            },
            "export_user_score_summary": {
                **summary_result,
            },
            "audit_workspace_write_report": {
                **audit_result,
                "report_path": str(audit_path),
                "audit_status": audit.get("status", ""),
            },
        },
        "migration_evidence": {
            "before_after_mapping": manifest.get("mappings", []),
            "canonical_tree": build_canonical_tree(repo_root, authority, inventory_after),
            "surviving_agents_files": build_survivor_entries(audit.get("agents_files", []), authority, runtime, "agents"),
            "surviving_config_files": build_survivor_entries(audit.get("config_files", []), authority, runtime, "config"),
            "cleanup_summary": {
                **cleanup,
                "counts": cleanup_counts(cleanup),
            },
            "git_root_marker_proof": git_root_marker_proof,
            "windows_policy_surface_proof": windows_policy_surface_proof,
            "startup_workflow_proof": audit.get("startup_workflow_check", {}),
            "global_runtime_proof": audit.get("global_runtime_surface", {}),
            "config_provenance_proof": audit.get("config_provenance", {}),
            "toolchain_surface_proof": audit.get("toolchain_surface", {}),
            "hook_readiness_proof": audit.get("hook_readiness", {}),
            "artifact_hygiene_proof": audit.get("artifact_hygiene", {}),
            "score_layer_proof": audit.get("score_layer", {}),
            "windows_app_ssh_readiness_proof": audit.get("windows_app_ssh_readiness", {}),
            "linux_native_codex_cli_proof": audit.get("linux_native_codex_cli", {}),
            "git_surface_proof": audit.get("git_surface_drift", {}),
            "instruction_guard_proof": audit.get("instruction_guard_policy", {}),
            "context7_proof": audit.get("startup_workflow_check", {}).get("context7", {}),
            "hardcoding_legacy_duplicate_audit": hardcoding_audit,
        },
    }
    save_json(output_path, report)

    print(report["status"])
    print(f"wrote {output_path}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
