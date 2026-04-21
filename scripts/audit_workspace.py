#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterable

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from check_artifact_hygiene import evaluate_artifact_hygiene
from check_active_config_smoke import evaluate_active_config_smoke
from check_config_provenance import evaluate_config_provenance
from check_hook_readiness import evaluate_hook_readiness
from preflight_path_context import evaluate_path_context
from check_toolchain_surface import evaluate_toolchain_surface
from check_windows_app_ssh_readiness import evaluate_windows_app_ssh_readiness
from devmgmt_runtime.authority import load_authority as load_shared_authority
from devmgmt_runtime.paths import runtime_paths as managed_runtime_paths


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
REPORTS_ROOT = ROOT / "reports"
REPORT_PATH = REPORTS_ROOT / "audit.final.json"
HOME = Path.home()

BASE_SKIP_DIRS = {
    ".git",
    ".venv",
    ".egg-info",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "dist-app",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
}

WINDOWS_STATE_DIRS = {
    ".tmp",
    ".sandbox-bin",
    "bin",
    "cache",
    "memories",
    "plugins",
    "sessions",
    "shell_snapshots",
    "sqlite",
    "tmp",
    "vendor_imports",
}

DATED_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROTECTED_SCORE_POLICY_FILES = (
    "contracts/user_score_policy.json",
    "contracts/disqualifier_policy.json",
)


def load_authority() -> dict:
    return load_shared_authority(ROOT, authority_path=AUTHORITY_PATH)


def load_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def runtime_paths(authority: dict[str, Any]) -> dict[str, Path]:
    paths = managed_runtime_paths(authority)
    return {
        **paths,
        "linux_user_override_config": paths["linux_user_override"],
    }


def git_lines(repo_root: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def runtime_skip_tokens(authority: dict) -> set[str]:
    return {
        *BASE_SKIP_DIRS,
        *authority.get("runtime_state_exclusions", []),
        "reports",
        "memory",
        "knowledge",
        ".codex_tmp",
        "quarantine",
    }


def is_state_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.endswith(".sqlite")
        or name.endswith(".db")
        or name.endswith(".bak")
        or name in {".codex-global-state.json", "session_index.jsonl"}
    )


def should_skip(path: Path, authority: dict, quarantine_root: Path) -> bool:
    try:
        path.resolve().relative_to(quarantine_root.resolve())
        return True
    except Exception:
        pass
    try:
        path.resolve().relative_to(WINDOWS_CODEX.resolve())
        if any(part in WINDOWS_STATE_DIRS for part in path.parts):
            return True
    except Exception:
        pass
    return (
        any(part in runtime_skip_tokens(authority) for part in path.parts)
        or any(part.endswith(".egg-info") for part in path.parts)
        or is_state_file(path)
    )


def find_paths(base: Path, matcher, authority: dict, quarantine_root: Path) -> list[Path]:
    results: list[Path] = []
    if not base.exists():
        return results
    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if not should_skip(root_path / d, authority, quarantine_root)]
        for name in files:
            path = root_path / name
            if should_skip(path, authority, quarantine_root):
                continue
            if matcher(path):
                results.append(path)
        for name in dirs:
            path = root_path / name
            if should_skip(path, authority, quarantine_root):
                continue
            if matcher(path):
                results.append(path)
    return sorted(set(results))


