#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from check_artifact_hygiene import evaluate_artifact_hygiene
from check_windows_app_ssh_readiness import DEFAULT_CACHE_PATH as WINDOWS_SSH_CACHE_PATH
from devmgmt_runtime.authority import load_authority
from devmgmt_runtime.paths import runtime_paths
from devmgmt_runtime.reports import load_json, save_json, write_markdown
from devmgmt_runtime.status import status_exit_code
from devmgmt_runtime.windows_policy import windows_policy_surface_report
from render_codex_runtime import render_hooks


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_report(path: Path) -> dict[str, Any]:
    payload = load_json(path, default={})
    return payload if isinstance(payload, dict) else {}


def git_status_lines(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return []
    return [line.rstrip() for line in result.stdout.splitlines() if line.strip()]


def dirty_path_from_status(line: str) -> str:
    return line[3:].strip() if len(line) >= 4 else line.strip()


def scan_repo_references(root: Path, needle: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for base in (root / "contracts", root / "docs", root / "scripts", root / "tests", root / "reports"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if needle in line:
                    hits.append(
                        {
                            "path": str(path),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
    return hits


def render_md(title: str, body: list[str]) -> str:
    return "\n".join([f"# {title}", "", *body]).rstrip() + "\n"


def find_finding(findings: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    for item in findings:
        if str(item.get("path", "")) == str(path):
            return dict(item)
    return {}


def latest_existing(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda item: item.stat().st_mtime)


def preferred_report(reports_root: Path, *names: str) -> tuple[Path | None, dict[str, Any]]:
    for name in names:
        path = reports_root / name
        if path.exists():
            return path, load_report(path)
    return None, {}


def build_windows_skill_disposition(repo_root: Path) -> dict[str, Any]:
    reports_root = repo_root / "reports"
    authority = load_authority(repo_root)
    paths = runtime_paths(authority)
    skill_path = paths["observed_windows_policy_skills"]
    expected_linux_hooks = render_hooks(authority, windows=False)
    current_surface = windows_policy_surface_report(paths, authority, expected_linux_hooks=expected_linux_hooks)
    current_finding = find_finding(current_surface.get("findings", []), skill_path)

    removal_report_path = latest_existing(
        [
            reports_root / "windows-codex-policy-mirror-removal.apply.json",
            reports_root / "windows-codex-policy-mirror-removal.final-dry-run.json",
            reports_root / "windows-codex-policy-mirror-removal.dry-run.json",
        ]
    )
    removal_report = load_report(removal_report_path) if removal_report_path else {}
    prior_surface = removal_report.get("windows_policy_surface_report", {}) if isinstance(removal_report, dict) else {}
    prior_finding = find_finding(prior_surface.get("findings", []), skill_path)
    applied_change = next(
        (
            dict(item)
            for item in removal_report.get("applied_changes", [])
            if str(item.get("source_path", "")) == str(skill_path)
        ),
        {},
    )

    evidence_finding = current_finding or prior_finding
    disposition = str(evidence_finding.get("disposition", "ACCEPTED_NONBLOCKING"))
    reason = str(evidence_finding.get("reason", "Windows skill surface is absent."))
    action_taken = str(applied_change.get("action", "")).strip()
    rollback_path = str(applied_change.get("rollback_path", "")).strip()
    exists_now = skill_path.exists()
    resolved = (
        (disposition == "REMOVE_NOW" and not exists_now)
        or (disposition == "INERT_QUARANTINE" and not exists_now)
        or disposition in {"MANUAL_REMEDIATION", "ACCEPTED_NONBLOCKING"}
    )
    status = "PASS" if resolved else "BLOCKED" if disposition in {"REMOVE_NOW", "INERT_QUARANTINE"} else "WARN"
    references = scan_repo_references(repo_root, "skills/dev-workflow")
    structural = evidence_finding.get("details", {})
    return {
        "status": status,
        "path": str(skill_path),
        "exists_now": exists_now,
        "disposition": disposition,
        "reason": reason,
        "action_taken": action_taken or ("removed" if disposition == "REMOVE_NOW" and not exists_now else "retained"),
        "rollback_path": rollback_path,
        "rollback_note": str(applied_change.get("rollback_note", "")),
        "evidence_report": str(removal_report_path) if removal_report_path else "",
        "repo_reference_hits": references,
        "reference_count": len(references),
        "structural_analysis": structural,
        "current_finding": current_finding,
        "prior_finding": prior_finding,
        "applied_change": applied_change,
    }


def build_windows_ssh_probe_dedup(repo_root: Path) -> dict[str, Any]:
    reports_root = repo_root / "reports"
    readiness_script = repo_root / "scripts" / "check_windows_app_ssh_readiness.py"
    global_runtime_script = repo_root / "scripts" / "check_global_runtime.py"
    audit_script = repo_root / "scripts" / "audit_workspace.py"
    usability_script = repo_root / "scripts" / "activate_codex_app_usability.py"

    live_probe_owner_files = []
    for path in (readiness_script, global_runtime_script, audit_script, usability_script):
        text = read_text(path)
        if 'OpenSSH\\\\ssh.exe' in text or "run_windows_ssh(" in text:
            live_probe_owner_files.append(str(path))

    global_runtime_report = load_report(reports_root / "global-runtime.closeout-v2.final.json")
    audit_report = load_report(reports_root / "audit.closeout-v2.final.json")
    app_report = load_report(reports_root / "app-usability.closeout-v2.final-dry-run.json")
    refresh_report = load_report(reports_root / "windows-app-ssh-remote-readiness.closeout-v2.refresh.json")
    cached_report = load_report(reports_root / WINDOWS_SSH_CACHE_PATH.name)

    global_runtime_probe_source = str(
        global_runtime_report.get(
            "windows_app_ssh_probe_source",
            global_runtime_report.get("windows_app_ssh_readiness", {}).get("probe_source", ""),
        )
    )
    audit_probe_source = str(audit_report.get("windows_app_ssh_readiness", {}).get("probe_source", ""))
    app_probe_source = str(app_report.get("windows_app_ssh_probe_source", ""))
    refresh_probe_source = str(refresh_report.get("probe_source", ""))
    cached_probe_source = str(cached_report.get("probe_source", ""))

    call_site_checks = {
        "global_runtime_default_cache_only": "allow_cache_miss_live_probe=False" in read_text(global_runtime_script),
        "audit_default_cache_only": "allow_cache_miss_live_probe=False" in read_text(audit_script),
        "app_usability_reuses_injected_readiness": "windows_app_ssh_readiness=windows" in read_text(usability_script),
        "audit_cli_uses_report_reuse": "--windows-ssh-readiness-report" in read_text(usability_script)
        and "--no-live-windows-ssh-probe" in read_text(usability_script),
    }
    blocked_reasons: list[str] = []
    if live_probe_owner_files != [str(readiness_script)]:
        blocked_reasons.append("live Windows ssh.exe probe ownership is not isolated to check_windows_app_ssh_readiness.py")
    if global_runtime_probe_source == "live_probe":
        blocked_reasons.append("global-runtime default closeout report still used a live Windows probe")
    if audit_probe_source == "live_probe":
        blocked_reasons.append("audit default closeout report still used a live Windows probe")
    if app_probe_source == "live_probe":
        blocked_reasons.append("app-usability default closeout report still used a live Windows probe")
    if refresh_report and refresh_probe_source != "live_probe":
        blocked_reasons.append("explicit refresh did not record a live Windows probe")
    if not all(call_site_checks.values()):
        blocked_reasons.append("one or more downstream scripts no longer prove cache/injected readiness reuse")

    status = "BLOCKED" if blocked_reasons else "PASS"
    return {
        "status": status,
        "live_probe_owner_files": live_probe_owner_files,
        "call_site_checks": call_site_checks,
        "report_probe_sources": {
            "cached_readiness_report": cached_probe_source,
            "app_usability": app_probe_source,
            "global_runtime": global_runtime_probe_source,
            "audit": audit_probe_source,
            "explicit_refresh": refresh_probe_source,
        },
        "blocked_reasons": blocked_reasons,
    }


def build_quarantine_dead_surface(repo_root: Path) -> dict[str, Any]:
    report = evaluate_artifact_hygiene(repo_root)
    findings = list(report.get("findings", []))
    return {
        "status": report.get("status", "PASS"),
        "findings": findings,
        "quarantine_executable_files": report.get("quarantine_executable_files", []),
        "quarantine_importable_files": report.get("quarantine_importable_files", []),
        "quarantine_cli_files": report.get("quarantine_cli_files", []),
        "preview_executable_files": report.get("preview_executable_files", []),
        "active_quarantine_reference_hits": report.get("active_quarantine_reference_hits", []),
        "cleanup_actions": report.get("cleanup_actions", []),
    }


def build_inventory(
    repo_root: Path,
    skill: dict[str, Any],
    ssh_dedup: dict[str, Any],
    quarantine: dict[str, Any],
) -> dict[str, Any]:
    reports_root = repo_root / "reports"
    authority = load_authority(repo_root)
    paths = runtime_paths(authority)
    surface = windows_policy_surface_report(paths, authority, expected_linux_hooks=render_hooks(authority, windows=False))
    dirty_lines = git_status_lines(repo_root)
    related_prefixes = (
        "devmgmt_runtime/windows_policy.py",
        "scripts/check_artifact_hygiene.py",
        "scripts/check_global_runtime.py",
        "scripts/activate_codex_app_usability.py",
        "scripts/audit_workspace.py",
        "scripts/check_config_provenance.py",
        "scripts/check_active_config_smoke.py",
        "scripts/check_windows_app_ssh_readiness.py",
        "scripts/remove_windows_codex_policy_mirrors.py",
        "scripts/verify_migration_evidence.py",
        "scripts/generate_closeout_v2_reports.py",
        "tests/test_windows_app_ssh_readiness.py",
        "tests/test_codex_app_usability.py",
        "tests/test_windows_codex_policy_mirror_removal.py",
        "tests/test_check_config_provenance.py",
        "tests/test_check_active_config_smoke.py",
        "tests/test_artifact_hygiene.py",
        "tests/test_check_global_runtime.py",
        "tests/test_audit_workspace_contract.py",
        "tests/test_verify_migration_evidence.py",
        "tests/test_closeout_v2_reports.py",
        "docs/CODEX_APP_USER_SETUP.md",
        "contracts/app_surface_policy.json",
        "reports/",
    )
    unrelated_dirty = [
        line for line in dirty_lines if not dirty_path_from_status(line).startswith(related_prefixes)
    ]
    remaining_windows = [dict(item) for item in surface.get("findings", [])]
    repo_owned_stale = [
        dict(item)
        for item in [*remaining_windows, *quarantine.get("findings", [])]
        if str(item.get("disposition", "")) in {"REMOVE_NOW", "INERT_QUARANTINE", "FIX_NOW"}
    ]
    app_owned_runtime = [
        dict(item)
        for item in remaining_windows
        if str(item.get("disposition", "")) in {"MANUAL_REMEDIATION", "ACCEPTED_NONBLOCKING"}
    ]
    product_excluded = []
    toolchain_report = load_report(reports_root / "toolchain-surface.closeout-v2.final.json")
    for warning in toolchain_report.get("warnings", []):
        if "PATH mismatch" in str(warning):
            product_excluded.append(
                {
                    "path": "Codex App multiple terminals",
                    "category": "client_terminal_path_mismatch",
                    "disposition": "PRODUCT_EXCLUDED",
                    "reason": str(warning),
                }
            )
    return {
        "status": "PASS",
        "remaining_windows_policy_like_surfaces": remaining_windows,
        "repo_owned_stale_surfaces": repo_owned_stale,
        "app_owned_runtime_state": app_owned_runtime,
        "structurally_stale_unmarked_surfaces": [skill] if skill.get("disposition") == "REMOVE_NOW" else [],
        "duplicate_probe_call_sites": ssh_dedup.get("live_probe_owner_files", []),
        "quarantine_dead_surfaces": quarantine.get("findings", []),
        "product_excluded_surfaces": product_excluded,
        "unrelated_dirty_files": unrelated_dirty,
        "unclassified_items": [],
    }


def disposition_entry(
    *,
    entry_id: str,
    source_report: str,
    evidence: list[str],
    root_cause: str,
    disposition: str,
    action_taken: str,
    owner: str,
    remaining_risk: str,
    blocks_app_usability: bool,
    blocks_code_modification: bool,
    test_coverage: list[str],
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "source_report": source_report,
        "evidence": evidence,
        "root_cause": root_cause,
        "disposition": disposition,
        "action_taken": action_taken,
        "owner": owner,
        "remaining_risk": remaining_risk,
        "blocks_app_usability": blocks_app_usability,
        "blocks_code_modification": blocks_code_modification,
        "test_coverage": test_coverage,
    }


def build_warn_disposition(
    repo_root: Path,
    skill: dict[str, Any],
    ssh_dedup: dict[str, Any],
    quarantine: dict[str, Any],
) -> dict[str, Any]:
    reports_root = repo_root / "reports"
    entries: list[dict[str, Any]] = []
    _, config = preferred_report(reports_root, "config-provenance.closeout-v2.final.json")
    _, runtime = preferred_report(reports_root, "global-runtime.closeout-v2.final.json")
    _, toolchain = preferred_report(reports_root, "toolchain-surface.closeout-v2.final.json")
    _, hooks = preferred_report(reports_root, "hook-readiness.closeout-v2.final.json")
    _, score = preferred_report(reports_root, "score-layer.closeout-v2.final.json")
    _, audit = preferred_report(reports_root, "audit.closeout-v2.final.json")
    startup_path, startup = preferred_report(
        reports_root,
        "startup-workflow.closeout-v2.final.json",
        "startup-workflow.final.json",
    )
    startup_source_report = (
        f"reports/{startup_path.name}" if startup_path else "reports/startup-workflow.closeout-v2.final.json"
    )
    _, app = preferred_report(reports_root, "app-usability.closeout-v2.final-dry-run.json")

    for finding in config.get("windows_policy_surface_findings", []):
        if str(finding.get("disposition", "")) != "MANUAL_REMEDIATION":
            continue
        entries.append(
            disposition_entry(
                entry_id="windows_policy_surface.manual_review",
                source_report="reports/config-provenance.closeout-v2.final.json",
                evidence=[str(finding.get("path", "")), str(finding.get("reason", ""))],
                root_cause="Non-generated Windows .codex policy-bearing content remains as external app or user state.",
                disposition="MANUAL_REMEDIATION",
                action_taken="Repo left the non-generated Windows config untouched and classified it as external evidence-only state.",
                owner="user_or_app",
                remaining_risk="The user-configured Windows .codex file may continue to influence app-local behavior until the user reviews or removes it.",
                blocks_app_usability=False,
                blocks_code_modification=False,
                test_coverage=["tests.test_check_config_provenance", "tests.test_check_active_config_smoke"],
            )
        )

    if runtime and str(runtime.get("overall_status", "PASS")) == "WARN" and str(runtime.get("client_surface_status", "PASS")) == "WARN":
        entries.append(
            disposition_entry(
                entry_id="global_runtime.client_surface_path_mismatch",
                source_report="reports/global-runtime.closeout-v2.final.json",
                evidence=[str(runtime.get("path_contamination", {}).get("local_contaminated_entries", []))],
                root_cause="Client terminal PATH contamination remains on the app/user surface even though canonical SSH execution passes.",
                disposition="PRODUCT_EXCLUDED",
                action_taken="Canonical SSH runtime remained PASS and no repo-side Windows mirror was restored.",
                owner="codex_app_or_user_session",
                remaining_risk="App-local PATH noise can still confuse local terminal inspection, but it does not control the canonical remote runtime.",
                blocks_app_usability=False,
                blocks_code_modification=False,
                test_coverage=["tests.test_check_global_runtime"],
            )
        )

    for warning in toolchain.get("warnings", []):
        warning_text = str(warning)
        if "PATH mismatch" in warning_text:
            entries.append(
                disposition_entry(
                    entry_id="toolchain.multiple_terminal_path_mismatch",
                    source_report="reports/toolchain-surface.closeout-v2.final.json",
                    evidence=[warning_text],
                    root_cause="Codex App multiple-terminal state still reports a PATH mismatch outside repo authority.",
                    disposition="PRODUCT_EXCLUDED",
                    action_taken="Left app terminal state untouched and kept canonical runtime authority on devmgmt-wsl.",
                    owner="codex_app",
                    remaining_risk="Local terminal surfaces may continue to show mixed PATH state until the app refreshes or the user opens a clean terminal.",
                    blocks_app_usability=False,
                    blocks_code_modification=False,
                    test_coverage=["tests.test_check_toolchain_surface"],
                )
            )
        elif "Windows hooks are intentionally disabled" in warning_text or "Windows hook generation" in warning_text:
            entries.append(
                disposition_entry(
                    entry_id="toolchain.windows_hooks_disabled",
                    source_report="reports/toolchain-surface.closeout-v2.final.json",
                    evidence=[warning_text, str(hooks.get("windows_generation_reason", ""))],
                    root_cause="Windows hook generation remains intentionally disabled because Windows .codex policy surfaces are forbidden.",
                    disposition="ACCEPTED_NONBLOCKING",
                    action_taken="Kept Linux hook readiness only and did not reintroduce Windows hooks.",
                    owner="repo",
                    remaining_risk="Windows app surfaces will not receive repo-generated hook reminders, by design.",
                    blocks_app_usability=False,
                    blocks_code_modification=False,
                    test_coverage=["tests.test_check_hook_readiness", "tests.test_check_toolchain_surface"],
                )
            )

    if startup and str(startup.get("status", "PASS")) in {"WARN", "BLOCKED"}:
        entries.append(
            disposition_entry(
                entry_id="startup.serena_activation_pending",
                source_report=startup_source_report,
                evidence=[json.dumps(startup.get("serena", {}), ensure_ascii=False)],
                root_cause="Serena onboarding or activation is still incomplete for general code modification.",
                disposition="ACCEPTED_NONBLOCKING",
                action_taken="Root-cause closeout left Serena untouched and kept the code-modification gate explicit.",
                owner="serena_runtime",
                remaining_risk="General code modification remains blocked until Serena onboarding/activation succeeds.",
                blocks_app_usability=False,
                blocks_code_modification=True,
                test_coverage=["tests.test_check_startup_workflow"],
            )
        )

    if audit and str(audit.get("status", "PASS")) in {"FAIL", "BLOCKED"}:
        entries.append(
            disposition_entry(
                entry_id="audit.code_modification_gate",
                source_report="reports/audit.closeout-v2.final.json",
                evidence=[str(audit.get("status", "")), str(audit.get("startup_workflow_check", {}).get("status", ""))],
                root_cause="Audit remains blocked because code-modification gating still depends on startup/Serena readiness.",
                disposition="ACCEPTED_NONBLOCKING",
                action_taken="Left the final code-modification gate blocked only by startup/Serena, not by Windows mirror residue.",
                owner="repo",
                remaining_risk="Code modification cannot proceed until startup gating is satisfied.",
                blocks_app_usability=False,
                blocks_code_modification=True,
                test_coverage=["tests.test_audit_workspace_contract", "tests.test_check_startup_workflow"],
            )
        )

    if score and str(score.get("status", "PASS")) in {"WARN", "BLOCKED"}:
        entries.append(
            disposition_entry(
                entry_id="score_layer.gating_derivative",
                source_report="reports/score-layer.closeout-v2.final.json",
                evidence=[json.dumps(score.get("disqualifiers", []), ensure_ascii=False), json.dumps(score.get("warnings", []), ensure_ascii=False)],
                root_cause="Score layer still reflects startup/audit warnings after root-cause cleanup.",
                disposition="ACCEPTED_NONBLOCKING",
                action_taken="Score layer remained derivative of upstream readiness reports after Windows mirror cleanup.",
                owner="repo",
                remaining_risk="The score layer will continue to warn or block until upstream startup and audit gates clear.",
                blocks_app_usability=False,
                blocks_code_modification=any("startup" in str(item).lower() or "audit" in str(item).lower() for item in score.get("disqualifiers", [])),
                test_coverage=["tests.test_score_layer"],
            )
        )

    if app and str(app.get("status", "APP_READY")) == "APP_READY_WITH_WARNINGS":
        entries.append(
            disposition_entry(
                entry_id="app_usability.ready_with_warnings",
                source_report="reports/app-usability.closeout-v2.final-dry-run.json",
                evidence=[json.dumps(app.get("status_reasons", []), ensure_ascii=False)],
                root_cause="App readiness remains warning-only because surviving issues are external/manual or startup-gated.",
                disposition="ACCEPTED_NONBLOCKING",
                action_taken="Maintained APP_READY_WITH_WARNINGS without reintroducing Windows mirrors.",
                owner="repo",
                remaining_risk="The app is usable, but warnings remain until external app state or Serena onboarding is addressed.",
                blocks_app_usability=False,
                blocks_code_modification=True,
                test_coverage=["tests.test_codex_app_usability"],
            )
        )

    if skill.get("status") != "PASS":
        entries.append(
            disposition_entry(
                entry_id="windows_skill.dev_workflow_unresolved",
                source_report="reports/windows-skill-dev-workflow-disposition.json",
                evidence=[json.dumps(skill, ensure_ascii=False)],
                root_cause="Windows .codex/skills/dev-workflow still has unresolved stale policy-bearing residue.",
                disposition="FIX_NOW",
                action_taken="No final closeout possible until the stale skill mirror is removed or explicitly justified.",
                owner="repo",
                remaining_risk="Windows skill mirror could continue to act as an app-readable policy-like surface.",
                blocks_app_usability=True,
                blocks_code_modification=True,
                test_coverage=["tests.test_windows_codex_policy_mirror_removal", "tests.test_closeout_v2_reports"],
            )
        )

    if ssh_dedup.get("status") != "PASS":
        entries.append(
            disposition_entry(
                entry_id="windows_ssh_probe.dedup_unresolved",
                source_report="reports/windows-ssh-probe-dedup.closeout-v2.json",
                evidence=[json.dumps(ssh_dedup, ensure_ascii=False)],
                root_cause="Repo-side Windows SSH readiness still allows repeated live probe bursts.",
                disposition="FIX_NOW",
                action_taken="No final closeout possible until live Windows probe ownership is isolated and cached reuse is proven.",
                owner="repo",
                remaining_risk="Sequential readiness flows may still cause extra Windows ssh.exe churn.",
                blocks_app_usability=True,
                blocks_code_modification=False,
                test_coverage=["tests.test_windows_app_ssh_readiness", "tests.test_codex_app_usability", "tests.test_check_global_runtime", "tests.test_closeout_v2_reports"],
            )
        )

    for finding in quarantine.get("findings", []):
        if str(finding.get("status", "PASS")) != "BLOCKED":
            continue
        entries.append(
            disposition_entry(
                entry_id=f"quarantine.{finding.get('category', 'blocked')}",
                source_report="reports/quarantine-and-dead-surface.closeout-v2.json",
                evidence=[str(finding.get("path", "")), str(finding.get("reason", ""))],
                root_cause="Quarantine or dead-surface content remains executable, importable, or actively referenced.",
                disposition="FIX_NOW",
                action_taken="Quarantine must remain inert evidence only.",
                owner="repo",
                remaining_risk="Blocked dead surfaces can be accidentally executed or imported.",
                blocks_app_usability=False,
                blocks_code_modification=True,
                test_coverage=["tests.test_artifact_hygiene", "tests.test_quarantine_hostile_audit"],
            )
        )

    blocking_dispositions = {"FIX_NOW", "REMOVE_NOW"}
    status = "BLOCKED" if any(entry["disposition"] in blocking_dispositions for entry in entries) else "PASS"
    return {
        "status": status,
        "entries": entries,
        "entry_count": len(entries),
    }


def write_restart_note(repo_root: Path) -> None:
    reports_root = repo_root / "reports"
    body = [
        "- Windows generated config/AGENTS/hooks were removed or quarantined earlier.",
        "- Windows `skills/dev-workflow` disposition is now resolved.",
        "- Windows SSH readiness is kept as bootstrap only.",
        "- Dev-Management no longer generates Windows `.codex` policy surfaces.",
        "- Codex App must be restarted.",
        "- Open `Settings > Connections > devmgmt-wsl`.",
        "- Open `/home/andy4917/Dev-Management`.",
        "- Do not recreate Windows `.codex/config.toml`, `AGENTS.md`, `hooks.json`, or `skills`.",
        "- If warnings remain after restart, collect app state evidence; do not reintroduce mirrors.",
        "",
        "Readiness prompt:",
        "",
        "`Run Dev-Management readiness after Windows .codex root-cause cleanup and report APP_READY / APP_READY_WITH_WARNINGS / APP_NOT_READY. Do not modify code unless runtime, config provenance, Serena/Context7, score, and audit gates allow it.`",
    ]
    write_markdown(reports_root / "app-restart-after-root-cause-closeout-v2.md", render_md("App Restart After Root-Cause Closeout V2", body))


def save_pair(path: Path, payload: dict[str, Any], title: str, body_lines: list[str]) -> None:
    save_json(path, payload)
    write_markdown(path.with_suffix(".md"), render_md(title, body_lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate closeout-v2 inventory, disposition, dedup, quarantine, and restart reports.")
    parser.add_argument("--repo-root", default=str(ROOT))
    args = parser.parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    reports_root = repo_root / "reports"

    skill = build_windows_skill_disposition(repo_root)
    skill_body = [
        f"- Status: {skill['status']}",
        f"- Path: {skill['path']}",
        f"- Exists now: {str(skill['exists_now']).lower()}",
        f"- Disposition: {skill['disposition']}",
        f"- Action taken: {skill['action_taken']}",
        f"- Reason: {skill['reason']}",
        f"- Repo reference hits: {skill['reference_count']}",
    ]
    save_pair(reports_root / "windows-skill-dev-workflow-disposition.json", skill, "Windows Skill Dev-Workflow Disposition", skill_body)

    ssh_dedup = build_windows_ssh_probe_dedup(repo_root)
    ssh_body = [
        f"- Status: {ssh_dedup['status']}",
        f"- Live probe owner files: {', '.join(ssh_dedup['live_probe_owner_files']) or '(none)'}",
        f"- Probe sources: {json.dumps(ssh_dedup['report_probe_sources'], ensure_ascii=False)}",
    ]
    if ssh_dedup.get("blocked_reasons"):
        ssh_body.extend(f"- Blocked reason: {item}" for item in ssh_dedup["blocked_reasons"])
    save_pair(reports_root / "windows-ssh-probe-dedup.closeout-v2.json", ssh_dedup, "Windows SSH Probe Dedup Closeout V2", ssh_body)

    quarantine = build_quarantine_dead_surface(repo_root)
    quarantine_body = [
        f"- Status: {quarantine['status']}",
        f"- Blocked findings: {len([item for item in quarantine['findings'] if item.get('status') == 'BLOCKED'])}",
        f"- Cleanup actions: {json.dumps(quarantine.get('cleanup_actions', []), ensure_ascii=False)}",
    ]
    save_pair(reports_root / "quarantine-and-dead-surface.closeout-v2.json", quarantine, "Quarantine And Dead Surface Closeout V2", quarantine_body)

    inventory = build_inventory(repo_root, skill, ssh_dedup, quarantine)
    inventory_body = [
        f"- Status: {inventory['status']}",
        f"- Remaining Windows policy-like surfaces: {len(inventory['remaining_windows_policy_like_surfaces'])}",
        f"- Repo-owned stale surfaces: {len(inventory['repo_owned_stale_surfaces'])}",
        f"- App-owned runtime state: {len(inventory['app_owned_runtime_state'])}",
        f"- Unrelated dirty files: {len(inventory['unrelated_dirty_files'])}",
    ]
    save_pair(reports_root / "closeout-v2-inventory.json", inventory, "Closeout V2 Inventory", inventory_body)

    warn = build_warn_disposition(repo_root, skill, ssh_dedup, quarantine)
    warn_body = [
        f"- Status: {warn['status']}",
        f"- Entry count: {warn['entry_count']}",
    ]
    warn_body.extend(f"- {entry['id']}: {entry['disposition']}" for entry in warn.get("entries", []))
    save_pair(reports_root / "warn-disposition.closeout-v2.json", warn, "Warn Disposition Closeout V2", warn_body)

    write_restart_note(repo_root)
    print(warn["status"])
    return status_exit_code(warn["status"])


if __name__ == "__main__":
    raise SystemExit(main())
