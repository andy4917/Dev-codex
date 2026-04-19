#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
BASE_SKIP_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "coverage",
}
ALT_PROJECT_ROOT_MARKERS = {".hg", ".svn", ".bzr", ".jj", "_darcs"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def root_name(path: Path, roots: dict[str, str]) -> str:
    for name, raw_root in roots.items():
        root = Path(raw_root).resolve()
        try:
            path.relative_to(root)
            return name
        except ValueError:
            continue
    return "external"


def path_in_runtime_state(path: Path, runtime_tokens: set[str]) -> bool:
    return any(part in runtime_tokens for part in path.parts)


def iter_project_roots(product_root: Path) -> list[Path]:
    if not product_root.exists():
        return []
    return sorted(path for path in product_root.iterdir() if path.is_dir())


def is_valid_project_root(project_root: Path) -> bool:
    return (project_root / ".git").exists()


def project_root_for_path(path: Path, product_root: Path) -> Path | None:
    path = path.resolve()
    product_root = product_root.resolve()
    try:
        relative = path.relative_to(product_root)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return product_root / relative.parts[0]


def should_track_named_dir(
    path: Path,
    authority: dict[str, Any],
    quarantine_root: Path,
    runtime_tokens: set[str],
) -> bool:
    try:
        path.relative_to(quarantine_root)
        return True
    except ValueError:
        pass

    if path_in_runtime_state(path, runtime_tokens):
        return True

    roots = {name: Path(raw).resolve() for name, raw in authority["canonical_roots"].items()}
    path = path.resolve()
    if path == roots["management"] / "contracts":
        return True

    workflow_skill_source = authority.get("classification_rules", {}).get("workflow", {}).get("canonical_skill_source")
    if workflow_skill_source and path == roots["workflow"] / workflow_skill_source:
        return True

    if path.parent in roots.values():
        return True

    project_root = project_root_for_path(path, roots["product"])
    return project_root is not None and path.parent == project_root


def classify_artifact(
    path: Path,
    kind: str,
    authority: dict[str, Any],
    quarantine_root: Path,
    runtime_tokens: set[str],
    project_roots: list[Path],
    canonical_skill_dir: Path | None,
) -> tuple[str, str]:
    try:
        path.relative_to(quarantine_root)
        return "quarantine-worthy", "Already located under the authority quarantine root."
    except ValueError:
        pass

    if path_in_runtime_state(path, runtime_tokens):
        return "runtime-state", "Located under a runtime-state directory excluded by workspace authority."

    management_contracts = (Path(authority["canonical_roots"]["management"]).resolve() / "contracts").resolve()
    if kind == "contracts_dir" and path == management_contracts:
        return "canonical", "Global contracts are canonical only under Dev-Management/contracts."

    if canonical_skill_dir and kind == "skills_dir" and path == canonical_skill_dir:
        return "canonical", "Shared skills are canonical only at the workflow canonical skill source."

    for project_root in project_roots:
        project_root = project_root.resolve()
        if not is_valid_project_root(project_root):
            continue
        allowed = {
            "agents_file": project_root / "AGENTS.md",
            "codex_config": project_root / ".codex" / "config.toml",
            "contracts_dir": project_root / "contracts",
        }
        if allowed.get(kind) == path:
            return "project-local", "Allowed project-local rule path under Dev-Product/<project>/."

    return "quarantine-worthy", "Artifact does not match a canonical or valid project-local authority location."


def find_artifacts(
    base: Path,
    authority: dict[str, Any],
    quarantine_root: Path,
    runtime_tokens: set[str],
) -> list[tuple[str, Path]]:
    artifacts: list[tuple[str, Path]] = []
    if not base.exists():
        return artifacts

    for root, dirs, files in os.walk(base):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if name not in BASE_SKIP_DIRS]

        for name in list(dirs):
            candidate = root_path / name
            if not should_track_named_dir(candidate, authority, quarantine_root, runtime_tokens):
                continue
            if name == "contracts":
                artifacts.append(("contracts_dir", candidate))
            elif name == "rules":
                artifacts.append(("rules_dir", candidate))
            elif name == "skills":
                artifacts.append(("skills_dir", candidate))
            elif name in {"skill", "policy", "policies"}:
                artifacts.append(("policy_dir", candidate))

        for name in files:
            path = root_path / name
            if name == "AGENTS.md":
                artifacts.append(("agents_file", path))
            elif name == "hooks.json":
                artifacts.append(("hooks_file", path))
            elif name == "config.toml" and path.parent.name == ".codex":
                artifacts.append(("codex_config", path))

    return sorted(set(artifacts), key=lambda item: str(item[1]))