def text_paths(paths: Iterable[Path], needles: list[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(needle in text for needle in needles):
            hits.append(str(path))
    return sorted(hits)


def forbidden_feature_flags(authority: dict) -> set[str]:
    feature_rules = authority.get("hardcoding_definition", {}).get("feature_rules", {})
    return {str(item).strip() for item in feature_rules.get("forbidden_feature_flags", []) if str(item).strip()}


def detect_forbidden_feature_flags(config_paths: Iterable[Path], authority: dict) -> list[dict[str, str]]:
    forbidden = forbidden_feature_flags(authority)
    findings: list[dict[str, str]] = []
    if not forbidden:
        return findings
    for path in config_paths:
        payload = load_toml(path)
        features = payload.get("features", {})
        if not isinstance(features, dict):
            continue
        for feature in sorted(forbidden):
            if features.get(feature) is True:
                findings.append(
                    {
                        "path": str(path),
                        "feature": feature,
                        "reason": f"forbidden feature flag '{feature}' is still enabled",
                    }
                )
    return findings


def normalize_legacy_path_markers(authority: dict) -> list[str]:
    return [
        str(item).replace("\\", "/").lower()
        for item in authority.get("hardcoding_definition", {})
        .get("path_rules", {})
        .get("legacy_repo_paths_to_remove", [])
        if str(item).strip()
    ]


def detect_runtime_restore_seed_violations(state_path: Path, authority: dict) -> list[dict[str, object]]:
    state = load_json(state_path, default={})
    if not isinstance(state, dict) or not state:
        return []

    violations: list[dict[str, object]] = []
    restore = authority.get("runtime_layering", {}).get("restore_seed_policy", {})
    preferred_host = str(restore.get("preferred_windows_access_host", "wsl.localhost")).lower()
    allowed_hosts = {
        preferred_host,
        *{
            str(host).strip().lower()
            for host in restore.get("allowed_windows_access_hosts", [])
            if str(host).strip()
        },
    }
    legacy_markers = normalize_legacy_path_markers(authority)

    projectless = state.get("projectless-thread-ids", [])
    if isinstance(projectless, list) and projectless:
        violations.append(
            {
                "category": "projectless_restore_refs",
                "path": str(state_path),
                "reason": f"projectless restore refs remain active: {len(projectless)}",
                "disqualifier_ids": ["DQ-010"],
                "evidence_refs": [str(state_path)],
            }
        )

    hints = state.get("thread-workspace-root-hints", {})
    if isinstance(hints, dict) and hints:
        violations.append(
            {
                "category": "thread_workspace_root_hints",
                "path": str(state_path),
                "reason": f"thread workspace root hints remain active: {len(hints)}",
                "disqualifier_ids": ["DQ-010"],
                "evidence_refs": [str(state_path)],
            }
        )

    for key in ("active-workspace-roots", "electron-saved-workspace-roots", "project-order"):
        raw_values = state.get(key, [])
        if not isinstance(raw_values, list):
            continue
        bad_values: list[str] = []
        for value in raw_values:
            if not isinstance(value, str):
                continue
            normalized = value.replace("\\", "/").lower()
            if "/mnt/c/" in normalized or any(marker in normalized for marker in legacy_markers):
                bad_values.append(value)
                continue
            if normalized.startswith("//"):
                host = normalized[2:].split("/", 1)[0]
                if host in allowed_hosts:
                    continue
                bad_values.append(value)
        if bad_values:
            violations.append(
                {
                    "category": key.replace("-", "_"),
                    "path": str(state_path),
                    "reason": f"{key} contains stale or non-canonical runtime roots",
                    "values": bad_values,
                    "disqualifier_ids": ["DQ-010"],
                    "evidence_refs": [str(state_path)],
                }
            )
    return violations


RUNTIME_RESTORE_WARNING_ONLY_CATEGORIES = {
    "projectless_restore_refs",
    "thread_workspace_root_hints",
}


def partition_runtime_restore_seed_violations(
    violations: Iterable[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    blocking: list[dict[str, object]] = []
    warning_only: list[dict[str, object]] = []
    for violation in violations:
        if str(violation.get("category", "")) in RUNTIME_RESTORE_WARNING_ONLY_CATEGORIES:
            warning_only.append(dict(violation))
        else:
            blocking.append(dict(violation))
    return blocking, warning_only


def build_tamper_events(
    *,
    old_path_refs: Iterable[str],
    forbidden_features: Iterable[dict[str, str]],
    runtime_restore_seed_violations: Iterable[dict[str, object]],
    score_policy_tamper_events: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for path in sorted(set(old_path_refs)):
        events.append(
            {
                "category": "legacy_path_reference",
                "reason": "legacy path reference remains outside allowlist or quarantine",
                "path": path,
                "disqualifier_ids": ["DQ-004", "DQ-010"],
                "evidence_refs": [path],
            }
        )
    for finding in forbidden_features:
        events.append(
            {
                "category": "forbidden_feature_flag",
                "reason": finding["reason"],
                "path": finding["path"],
                "feature": finding["feature"],
                "disqualifier_ids": ["DQ-010"],
                "evidence_refs": [finding["path"]],
            }
        )
    for violation in runtime_restore_seed_violations:
        events.append(dict(violation))
    for violation in score_policy_tamper_events:
        events.append(dict(violation))
    return events


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def strip_generated_header(text: str) -> str:
    lines = text.splitlines()
    while lines and (lines[0].strip() in {"GENERATED - DO NOT EDIT", "# GENERATED - DO NOT EDIT"} or lines[0].startswith("# GENERATED") or lines[0].startswith("# source_") or lines[0].startswith("# generated_") or lines[0].startswith("# role=") or lines[0].startswith("# read_by_") or lines[0].startswith("# user_override_source=") or lines[0].startswith("# optional_user_override=") or lines[0].startswith("# manual_edit=")):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def quarantine_root_policy_ok(quarantine_root: Path) -> bool:
    return not DATED_DIR_RE.fullmatch(quarantine_root.name)


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def launcher_header_ok(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines()[:3] if line.strip()]
    return len(lines) >= 2 and lines[0] == "#!/usr/bin/env bash" and lines[1] == "# GENERATED - DO NOT EDIT"


def extract_launcher_target(text: str) -> str:
    match = re.search(r'^\s*target=(["\'])(?P<target>.+?)\1\s*$', text, re.MULTILINE)
    return match.group("target") if match else ""


def is_forbidden_runtime_value(value: str, authority: dict[str, Any]) -> bool:
    normalized = value.replace("\\", "/").strip().lower()
    for raw in authority.get("forbidden_primary_runtime_paths", []):
        marker = str(raw).replace("\\", "/").strip().lower()
        if marker == ".codex/bin/wsl/codex" and normalized.endswith(marker):
            return True
        if marker and marker in normalized:
            return True
    return False


def diff_preview(left: str, right: str, *, left_label: str, right_label: str, limit: int = 20) -> list[str]:
    if left == right:
        return []
    diff_lines = list(
        difflib.unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile=left_label,
            tofile=right_label,
            lineterm="",
        )
    )
    if len(diff_lines) <= limit:
        return diff_lines
    return [*diff_lines[:limit], "... diff truncated ..."]


def load_script_function(script_name: str, function_name: str):
    script_path = Path(__file__).resolve().with_name(script_name)
    spec = importlib.util.spec_from_file_location(f"_audit_probe_{script_path.stem}", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def build_startup_workflow_check(management_root: Path, *, purpose: str = "code-modification") -> dict[str, Any]:
    try:
        evaluator = load_script_function("check_startup_workflow.py", "evaluate_startup_workflow")
        payload = evaluator(management_root, purpose=purpose)
        if isinstance(payload, dict):
            return payload
        return {
            "status": "FAIL",
            "summary": "startup workflow check returned an unexpected payload",
            "repo_root": str(management_root),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "summary": "startup workflow check failed to run",
            "repo_root": str(management_root),
            "reason": str(exc),
        }


def build_global_runtime_surface_check(
    management_root: Path,
    *,
    windows_ssh_readiness_report: str | Path | None = None,
    no_live_windows_ssh_probe: bool = True,
) -> dict[str, Any]:
    try:
        evaluator = load_script_function("check_global_runtime.py", "evaluate_global_runtime")
        payload = evaluator(
            management_root,
            mode="auto",
            windows_ssh_readiness_report=windows_ssh_readiness_report,
            no_live_windows_ssh_probe=no_live_windows_ssh_probe,
        )
        return payload if isinstance(payload, dict) else {"status": "BLOCKED", "reason": "unexpected global runtime payload"}
    except Exception as exc:
        return {"status": "BLOCKED", "reason": str(exc)}


def build_git_surface_drift_check() -> dict[str, Any]:
    try:
        evaluator = load_script_function("check_git_surface.py", "evaluate_git_surfaces")
        payload = evaluator()
        return payload if isinstance(payload, dict) else {"status": "WARN", "reason": "unexpected git surface payload"}
    except Exception as exc:
        return {"status": "WARN", "reason": str(exc)}


def build_workspace_dependency_surface_check(management_root: Path, runtime: dict[str, Path]) -> dict[str, Any]:
    report_path = management_root / "reports" / "workspace-dependency-surface.json"
    report = load_json(report_path, default={}) if report_path.exists() else {}
    feature_enabled = False
    if runtime["linux_config"].exists():
        payload = load_toml(runtime["linux_config"])
        features = payload.get("features", {})
        if isinstance(features, dict):
            feature_enabled = bool(features.get("workspace_dependencies") is True)
    tool_status = str(report.get("tool_status", "")).strip() if isinstance(report, dict) else ""
    status = "PASS"
    reasons: list[str] = []
    if feature_enabled and not report_path.exists():
        status = "WARN"
        reasons.append("workspace dependency feature is enabled but no app-surface availability report is present")
    elif feature_enabled and tool_status in {"DISABLED_IN_APP_SETTINGS", "DISABLED", "BLOCKED"}:
        status = "WARN"
        reasons.append("workspace dependency feature is enabled but the current Codex app disables workspace dependency tools")
    return {
        "status": status,
        "feature_enabled": feature_enabled,
        "report_path": str(report_path),
        "report_present": report_path.exists(),
        "tool_status": tool_status,
        "report": report,
        "reasons": reasons,
    }


def build_instruction_guard_policy_check(management_root: Path) -> dict[str, Any]:
    policy_path = management_root / "contracts" / "instruction_guard_policy.json"
    payload = load_json(policy_path, default={})
    persisted = bool(payload.get("bootstrap_exception", {}).get("persisted", True)) if isinstance(payload, dict) else True
    return {
        "policy_path": str(policy_path),
        "present": policy_path.exists(),
        "bootstrap_exception_persisted": persisted,
        "status": "PASS" if policy_path.exists() and not persisted else "BLOCKED",
    }


def build_repair_boundary_check(authority: dict[str, Any]) -> dict[str, Any]:
    payload = authority.get("repair_boundaries", {})
    blocked_targets = [str(item) for item in payload.get("repo_must_not_treat_as_repo_owned", [])]
    return {
        "status": "PASS" if payload else "WARN",
        "boundaries": payload,
        "external_targets": blocked_targets,
    }


def build_linux_source_of_truth_proof(authority: dict[str, Any], runtime: dict[str, Path]) -> dict[str, Any]:
    linux_agents = runtime["linux_agents"].resolve()
    linux_config = runtime["linux_config"].resolve()
    linux_user_override = runtime["linux_user_override_config"].resolve()
    authority_source = str(authority.get("_authority_path", AUTHORITY_PATH))

    probe = {
        "script": str(Path(__file__).resolve().with_name("render_codex_runtime.py")),
        "function": "user_override_config_paths",
        "linux_config_path": str(linux_config),
        "linux_user_override_config_path": str(linux_user_override),
        "returned_paths": [],
        "linux_config_used_as_override_source": False,
        "linux_user_override_used_as_override_source": False,
        "reasons": [],
        "status": "FAIL",
    }
    try:
        user_override_paths = load_script_function("render_codex_runtime.py", "user_override_config_paths")
        returned_paths = [str(Path(item).expanduser().resolve()) for item in user_override_paths(authority)]
        probe["returned_paths"] = returned_paths
        probe["linux_config_used_as_override_source"] = str(linux_config) in returned_paths
        probe["linux_user_override_used_as_override_source"] = str(linux_user_override) in returned_paths if linux_user_override.exists() else False
        if probe["linux_config_used_as_override_source"]:
            probe["reasons"].append("render_codex_runtime.py treated the Linux generated config as an override input.")
        if linux_user_override.exists() and not probe["linux_user_override_used_as_override_source"]:
            probe["reasons"].append("render_codex_runtime.py did not expose the dedicated Linux user override path as the optional override input.")
        probe["status"] = "PASS" if not probe["reasons"] else "FAIL"
    except Exception as exc:
        probe["reasons"].append(f"unable to evaluate render_codex_runtime.py user_override_config_paths: {exc}")

    targets_are_distinct = len({linux_agents, linux_config, linux_user_override}) == 3
    reasons = list(probe["reasons"])
    if not targets_are_distinct:
        reasons.append("workspace authority does not keep Linux generated runtime targets distinct from the dedicated user override target.")

    status = "PASS" if targets_are_distinct and probe["status"] == "PASS" else "FAIL"
    return {
        "authority_path": authority_source,
        "agents_generation_source": authority_source,
        "linux_runtime_targets": {
            "agents": str(linux_agents),
            "config": str(linux_config),
            "user_override_config": str(linux_user_override),
        },
        "linux_targets_are_distinct": targets_are_distinct,
        "config_override_probe": probe,
        "reasons": reasons,
        "status": status,
    }


def build_windows_policy_surface_check(
    runtime: dict[str, Path],
    config_provenance: dict[str, Any],
    active_config_smoke: dict[str, Any],
    *,
    linux_source_of_truth_proof: dict[str, Any] | None = None,
) -> dict[str, Any]:
    findings = [
        dict(item)
        for item in config_provenance.get("windows_policy_surface_findings", [])
        if isinstance(item, dict)
    ]
    known_generated_cleanup_candidates = [
        str(item.get("path", ""))
        for item in findings
        if str(item.get("disposition", "")).strip() in {"INERT_QUARANTINE", "REMOVE_NOW"}
    ]
    unknown_observed = [
        str(item.get("path", ""))
        for item in findings
        if str(item.get("disposition", "")).strip() in {"MANUAL_REMEDIATION", "ACCEPTED_NONBLOCKING"}
    ]
    files = {
        "config": runtime["observed_windows_policy_config"],
        "agents": runtime["observed_windows_policy_agents"],
        "hooks": runtime["observed_windows_policy_hooks"],
        "skills": runtime["observed_windows_policy_skills"],
    }
    app_evidence_status = str(active_config_smoke.get("windows_app_evidence_status", "WARN")).strip() or "WARN"
    status = (
        "BLOCKED"
        if str(config_provenance.get("windows_policy_surface_status", "PASS")) != "PASS"
        else "WARN"
        if app_evidence_status != "PASS"
        else "PASS"
    )
    if str(config_provenance.get("windows_policy_surface_status", "PASS")) == "WARN":
        status = "WARN" if app_evidence_status == "PASS" else "WARN"
    reasons = [str(item.get("reason", "")) for item in findings if str(item.get("reason", "")).strip()]
    if app_evidence_status != "PASS":
        reasons.append("Windows Codex App state evidence was not observed on this host.")
    return {
        "windows_observed_root": str(runtime["observed_windows_codex_home"]),
        "policy_role": "windows_policy_surface_violation",
        "canonical_source": "linux_runtime_outputs_only",
        "authoritative": False,
        "repo_generation_allowed": False,
        "files": {
            name: {
                "path": str(path),
                "exists": path.exists(),
                "is_dir": path.is_dir(),
                "has_generated_header": generated if path.exists() else False,
            }
            for name, path, generated in [
                ("config", files["config"], str(files["config"]) in known_generated_cleanup_candidates),
                ("agents", files["agents"], str(files["agents"]) in known_generated_cleanup_candidates),
                ("hooks", files["hooks"], str(files["hooks"]) in known_generated_cleanup_candidates),
                ("skills", files["skills"], str(files["skills"]) in known_generated_cleanup_candidates),
            ]
        },
        "findings": findings,
        "known_generated_cleanup_candidates": sorted(path for path in known_generated_cleanup_candidates if path),
        "unknown_windows_policy_files_blocking": [],
        "unknown_windows_policy_files_observed": sorted(path for path in unknown_observed if path),
        "windows_app_evidence_status": app_evidence_status,
        "linux_source_of_truth_proof": linux_source_of_truth_proof or {},
        "reasons": reasons,
        "status": status,
    }


def build_wsl_launcher_check(
    authority: dict[str, Any],
    runtime: dict[str, Path] | None = None,
) -> dict[str, Any]:
    runtime_paths_map = runtime or runtime_paths(authority)
    linux_launcher = runtime_paths_map["linux_launcher"]
    launcher_text = read_text(linux_launcher)
    configured_target = extract_launcher_target(launcher_text)
    management_root_value = str(authority.get("canonical_roots", {}).get("management", "")).strip()
    global_runtime = (
        build_global_runtime_surface_check(Path(management_root_value))
        if management_root_value
        else {
            "local_runtime_surface": {
                "local_live_codex_resolution_status": {"status": "PASS"},
                "local_path_precedence_status": {"status": "PASS"},
            },
            "wrapper_target_safety_status": {"status": "PASS"},
        }
    )

    reasons: list[str] = []
    if not linux_launcher.exists():
        reasons.append(f"Linux Codex launcher shim is missing: {linux_launcher}")
    elif not launcher_header_ok(launcher_text):
        reasons.append(f"Linux Codex launcher shim is missing the generated header: {linux_launcher}")
    if configured_target and is_forbidden_runtime_value(configured_target, authority):
        reasons.append("Linux Codex launcher shim still points to the forbidden Windows-mounted launcher.")
    live_status = (
        global_runtime.get("local_runtime_surface", {})
        .get("local_live_codex_resolution_status", {})
        .get("status", "BLOCKED")
    )
    precedence_status = (
        global_runtime.get("local_runtime_surface", {})
        .get("local_path_precedence_status", {})
        .get("status", "BLOCKED")
    )
    wrapper_safety = global_runtime.get("wrapper_target_safety_status", {}).get("status", "BLOCKED")
    if live_status != "PASS":
        reasons.append("Live command -v codex resolves to a forbidden runtime target.")
    if precedence_status != "PASS":
        reasons.append("Local PATH precedence still allows forbidden runtime entries ahead of the local wrapper.")
    if wrapper_safety != "PASS":
        reasons.append("Rendered wrapper target is not safe.")
    canonical_execution_status = global_runtime.get("canonical_execution_status", "BLOCKED")
    status = "PASS" if not reasons else "WARN" if canonical_execution_status == "PASS" else "BLOCKED"

    return {
        "linux_launcher_path": str(linux_launcher),
        "linux_launcher_exists": linux_launcher.exists(),
        "linux_launcher_generated_header_ok": launcher_header_ok(launcher_text) if launcher_text else False,
        "configured_target": configured_target,
        "global_runtime_surface": global_runtime,
        "reasons": reasons,
        "status": status,
    }


def windows_policy_surface_absent(*paths: Path) -> bool:
    return not any(path.exists() for path in paths)


def policy_update_workorder_present(*paths: Path) -> bool:
    for path in paths:
        if path.exists() and "Policy Update Workorder:" in read_text(path):
            return True
    return False


def latest_agent_run_file(workflow_root: Path, filename: str) -> Path | None:
    runs_root = workflow_root / ".agent-runs"
    if not runs_root.exists():
        return None
    candidates = sorted(path for path in runs_root.glob(f"*/{filename}") if path.is_file())
    if not candidates:
        return None
    return candidates[-1]


def structured_policy_update_workorder_present(management_root: Path, workflow_root: Path, changed: list[str]) -> bool:
    if not policy_update_workorder_present(management_root / "DESIGN_REVIEW.md", workflow_root / "DESIGN_REVIEW.md"):
        return False

    workorder_path = latest_agent_run_file(workflow_root, "WORKORDER.json")
    manifest_path = latest_agent_run_file(workflow_root, "EVIDENCE_MANIFEST.json")
    if workorder_path is None or manifest_path is None:
        return False

    workorder = load_json(workorder_path, default={})
    manifest = load_json(manifest_path, default={})
    if not isinstance(workorder, dict) or not isinstance(manifest, dict):
        return False
    if not bool(workorder.get("rollback_plan_required", False)):
        return False

    policy_hashes = manifest.get("policy_hashes", {})
    before_hashes = dict(policy_hashes.get("before", {})) if isinstance(policy_hashes, dict) else {}
    after_hashes = dict(policy_hashes.get("after", {})) if isinstance(policy_hashes, dict) else {}
    changed_names = {Path(path).name for path in changed}
    if not changed_names:
        return False
    if any(name not in before_hashes or name not in after_hashes for name in changed_names):
        return False

    diff_paths = set(git_lines(management_root, "diff", "--name-only", "HEAD"))
    has_fixture_test_update = any(path.startswith("tests/") for path in diff_paths)
    has_snapshot_update = "reports/user-scorecard.json" in diff_paths
    return has_fixture_test_update and has_snapshot_update


def detect_score_policy_tamper_events(management_root: Path, workflow_root: Path) -> list[dict[str, object]]:
    changed = git_lines(management_root, "diff", "--name-only", "HEAD", "--", *PROTECTED_SCORE_POLICY_FILES)
    if not changed:
        return []
    if structured_policy_update_workorder_present(management_root, workflow_root, changed):
        return []
    return [
        {
            "category": "score_policy_tamper_without_policy_update_workorder",
            "reason": "protected score policy changed without a valid policy update workorder, hashes, fixture coverage, and snapshot update",
            "path": str(management_root / changed[0]),
            "disqualifier_ids": ["DQ-011"],
            "evidence_refs": [str(management_root / path) for path in changed],
        }
    ]


def report_path_for_phase(phase: str) -> Path:
    normalized = str(phase or "").strip().lower()
    if not normalized:
        return REPORT_PATH
    return REPORTS_ROOT / f"audit.{normalized}.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the canonical Codex workspace layout.")
    parser.add_argument("--phase", choices=["pre-gate", "pre-export", "post-export"], default="")
    parser.add_argument("--blocking-only", action="store_true", help="Record the phase as blocking-only while keeping the same canonical checks.")
    parser.add_argument("--write-report", action="store_true", help="Write the audit report to the default report path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--output-file", default="", help="Optional explicit report output path.")
    parser.add_argument("--purpose", choices=["code-modification", "app-usability"], default="code-modification")
    parser.add_argument("--refresh-windows-ssh", action="store_true")
    parser.add_argument("--windows-ssh-readiness-report", default="")
    parser.add_argument("--no-live-windows-ssh-probe", action="store_true")
    args = parser.parse_args()

    authority = load_authority()
    authority["_authority_path"] = str(AUTHORITY_PATH)
    roots = authority["canonical_roots"]
    trusted_projects = authority["generation_targets"]["global_config"]["trusted_projects"]
    quarantine_root = Path(authority["cleanup_policy"]["quarantine_root"])
    runtime = runtime_paths(authority)

    allowed_agents = {
        str(runtime["linux_agents"]),
    }
    product_root = Path(roots["product"])
    scan_roots = [
        Path(roots["management"]),
        Path(roots["workflow"]),
        product_root,
    ]
    agents_files: list[Path] = []
    for base in scan_roots:
        agents_files.extend(find_paths(base, lambda p: p.name == "AGENTS.md", authority, quarantine_root))
    for path in [runtime["linux_agents"]]:
        if path.exists():
            agents_files.append(path)
    agents_files = sorted(set(agents_files))
    if product_root.exists():
        for child in product_root.iterdir():
            if child.is_dir() and (child / "AGENTS.md").exists():
                allowed_agents.add(str(child / "AGENTS.md"))

    allowed_configs = {
        str(runtime["linux_config"]),
    }
    config_files = [path for path in [runtime["linux_config"]] if path.exists()]
    if product_root.exists():
        for child in product_root.iterdir():
            cfg = child / ".codex" / "config.toml"
            if cfg.exists():
                allowed_configs.add(str(cfg))
                config_files.append(cfg)
    config_files = sorted(set(config_files))

    contracts_dirs: list[Path] = []
    management_contracts = Path(roots["management"]) / "contracts"
    if management_contracts.is_dir():
        contracts_dirs.append(management_contracts)
    allowed_contract_dirs = {str(management_contracts)}
    if product_root.exists():
        for child in product_root.iterdir():
            contract_dir = child / "contracts"
            if contract_dir.is_dir():
                contracts_dirs.append(contract_dir)
                allowed_contract_dirs.add(str(contract_dir))

    violations = {
        "unexpected_agents": [str(p) for p in agents_files if str(p) not in allowed_agents],
        "unexpected_configs": [str(p) for p in config_files if str(p) not in allowed_configs],
        "unexpected_contract_dirs": [str(p) for p in contracts_dirs if str(p) not in allowed_contract_dirs],
    }

    linux_agents = runtime["linux_agents"]
    global_config = runtime["linux_config"]
    project_root_marker_ok = global_config.exists() and 'project_root_markers = [".git"]' in read_text(global_config)
    global_runtime_surface = build_global_runtime_surface_check(
        Path(roots["management"]),
        windows_ssh_readiness_report=args.windows_ssh_readiness_report or None,
        no_live_windows_ssh_probe=True,
    )
    wsl_launcher_check = build_wsl_launcher_check(authority, runtime=runtime)
    git_surface_drift = build_git_surface_drift_check()
    workspace_dependency_surface = build_workspace_dependency_surface_check(Path(roots["management"]), runtime)
    instruction_guard_policy = build_instruction_guard_policy_check(Path(roots["management"]))
    repair_boundary = build_repair_boundary_check(authority)
    config_provenance = evaluate_config_provenance(Path(roots["management"]))
    active_config_smoke = evaluate_active_config_smoke(Path(roots["management"]))
    linux_source_of_truth_proof = build_linux_source_of_truth_proof(authority, runtime)
    windows_policy_surface_check = build_windows_policy_surface_check(
        runtime,
        config_provenance,
        active_config_smoke,
        linux_source_of_truth_proof=linux_source_of_truth_proof,
    )
    toolchain_surface = evaluate_toolchain_surface(Path(roots["management"]))
    hook_readiness = evaluate_hook_readiness(Path(roots["management"]))
    artifact_hygiene = evaluate_artifact_hygiene(Path(roots["management"]))
    path_preflight = evaluate_path_context(Path(roots["management"]))
    windows_app_ssh_readiness = evaluate_windows_app_ssh_readiness(
        Path(roots["management"]),
        refresh_windows_ssh=bool(args.refresh_windows_ssh),
        windows_ssh_readiness_report=args.windows_ssh_readiness_report or None,
        no_live_windows_ssh_probe=bool(args.no_live_windows_ssh_probe),
        allow_cache_miss_live_probe=False,
    )
    release_report = load_json(REPORTS_ROOT / "codex-app-installed-release-impact.unified-phase.json", default={})
    score_layer = load_json(
        REPORTS_ROOT / "score-layer.final.json",
        load_json(
            REPORTS_ROOT / "score-layer.unified-phase.final.json",
            load_json(
                REPORTS_ROOT / "score-layer.unified-phase.json",
                default={"status": "PASS", "missing": True, "warnings": ["run_score_layer.py after audit to finalize score evidence"]},
            ),
        ),
    )
    quarantine_root_ok = quarantine_root_policy_ok(quarantine_root)
    old_path_refs = list(path_preflight.get("legacy_repo_refs", []))
    forbidden_feature_findings = detect_forbidden_feature_flags(config_files, authority)
    runtime_restore_seed_violations = detect_runtime_restore_seed_violations(runtime["observed_windows_codex_home"] / ".codex-global-state.json", authority)
    blocking_runtime_restore_seed_violations, warning_runtime_restore_seed_violations = partition_runtime_restore_seed_violations(
        runtime_restore_seed_violations
    )
    score_policy_tamper_events = detect_score_policy_tamper_events(Path(roots["management"]), Path(roots["workflow"]))
    startup_workflow_check = build_startup_workflow_check(Path(roots["management"]), purpose=args.purpose)
    tamper_events = build_tamper_events(
        old_path_refs=old_path_refs,
        forbidden_features=forbidden_feature_findings,
        runtime_restore_seed_violations=blocking_runtime_restore_seed_violations,
        score_policy_tamper_events=score_policy_tamper_events,
    )

    product_rule_leaks = []
    for path in agents_files + config_files + list(contracts_dirs):
        path_str = str(path)
        if path_str.startswith(roots["product"]):
            continue
        if path_str in allowed_agents or path_str in allowed_configs or path_str in allowed_contract_dirs:
            continue
        product_rule_leaks.append(path_str)

    canonical_execution_surface = {
        "status": global_runtime_surface.get("canonical_execution_status", "BLOCKED"),
        "details": global_runtime_surface.get("ssh_canonical_runtime", {}),
    }
    client_surface = global_runtime_surface.get("client_surface", {})
    local_shell_surface = global_runtime_surface.get("local_shell_surface", {})
    codex_resolution = global_runtime_surface.get("codex_resolution", {})
    path_contamination = global_runtime_surface.get("path_contamination", {})
    ssh_activation = global_runtime_surface.get("ssh_activation", {})
    serena_startup = startup_workflow_check.get("serena", {})
    context7_evidence = startup_workflow_check.get("context7", {})
    repair_readiness = global_runtime_surface.get("wrapper_apply_readiness", {})
    linux_native_codex_cli = global_runtime_surface.get("ssh_canonical_runtime", {}).get("remote_native_codex_status", {})
    legacy_feature_scan = {"status": "BLOCKED" if forbidden_feature_findings else "PASS", "findings": forbidden_feature_findings}
    hardcoding_fallback_scan = {
        "status": str(path_preflight.get("hardcoded_path_scan", {}).get("status", "PASS")),
        "findings": sorted(
            {
                *old_path_refs,
                *[
                    str(item.get("relative_path", item.get("path", "")))
                    for item in path_preflight.get("hardcoded_path_scan", {}).get("findings", [])
                    if str(item.get("relative_path", item.get("path", ""))).strip()
                ],
            }
        ),
    }

    blocking_conditions = [
        bool(any(violations.values())),
        bool(product_rule_leaks),
        not quarantine_root_ok,
        not project_root_marker_ok,
        windows_policy_surface_check["status"] == "BLOCKED",
        canonical_execution_surface["status"] != "PASS",
        config_provenance.get("gate_status", config_provenance.get("status")) == "BLOCKED",
        active_config_smoke.get("gate_status", active_config_smoke.get("status")) == "BLOCKED",
        toolchain_surface["status"] == "BLOCKED",
        hook_readiness["status"] == "BLOCKED",
        artifact_hygiene["status"] == "BLOCKED",
        path_preflight["status"] == "BLOCKED",
        windows_app_ssh_readiness["status"] == "BLOCKED",
        startup_workflow_check["status"] == "BLOCKED",
        instruction_guard_policy["status"] != "PASS",
        bool(forbidden_feature_findings),
        bool(old_path_refs),
        bool(tamper_events),
    ]
    if args.purpose == "app-usability":
        blocking_conditions.append(str(windows_app_ssh_readiness.get("app_remote_project_status", "UNOBSERVED")) != "OPENED")
    warning_conditions = [
        global_runtime_surface.get("status") == "WARN",
        windows_policy_surface_check["status"] == "WARN",
        wsl_launcher_check["status"] == "WARN",
        git_surface_drift["status"] == "WARN",
        windows_app_ssh_readiness["status"] == "WARN",
        hook_readiness["status"] == "WARN",
        artifact_hygiene["status"] == "WARN",
        path_preflight["status"] == "WARN",
        bool(warning_runtime_restore_seed_violations),
        str(score_layer.get("status", "PASS")) in {"WARN", "BLOCKED"} and not bool(score_layer.get("missing", False)),
        str((release_report or {}).get("status", "PASS")) == "WARN",
        repair_readiness.get("status") != "PASS",
        startup_workflow_check["status"] == "WARN",
    ]
    gate_status = "BLOCKED" if any(blocking_conditions) else "WARN" if any(warning_conditions) else "PASS"

    report = {
        "phase": str(args.phase).strip() or "final",
        "blocking_only": bool(args.blocking_only),
        "purpose": args.purpose,
        "authority_path": str(AUTHORITY_PATH),
        "trusted_projects": trusted_projects,
        "agents_files": [str(p) for p in sorted(agents_files)],
        "config_files": [str(p) for p in sorted(config_files)],
        "contracts_dirs": [str(p) for p in sorted(contracts_dirs)],
        "violations": violations,
        "project_rule_leaks": sorted(set(product_rule_leaks)),
        "quarantine_root_policy_ok": quarantine_root_ok,
        "project_root_markers_git_only": project_root_marker_ok,
        "windows_policy_surface_status": config_provenance.get("windows_policy_surface_status", "PASS"),
        "windows_policy_surface_findings": config_provenance.get("windows_policy_surface_findings", []),
        "known_generated_windows_policy_files_deleted": config_provenance.get("known_generated_windows_policy_files_deleted", []),
        "unknown_windows_policy_files_blocking": config_provenance.get("unknown_windows_policy_files_blocking", []),
        "windows_app_evidence_status": active_config_smoke.get("windows_app_evidence_status", "WARN"),
        "windows_policy_surface_check": windows_policy_surface_check,
        "codex_app_installed_release": release_report or {"status": "WARN", "reason": "installed app release evidence report is missing"},
        "config_provenance": config_provenance,
        "active_config_smoke": active_config_smoke,
        "linux_source_of_truth_proof": linux_source_of_truth_proof,
        "generated_mirror_contract": config_provenance.get("generated_mirror_contract", {}),
        "toolchain_surface": toolchain_surface,
        "hook_readiness": hook_readiness,
        "score_layer": score_layer,
        "artifact_hygiene": artifact_hygiene,
        "path_preflight": path_preflight,
        "legacy_feature_scan": legacy_feature_scan,
        "hardcoding_fallback_scan": hardcoding_fallback_scan,
        "canonical_execution_surface": canonical_execution_surface,
        "windows_app_ssh_readiness": windows_app_ssh_readiness,
        "app_remote_project_status": windows_app_ssh_readiness.get("app_remote_project_status", "UNOBSERVED"),
        "app_remote_project_path": windows_app_ssh_readiness.get("app_remote_project_path", ""),
        "windows_app_blocking_domain": windows_app_ssh_readiness.get("blocking_domain", ""),
        "linux_native_codex_cli": linux_native_codex_cli,
        "client_surface": client_surface,
        "local_shell_surface": local_shell_surface,
        "codex_resolution": codex_resolution,
        "path_contamination": path_contamination,
        "ssh_activation": ssh_activation,
        "serena_startup": serena_startup,
        "context7_evidence": context7_evidence,
        "git_surface": git_surface_drift,
        "workspace_dependency_surface": workspace_dependency_surface,
        "instruction_guard": instruction_guard_policy,
        "repair_readiness": repair_readiness,
        "global_runtime_surface": global_runtime_surface,
        "codex_live_resolution": global_runtime_surface.get("local_runtime_surface", {}).get("local_live_codex_resolution_status", {}),
        "path_contamination_legacy": {
            "local": global_runtime_surface.get("local_runtime_surface", {}).get("contaminated_entries", []),
            "remote": global_runtime_surface.get("ssh_canonical_runtime", {})
            .get("remote_path_contamination_status", {})
            .get("contaminated_entries", []),
        },
        "ssh_canonical_runtime": global_runtime_surface.get("ssh_canonical_runtime", {}),
        "git_surface_drift": git_surface_drift,
        "instruction_guard_policy": instruction_guard_policy,
        "repair_boundary": repair_boundary,
        "wsl_launcher_check": wsl_launcher_check,
        "startup_workflow_check": startup_workflow_check,
        "forbidden_feature_flags_enabled": forbidden_feature_findings,
        "runtime_restore_seed_violations": runtime_restore_seed_violations,
        "runtime_restore_seed_warning_only": warning_runtime_restore_seed_violations,
        "runtime_restore_seed_blocking": blocking_runtime_restore_seed_violations,
        "old_path_refs_outside_quarantine": sorted(set(old_path_refs)),
        "tamper_events": tamper_events,
        "gate_status": gate_status,
        "status": "FAIL" if gate_status == "BLOCKED" else "WARN" if gate_status == "WARN" else "PASS",
    }

    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.write_report or args.output_file:
        output_path = Path(args.output_file).expanduser().resolve() if args.output_file else report_path_for_phase(args.phase)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
