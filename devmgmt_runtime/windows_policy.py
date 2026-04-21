from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any


GENERATED_DIRECTORY_MARKERS = {
    ".devmgmt-generated",
    ".generated-by-dev-management",
    ".devmgmt-mirror-manifest.json",
}
GENERATED_FILE_HEADERS = (
    "# GENERATED - DO NOT EDIT",
    "GENERATED - DO NOT EDIT",
)
SKILL_ACTIVE_ENTRY_SUFFIXES = {
    ".bat",
    ".cmd",
    ".dll",
    ".exe",
    ".ps1",
    ".py",
    ".sh",
    ".so",
}
SKILL_MANIFEST_NAMES = {
    "package.json",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
    "setup.py",
}
WINDOWS_BOOTSTRAP_FEATURES = ("remote_control", "remote_connections")


def read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generated_header_present(path: Path) -> bool:
    return read_text(path).startswith(GENERATED_FILE_HEADERS)


def _loads_toml(text: str) -> dict[str, Any]:
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_structural_devmgmt_windows_config(text: str) -> bool:
    payload = _loads_toml(text)
    if not payload:
        return False
    features = payload.get("features", {}) if isinstance(payload.get("features"), dict) else {}
    if not features:
        return False
    feature_keys = sorted(str(key) for key in features.keys())
    if feature_keys != sorted(WINDOWS_BOOTSTRAP_FEATURES):
        allowed_feature_keys = {"chronicle", "memories", *WINDOWS_BOOTSTRAP_FEATURES}
        if not set(feature_keys).issubset(allowed_feature_keys):
            return False
    if any(features.get(key) is not True for key in WINDOWS_BOOTSTRAP_FEATURES):
        return False
    projects = payload.get("projects", {}) if isinstance(payload.get("projects"), dict) else {}
    project_keys = [str(key) for key in projects.keys()]
    project_refs_devmgmt = any(Path(key).is_absolute() and "Dev-Management" in key for key in project_keys)
    # Structural Dev-Management bootstrap residue may keep model/trusted-project state,
    # but it must not carry broader policy tables such as approval, sandbox, or plugins.
    forbidden_top_level = {"approval_policy", "sandbox_mode", "mcp_servers", "projects", "plugins"}
    if any(key in payload for key in forbidden_top_level - {"projects"}):
        return False
    allowed_top_level = {"features", "model", "model_reasoning_effort", "projects", "ux", "workspace_preference", "memories"}
    if not set(str(key) for key in payload.keys()).issubset(allowed_top_level):
        return False
    return bool(project_refs_devmgmt or "model" in payload or "model_reasoning_effort" in payload)


def is_structural_devmgmt_agents_surface(text: str) -> bool:
    normalized = text.replace("\r\n", "\n")
    return (
        "Generated Codex Workspace Contract" in normalized
        or "Windows ~/.codex is app runtime state and evidence only." in normalized
        or "Authority file:" in normalized and "contracts/workspace_authority.json" in normalized
    )


def is_structural_devmgmt_hook_surface(text: str) -> bool:
    normalized = text.replace("\r\n", "\n")
    return "scorecard_runtime_hook.py" in normalized or "UserPromptSubmit" in normalized