def scan_config_markers(config_path: Path, expected_markers: list[str]) -> dict[str, Any] | None:
    if not config_path.exists():
        return None
    payload = parse_toml(config_path)
    markers = [str(item) for item in payload.get("project_root_markers", [])]
    if not markers:
        return None
    if markers == expected_markers:
        return None
    return {
        "path": str(config_path),
        "markers": markers,
        "expected": expected_markers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit canonical roots for drifted policy artifacts.")
    parser.add_argument("--authority-path", default=str(DEFAULT_AUTHORITY_PATH), help="Path to workspace_authority.json.")
    parser.add_argument("--output-file", help="Optional path to write the JSON report.")
    args = parser.parse_args()

    authority_path = Path(args.authority_path).resolve()
    authority = load_json(authority_path)
    roots = {name: str(Path(raw).resolve()) for name, raw in authority["canonical_roots"].items()}
    quarantine_root = Path(authority["cleanup_policy"]["quarantine_root"]).resolve()
    runtime_tokens = set(authority.get("runtime_state_exclusions", []))
    runtime_tokens.update({"reports", "memory", "knowledge"})

    workflow_cfg = authority.get("classification_rules", {}).get("workflow", {})
    canonical_skill_dir: Path | None = None
    canonical_skill_source = workflow_cfg.get("canonical_skill_source")
    if canonical_skill_source:
        canonical_skill_dir = Path(roots["workflow"]) / canonical_skill_source

    product_root = Path(roots["product"])
    project_roots = iter_project_roots(product_root)
    artifacts_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for root in (Path(roots["management"]), Path(roots["workflow"]), product_root):
        for kind, path in find_artifacts(root, authority, quarantine_root, runtime_tokens):
            classification, reason = classify_artifact(
                path.resolve(),
                kind,
                authority,
                quarantine_root,
                runtime_tokens,
                project_roots,
                canonical_skill_dir.resolve() if canonical_skill_dir else None,
            )
            entry = (
                {
                    "path": str(path.resolve()),
                    "kind": kind,
                    "root_scope": root_name(path.resolve(), roots),
                    "classification": classification,
                    "reason": reason,
                }
            )
            artifacts_by_key[(entry["path"], kind)] = entry
    artifacts = sorted(artifacts_by_key.values(), key=lambda item: item["path"])

    expected_markers = [
        str(item)
        for item in authority.get("generation_targets", {}).get("global_config", {}).get("project_root_markers", [])
    ]
    config_marker_violations: list[dict[str, Any]] = []
    all_config_paths = [Path(entry["path"]) for entry in artifacts if entry["kind"] == "codex_config"]
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    for key in ("linux", "windows_mirror"):
        config_path = runtime.get(key, {}).get("config")
        if config_path:
            all_config_paths.append(Path(config_path))
    for config_path in sorted(set(path.resolve() for path in all_config_paths)):
        violation = scan_config_markers(config_path, expected_markers)
        if violation:
            config_marker_violations.append(violation)

    repository_marker_violations: list[dict[str, Any]] = []
    project_roots_missing_git: list[str] = []
    for project_root in project_roots:
        local_artifacts = [
            item
            for item in artifacts
            if item["path"].startswith(f"{project_root.resolve()}/")
            and item["kind"] in {"agents_file", "codex_config", "contracts_dir"}
        ]
        if local_artifacts and not is_valid_project_root(project_root):
            project_roots_missing_git.append(str(project_root.resolve()))

    for root in (Path(roots["management"]), Path(roots["workflow"]), product_root):
        if not root.exists():
            continue
        for marker in ALT_PROJECT_ROOT_MARKERS:
            for path in root.rglob(marker):
                if path_in_runtime_state(path, runtime_tokens) or any(part in BASE_SKIP_DIRS for part in path.parts):
                    continue
                repository_marker_violations.append(
                    {
                        "path": str(path.resolve()),
                        "marker": marker,
                    }
                )

    project_rule_violations = [
        item["path"]
        for item in artifacts
        if item["classification"] == "quarantine-worthy"
        and not item["path"].startswith(f"{quarantine_root}/")
    ]

    counts = Counter(item["classification"] for item in artifacts)
    checks = {
        "project_specific_rules_outside_product": {
            "status": "PASS" if not project_rule_violations else "FAIL",
            "violations": sorted(project_rule_violations),
        },
        "git_only_project_root_marker": {
            "status": (
                "PASS"
                if expected_markers == [".git"]
                and not config_marker_violations
                and not repository_marker_violations
                and not project_roots_missing_git
                else "FAIL"
            ),
            "expected_markers": expected_markers,
            "config_marker_violations": config_marker_violations,
            "repository_marker_violations": repository_marker_violations,
            "project_roots_missing_git": sorted(project_roots_missing_git),
        },
    }

    report = {
        "authority_path": str(authority_path),
        "canonical_roots": roots,
        "quarantine_root": str(quarantine_root),
        "artifacts": sorted(artifacts, key=lambda item: item["path"]),
        "summary": {
            "canonical": counts.get("canonical", 0),
            "project-local": counts.get("project-local", 0),
            "runtime-state": counts.get("runtime-state", 0),
            "quarantine-worthy": counts.get("quarantine-worthy", 0),
        },
        "checks": checks,
        "status": "PASS" if all(check["status"] == "PASS" for check in checks.values()) else "FAIL",
    }

    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output_file:
        output_path = Path(args.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
