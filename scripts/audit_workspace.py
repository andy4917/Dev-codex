#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Iterable


AUTHORITY_PATH = Path("/home/andy4917/Dev-Management/contracts/workspace_authority.json")
REPORTS_ROOT = Path("/home/andy4917/Dev-Management/reports")
REPORT_PATH = REPORTS_ROOT / "audit.final.json"
WINDOWS_CODEX = Path("/mnt/c/Users/anise/.codex")
HOME = Path("/home/andy4917")

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
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def load_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


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
    while lines and lines[0].strip() in {"GENERATED - DO NOT EDIT", "# GENERATED - DO NOT EDIT"}:
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return "\n".join(lines).strip()


def quarantine_root_policy_ok(quarantine_root: Path) -> bool:
    return not DATED_DIR_RE.fullmatch(quarantine_root.name)


def generated_runtime_mirror_matches_linux(
    *,
    linux_agents: Path,
    linux_config: Path,
    windows_agents: Path,
    windows_config: Path,
) -> bool:
    if not all(path.exists() for path in [linux_agents, linux_config, windows_agents, windows_config]):
        return False
    return (
        strip_generated_header(read_text(linux_agents)) == strip_generated_header(read_text(windows_agents))
        and strip_generated_header(read_text(linux_config)) == strip_generated_header(read_text(windows_config))
    )


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
    args = parser.parse_args()

    authority = load_authority()
    roots = authority["canonical_roots"]
    trusted_projects = authority["generation_targets"]["global_config"]["trusted_projects"]
    quarantine_root = Path(authority["cleanup_policy"]["quarantine_root"])

    allowed_agents = {
        str(Path("/home/andy4917/.codex/AGENTS.md")),
        str(Path("/mnt/c/Users/anise/.codex/AGENTS.md")),
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
    for path in [Path("/home/andy4917/.codex/AGENTS.md"), Path("/mnt/c/Users/anise/.codex/AGENTS.md")]:
        if path.exists():
            agents_files.append(path)
    agents_files = sorted(set(agents_files))
    if product_root.exists():
        for child in product_root.iterdir():
            if child.is_dir() and (child / "AGENTS.md").exists():
                allowed_agents.add(str(child / "AGENTS.md"))

    allowed_configs = {
        str(Path("/home/andy4917/.codex/config.toml")),
        str(Path("/mnt/c/Users/anise/.codex/config.toml")),
    }
    config_files = [
        path
        for path in [Path("/home/andy4917/.codex/config.toml"), Path("/mnt/c/Users/anise/.codex/config.toml")]
        if path.exists()
    ]
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

    linux_agents = Path("/home/andy4917/.codex/AGENTS.md")
    global_config = Path("/home/andy4917/.codex/config.toml")
    project_root_marker_ok = global_config.exists() and 'project_root_markers = [".git"]' in read_text(global_config)
    windows_agents = Path("/mnt/c/Users/anise/.codex/AGENTS.md")
    windows_config = Path("/mnt/c/Users/anise/.codex/config.toml")
    windows_generated_header_ok = (
        windows_agents.exists()
        and windows_config.exists()
        and read_text(windows_agents).startswith("GENERATED - DO NOT EDIT")
        and read_text(windows_config).startswith("# GENERATED - DO NOT EDIT")
    )
    windows_generated_body_matches_linux = generated_runtime_mirror_matches_linux(
        linux_agents=linux_agents,
        linux_config=global_config,
        windows_agents=windows_agents,
        windows_config=windows_config,
    )
    quarantine_root_ok = quarantine_root_policy_ok(quarantine_root)

    files_to_scan: list[Path] = []
    for base in scan_roots:
        if not base.exists():
            continue
        files_to_scan.extend(
            find_paths(
                base,
                lambda p: p.is_file()
                and not should_skip(p, authority, quarantine_root)
                and p.suffix.lower() in {".md", ".json", ".toml", ".py", ".yml", ".yaml", ".mjs", ".sh", ".txt", ".cmd"},
                authority,
                quarantine_root,
            )
        )
    files_to_scan.extend(path for path in [windows_agents, windows_config] if path.exists())
    old_path_refs = text_paths(files_to_scan, authority["hardcoding_definition"]["path_rules"]["legacy_repo_paths_to_remove"])
    historical_allowlist = set(authority["hardcoding_definition"]["path_rules"].get("historical_evidence_allowlist", []))
    old_path_refs = [
        path
        for path in old_path_refs
        if not str(path).startswith(str(quarantine_root))
        and path != str(AUTHORITY_PATH)
        and Path(path).name not in historical_allowlist
    ]
    forbidden_feature_findings = detect_forbidden_feature_flags(config_files, authority)
    runtime_restore_seed_violations = detect_runtime_restore_seed_violations(WINDOWS_CODEX / ".codex-global-state.json", authority)
    score_policy_tamper_events = detect_score_policy_tamper_events(Path(roots["management"]), Path(roots["workflow"]))
    tamper_events = build_tamper_events(
        old_path_refs=old_path_refs,
        forbidden_features=forbidden_feature_findings,
        runtime_restore_seed_violations=runtime_restore_seed_violations,
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

    report = {
        "phase": str(args.phase).strip() or "final",
        "blocking_only": bool(args.blocking_only),
        "authority_path": str(AUTHORITY_PATH),
        "trusted_projects": trusted_projects,
        "agents_files": [str(p) for p in sorted(agents_files)],
        "config_files": [str(p) for p in sorted(config_files)],
        "contracts_dirs": [str(p) for p in sorted(contracts_dirs)],
        "violations": violations,
        "project_rule_leaks": sorted(set(product_rule_leaks)),
        "quarantine_root_policy_ok": quarantine_root_ok,
        "project_root_markers_git_only": project_root_marker_ok,
        "windows_generated_mirror": windows_generated_header_ok,
        "windows_generated_mirror_matches_linux": windows_generated_body_matches_linux,
        "forbidden_feature_flags_enabled": forbidden_feature_findings,
        "runtime_restore_seed_violations": runtime_restore_seed_violations,
        "old_path_refs_outside_quarantine": sorted(set(old_path_refs)),
        "tamper_events": tamper_events,
        "status": "PASS"
        if (
            not any(violations.values())
            and not product_rule_leaks
            and quarantine_root_ok
            and project_root_marker_ok
            and windows_generated_header_ok
            and windows_generated_body_matches_linux
            and not forbidden_feature_findings
            and not runtime_restore_seed_violations
            and not old_path_refs
            and not tamper_events
        )
        else "FAIL",
    }

    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.write_report:
        output_path = report_path_for_phase(args.phase)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