def generated_directory_marker_present(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    return any((path / marker).exists() for marker in GENERATED_DIRECTORY_MARKERS)


def canonical_workflow_skill_root(authority: dict[str, Any]) -> Path | None:
    skill_cfg = authority.get("generation_targets", {}).get("skill_exposure", {})
    wsl_symlink = skill_cfg.get("wsl_symlink", {}) if isinstance(skill_cfg, dict) else {}
    target = str(wsl_symlink.get("target", "")).strip()
    if target:
        return Path(target).expanduser().resolve()
    roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    workflow_root = str(roots.get("workflow", "")).strip()
    if workflow_root:
        return (Path(workflow_root).expanduser().resolve() / "skills").resolve()
    return None


def _skill_tree_details(path: Path) -> dict[str, Any]:
    details = {
        "exists": path.exists(),
        "is_dir": path.is_dir(),
        "files": [],
        "hashes": {},
        "symlinks": [],
        "unexpected_files": [],
        "active_entries": [],
        "executable_markdown": [],
    }
    if not path.exists() or not path.is_dir():
        return details

    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        root_path = Path(root)
        for name in list(dirs):
            child = root_path / name
            if child.is_symlink():
                details["symlinks"].append(str(child.relative_to(path)))
        for name in files:
            child = root_path / name
            relative = str(child.relative_to(path))
            if child.is_symlink():
                details["symlinks"].append(relative)
                continue
            details["files"].append(relative)
            details["hashes"][relative] = sha256(child)
            executable = bool(child.stat().st_mode & 0o111)
            if name == "SKILL.md":
                if executable:
                    details["executable_markdown"].append(relative)
                continue
            details["unexpected_files"].append(relative)
            if child.suffix.lower() in SKILL_ACTIVE_ENTRY_SUFFIXES or name in SKILL_MANIFEST_NAMES:
                details["active_entries"].append(relative)
    return details


def classify_windows_skill_mirror(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    canonical_root = canonical_workflow_skill_root(authority)
    details = _skill_tree_details(path)
    result = {
        "canonical_skill_root": str(canonical_root) if canonical_root else "",
        "windows_tree": details,
        "canonical_tree": {},
        "is_structural_mirror": False,
        "reason": "",
    }
    if not path.exists():
        result["reason"] = "Windows skill surface is absent."
        return result
    if not path.is_dir():
        result["reason"] = "Windows skill surface is not a directory."
        return result
    if canonical_root is None or not canonical_root.exists():
        result["reason"] = "Canonical Linux skill root could not be resolved."
        return result

    canonical = _skill_tree_details(canonical_root)
    result["canonical_tree"] = canonical
    result["is_structural_mirror"] = (
        not details["symlinks"]
        and not details["active_entries"]
        and not canonical["symlinks"]
        and not canonical["active_entries"]
        and details["files"] == canonical["files"]
        and details["hashes"] == canonical["hashes"]
        and all(item.endswith("SKILL.md") for item in details["files"])
    )
    if result["is_structural_mirror"]:
        result["reason"] = (
            "Windows dev-workflow skills are a byte-for-byte mirror of the canonical Linux Dev-Workflow skills tree, "
            "contain only SKILL.md files, and are stale policy-bearing residue."
        )
        return result

    if details["symlinks"]:
        result["reason"] = "Windows skill surface contains symlinks and cannot be auto-removed as a simple stale mirror."
    elif details["active_entries"]:
        result["reason"] = "Windows skill surface contains active manifests or executable/importable entries and must be treated as external state."
    elif details["files"] != canonical["files"]:
        result["reason"] = "Windows skill surface diverges from the canonical Linux skill file set."
    else:
        result["reason"] = "Windows skill surface content diverges from the canonical Linux skill content."
    return result


def classify_windows_policy_candidate(
    path: Path,
    authority: dict[str, Any],
    *,
    expected_linux_hooks: str | None = None,
) -> dict[str, Any]:
    payload = {
        "path": str(path),
        "present": path.exists(),
        "kind": "directory" if path.name == "dev-workflow" or path.is_dir() else "file",
        "classification": "absent",
        "disposition": "ACCEPTED_NONBLOCKING",
        "operation": "retain",
        "status": "PASS",
        "generated_marker_found": False,
        "repo_owned": False,
        "reason": "path is absent",
        "details": {},
    }
    if not path.exists():
        return payload

    if path.name == "dev-workflow" and path.is_dir():
        mirror = classify_windows_skill_mirror(path, authority)
        payload["details"] = mirror
        if mirror["is_structural_mirror"]:
            payload.update(
                {
                    "classification": "stale_dev_workflow_skill_mirror",
                    "disposition": "REMOVE_NOW",
                    "operation": "remove",
                    "status": "BLOCKED",
                    "repo_owned": True,
                    "reason": str(mirror["reason"]),
                }
            )
            return payload
        payload.update(
            {
                "classification": "external_app_or_user_state",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "WARN",
                "reason": str(mirror["reason"]),
            }
        )
        return payload

    if path.is_dir():
        generated = path.is_symlink() or generated_directory_marker_present(path)
        payload["generated_marker_found"] = generated
        if generated:
            payload.update(
                {
                    "classification": "generated_policy_surface",
                    "disposition": "REMOVE_NOW",
                    "operation": "remove",
                    "status": "BLOCKED",
                    "repo_owned": True,
                    "reason": "directory carries a Dev-Management generated marker or symlink and must be removed instead of preserved as backup residue",
                }
            )
            return payload
        payload.update(
            {
                "classification": "external_app_or_user_state",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "WARN",
                "reason": "directory is app-readable Windows state without generated markers and must be treated as external state",
            }
        )
        return payload

    text = read_text(path)
    generated = generated_header_present(path)
    if path.name == "hooks.json" and expected_linux_hooks is not None and text == expected_linux_hooks:
        generated = True
    payload["generated_marker_found"] = generated
    if generated:
        payload.update(
            {
                "classification": "generated_policy_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "file carries a Dev-Management generated marker or matches the generated Linux hooks payload and must be removed instead of preserved as backup residue",
            }
        )
        return payload

    if path.name == "config.toml" and is_structural_devmgmt_windows_config(text):
        payload.update(
            {
                "classification": "stale_devmgmt_bootstrap_config",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows .codex config contains only Dev-Management bootstrap feature flags and must be removed instead of preserved as a policy surface",
            }
        )
        return payload

    if path.name == "AGENTS.md" and is_structural_devmgmt_agents_surface(text):
        payload.update(
            {
                "classification": "stale_devmgmt_agents_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows AGENTS content is structurally a Dev-Management-generated policy mirror and must be removed",
            }
        )
        return payload

    if path.name == "hooks.json" and is_structural_devmgmt_hook_surface(text):
        payload.update(
            {
                "classification": "stale_devmgmt_hook_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows hooks content is structurally a Dev-Management-generated policy surface and must be removed",
            }
        )
        return payload

    payload.update(
        {
            "classification": "external_app_or_user_state",
            "disposition": "MANUAL_REMEDIATION",
            "operation": "retain",
            "status": "WARN",
            "reason": "non-generated Windows policy-bearing file diverges from Linux generated outputs and is treated as external app or user state",
        }
    )
    return payload


def windows_policy_surface_report(
    paths: dict[str, Path],
    authority: dict[str, Any],
    *,
    expected_linux_hooks: str | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    known_generated_cleanup_candidates: list[str] = []
    remove_now_candidates: list[str] = []
    manual_remediation_candidates: list[str] = []
    accepted_nonblocking_candidates: list[str] = []

    candidates = [
        paths["observed_windows_policy_config"],
        paths["observed_windows_policy_agents"],
        paths["observed_windows_policy_hooks"],
        paths["observed_windows_policy_skills"],
    ]
    for path in candidates:
        finding = classify_windows_policy_candidate(path, authority, expected_linux_hooks=expected_linux_hooks)
        if not finding["present"]:
            continue
        findings.append(finding)
        if finding["classification"] == "generated_policy_surface":
            known_generated_cleanup_candidates.append(str(path))
        if finding["disposition"] == "REMOVE_NOW":
            remove_now_candidates.append(str(path))
        elif finding["disposition"] == "MANUAL_REMEDIATION":
            manual_remediation_candidates.append(str(path))
        else:
            accepted_nonblocking_candidates.append(str(path))

    status = (
        "BLOCKED"
        if known_generated_cleanup_candidates or remove_now_candidates
        else "WARN"
        if manual_remediation_candidates or accepted_nonblocking_candidates
        else "PASS"
    )
    return {
        "status": status,
        "findings": findings,
        "known_generated_cleanup_candidates": sorted(set(known_generated_cleanup_candidates)),
        "remove_now_candidates": sorted(remove_now_candidates),
        "manual_remediation_candidates": sorted(manual_remediation_candidates),
        "accepted_nonblocking_candidates": sorted(accepted_nonblocking_candidates),
        "unknown_observed": sorted(manual_remediation_candidates + accepted_nonblocking_candidates),
        "unknown_blocking": [],
    }


def remove_directory_tree(path: Path) -> int:
    removed = 0
    if not path.exists():
        return removed
    for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
        root_path = Path(root)
        for name in files:
            child = root_path / name
            if child.exists() or child.is_symlink():
                child.unlink()
                removed += 1
        for name in dirs:
            child = root_path / name
            if child.is_symlink():
                child.unlink()
                removed += 1
            elif child.exists():
                child.rmdir()
                removed += 1
    path.rmdir()
    removed += 1
    return removed
