from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any, Iterable

from .path_authority import canonical_roots, load_path_policy, workflow_doc_path
from .scorecard_hook import is_expected_hooks_json
from .trash import recycle_path


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
WINDOWS_SAFE_FEATURE_KEYS = {
    "apps",
    "codex_hooks",
    "memories",
    "plugins",
    "tool_call_mcp_elicitation",
    "tool_search",
    "tool_suggest",
    *WINDOWS_BOOTSTRAP_FEATURES,
}
WINDOWS_SAFE_TOP_LEVEL_KEYS = {
    "analytics",
    "approval_policy",
    "features",
    "marketplaces",
    "mcp_servers",
    "memories",
    "model",
    "model_reasoning_effort",
    "projects",
    "sandbox_mode",
    "shell_zsh_fork",
    "ux",
    "web_search",
    "windows",
    "workspace_preference",
    "zsh_path",
    "plugins",
}
WINDOWS_BLOCKED_TOP_LEVEL_KEYS = {
    "hooks",
    "project_root_markers",
    "skills",
    "telepathy",
}
WINDOWS_BLOCKED_FEATURE_KEYS = {"telepathy"}
WINDOWS_BLOCKED_POINTER_KEYS = {
    "workspace_authority",
    "path_authority",
    "path_policy",
    "runtime_paths",
    "launcher",
    "linux_native_codex",
}
WINDOWS_FORBIDDEN_RUNTIME_MARKERS = (
    "mounted-linux-launcher",
    ".codex/tmp/arg0",
    "/home/",
    "/mnt/",
    "legacy-linux",
    "legacy-remote",
)
WINDOWS_ALLOWED_MCP_SERVERS = {"context7", "serena"}
WINDOWS_MCP_LOCAL_EXECUTION_KEYS = {"args", "command", "cwd", "env", "executable", "path", "script"}
WINDOWS_SKILL_ALLOWED_DOC_NAMES = {
    ".codex-system-skills.marker",
    "license",
    "license.txt",
    "notice",
    "notice.txt",
    "readme",
    "readme.md",
    "skill.md",
}
WINDOWS_SKILL_ALLOWED_DOC_SUFFIXES = {".md", ".rst", ".txt"}
WINDOWS_SKILL_SYSTEM_ROOTS = {".system"}
SECRET_VALUE_MARKERS = ("-----begin ", "ghp_", "sk-", "xoxb-")
def path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def path_is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False


def read_text(path: Path) -> str:
    if not path_is_file(path):
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


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


def _normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\\", "/").strip().lower()


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_strings(item)


def _contains_forbidden_runtime_reference(payload: dict[str, Any]) -> bool:
    return any(marker in _normalized_text(text) for text in _iter_strings(payload) for marker in WINDOWS_FORBIDDEN_RUNTIME_MARKERS)


def _authority_markers(authority: dict[str, Any] | None = None) -> tuple[str, ...]:
    payload = authority if isinstance(authority, dict) else {}
    markers = {
        "contracts/workspace_authority.json",
        "contracts/path_authority_policy.json",
    }
    surface = payload.get("canonical_execution_surface", {}) if isinstance(payload.get("canonical_execution_surface"), dict) else {}
    if (
        str(payload.get("canonical_execution_host", "")).strip() == "windows-native"
        or str(surface.get("id", "")).strip() == "windows-native"
        or str(surface.get("expected_os", "")).strip().lower() == "windows"
    ):
        return tuple(sorted(markers))
    roots = canonical_roots(payload) if payload else {}
    if not roots:
        try:
            roots = canonical_roots(load_path_policy())
        except Exception:
            roots = {}
    for root in roots.values():
        markers.add(str(root).replace("\\", "/").lower())
    return tuple(sorted(markers))


def approved_global_agents_text(authority: dict[str, Any] | None = None) -> str:
    policy = authority if isinstance(authority, dict) else None
    try:
        workflow_doc = workflow_doc_path(policy)
    except Exception:
        root = ""
        if isinstance(policy, dict):
            root = str(policy.get("authority_root", "") or policy.get("canonical_repo_root", "")).strip()
        workflow_doc = Path(root) / "docs" / "GLOBAL_AGENT_WORKFLOW.md" if root else Path("GLOBAL_AGENT_WORKFLOW.md")
    return (
        "Global authority capsule:\n"
        "- The user's explicit instruction is the highest project authority inside allowed system/developer constraints.\n"
        "- Before work, read and follow:\n"
        f"{workflow_doc}\n\n"
        "- Codex App is my UI and Windows-native execution control plane. "
        "Repo-specific stack and commands come from that repo's AGENTS.md and package scripts.\n\n"
        "- Use Serena for codebase exploration, Context7 for external docs, and tests/reports for final claims. "
        "If required evidence is missing, report the gap and do not fabricate it.\n\n"
        "- Always run the exact code path touched before claiming behavior; exercise all touched functions directly when practical, "
        "and use C:\\Users\\anise\\code\\.scratch\\Dev-Management scratch harnesses to copy relevant production context and observe actual behavior.\n"
        "- Test means limited counterexample search plus partial evidence; verification means declared oracle/scope/policy match; review means adversarial reading; PASS means no counterexample found within declared scope/oracle, not formal approval.\n"
    )


def _pointer_only_text(authority: dict[str, Any] | None = None) -> str:
    return approved_global_agents_text(authority)


def _contains_authority_reference(payload: dict[str, Any], authority: dict[str, Any] | None = None) -> bool:
    return any(marker in _normalized_text(text) for text in _iter_strings(payload) for marker in _authority_markers(authority))


def _project_paths(payload: dict[str, Any]) -> list[str]:
    projects = payload.get("projects", {}) if isinstance(payload.get("projects"), dict) else {}
    return [str(key).strip() for key in projects.keys() if str(key).strip()]


def _canonical_root_values(authority: dict[str, Any]) -> list[str]:
    roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    values: list[str] = []
    for key in ("workflow", "dev_workflow", "management", "dev_management", "product", "dev_product"):
        raw = str(roots.get(key, "")).strip()
        if raw:
            values.append(raw.replace("\\", "/").lower())
    return values


def _safe_features(features: dict[str, Any]) -> bool:
    return set(str(key) for key in features.keys()).issubset(WINDOWS_SAFE_FEATURE_KEYS)


def _safe_top_level_keys(payload: dict[str, Any]) -> bool:
    return set(str(key) for key in payload.keys()).issubset(WINDOWS_SAFE_TOP_LEVEL_KEYS)


def _safe_bootstrap_payload(payload: dict[str, Any]) -> bool:
    features = payload.get("features", {}) if isinstance(payload.get("features"), dict) else {}
    return _safe_top_level_keys(payload) and _safe_features(features)


def _exact_minimal_bootstrap_payload(payload: dict[str, Any]) -> bool:
    features = payload.get("features", {}) if isinstance(payload.get("features"), dict) else {}
    if set(str(key) for key in payload.keys()) != {"features"}:
        return False
    feature_keys = {str(key) for key in features.keys()}
    if feature_keys != set(WINDOWS_BOOTSTRAP_FEATURES):
        return False
    return all(features.get(key) is True for key in WINDOWS_BOOTSTRAP_FEATURES)


def _key_is_secret_like(name: str) -> bool:
    normalized = name.strip().lower().replace("-", "_")
    return (
        normalized in {"api_key", "api_token", "authorization", "password", "secret", "token"}
        or normalized.endswith("_api_key")
        or normalized.endswith("_password")
        or normalized.endswith("_secret")
        or normalized.endswith("_token")
    )


def _contains_secret_material_text(text: str) -> bool:
    normalized = _normalized_text(text)
    return any(marker in normalized for marker in SECRET_VALUE_MARKERS)


def _mcp_server_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        "approved_servers": [],
        "warning_servers": [],
        "blocked_servers": [],
        "warnings": [],
        "reasons": [],
    }
    raw = payload.get("mcp_servers")
    if raw is None:
        return result
    if not isinstance(raw, dict):
        result["reasons"].append("mcp_servers must be a table when present")
        return result

    for name in sorted(str(item).strip() for item in raw.keys()):
        cfg = raw.get(name)
        cfg_dict = cfg if isinstance(cfg, dict) else {}
        cfg_keys = {str(key).strip().lower() for key in cfg_dict.keys()}
        local_execution = bool(cfg_keys.intersection(WINDOWS_MCP_LOCAL_EXECUTION_KEYS))
        secret_like = any(_key_is_secret_like(str(key)) for key in cfg_dict.keys())
        if name in WINDOWS_ALLOWED_MCP_SERVERS:
            result["approved_servers"].append(name)
            if secret_like:
                result["warnings"].append(
                    f"approved MCP server {name} contains secret-like fields; reports must stay redacted"
                )
            continue
        if local_execution:
            result["blocked_servers"].append(name)
            result["reasons"].append(f"unapproved MCP server {name} defines a local executable surface")
            continue
        if secret_like:
            result["blocked_servers"].append(name)
            result["reasons"].append(f"unapproved MCP server {name} contains secret-like fields")
            continue
        result["warning_servers"].append(name)
        result["warnings"].append(f"unapproved MCP server {name} is present; verify it is user-approved and non-authoritative")
    return result


def _workflow_doc_marker(authority: dict[str, Any] | None = None) -> str:
    try:
        return str(workflow_doc_path(authority)).replace("\\", "/").lower()
    except Exception:
        return ""


def _agents_block_reasons(text: str, authority: dict[str, Any]) -> list[str]:
    normalized = _normalized_text(text)
    reasons: list[str] = []
    if _contains_secret_material_text(text):
        reasons.append("Windows AGENTS.md contains secret or token material.")
    if any(token in normalized for token in ("generated codex workspace contract", "dev-management generated mirror")):
        reasons.append("Windows AGENTS.md contains generated Dev-Management contract content.")
    if any(token in normalized for token in ("mounted-linux-launcher", ".codex/tmp/arg0", "legacy-remote")):
        reasons.append("Windows AGENTS.md contains stale launcher or fallback policy content.")
    workflow_marker = _workflow_doc_marker(authority)
    for marker in _authority_markers(authority):
        if marker == workflow_marker:
            continue
        if marker and marker in normalized:
            reasons.append("Windows AGENTS.md contains repo-specific or Dev-Management authority paths.")
            break
    if "source of truth" in normalized or "ssot" in normalized:
        reasons.append("Windows AGENTS.md must not claim source-of-truth status.")
    return reasons


def _allowed_skill_doc(name: str) -> bool:
    normalized = name.strip().lower()
    suffix = Path(name).suffix.lower()
    return normalized in WINDOWS_SKILL_ALLOWED_DOC_NAMES or suffix in WINDOWS_SKILL_ALLOWED_DOC_SUFFIXES


def _skill_text_block_reasons(text: str) -> list[str]:
    normalized = _normalized_text(text)
    reasons: list[str] = []
    if _contains_secret_material_text(text):
        reasons.append("skill content contains secret or token material")
    if any(token in normalized for token in ("source of truth", "factual authority", "repo authority", "policy authority")):
        reasons.append("skill content claims authority instead of workflow guidance")
    if any(
        token in normalized
        for token in (
            "setx path",
            "mounted-linux-launcher",
            "hooks.json",
            ".codex/config.toml",
            "workspace_authority.json",
            "path_authority_policy.json",
        )
    ):
        reasons.append("skill content instructs Windows PATH, launcher, hook, or policy-config mutation")
    return reasons


def is_structural_devmgmt_windows_config(text: str, authority: dict[str, Any] | None = None) -> bool:
    if isinstance(authority, dict) and str(authority.get("canonical_execution_host", "")).strip() == "windows-native":
        return False
    payload = _loads_toml(text)
    if not payload:
        return False
    features = payload.get("features", {}) if isinstance(payload.get("features"), dict) else {}
    if not isinstance(features, dict):
        return False
    feature_keys = {str(key) for key in features.keys()}
    allowed_feature_keys = set(WINDOWS_SAFE_FEATURE_KEYS) | {"chronicle"}
    if not feature_keys or not feature_keys.issubset(allowed_feature_keys):
        return False
    top_level_keys = {str(key) for key in payload.keys()}
    allowed_top_level = set(WINDOWS_SAFE_TOP_LEVEL_KEYS) | {"projects"}
    if not top_level_keys.issubset(allowed_top_level):
        return False
    project_paths = _project_paths(payload)
    if not project_paths:
        return False
    known_roots = _canonical_root_values(authority or {})
    normalized_paths = [path.replace("\\", "/").lower() for path in project_paths]
    if known_roots:
        return all(any(root in path for root in known_roots) for path in normalized_paths)
    return all(any(token in path for token in ("/dev-management", "/dev-workflow", "/dev-product")) for path in normalized_paths)


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
    if not path_is_dir(path):
        return False
    return any(path_exists(path / marker) for marker in GENERATED_DIRECTORY_MARKERS)


def canonical_workflow_skill_root(authority: dict[str, Any]) -> Path | None:
    skill_cfg = authority.get("generation_targets", {}).get("skill_exposure", {})
    skill_link = skill_cfg.get("canonical_skill_root", {}) if isinstance(skill_cfg, dict) else {}
    target = str(skill_link.get("target", "") if isinstance(skill_link, dict) else skill_link).strip()
    if target:
        return Path(target).expanduser().resolve()
    roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    workflow_root = str(roots.get("workflow", "") or roots.get("dev_workflow", "")).strip()
    if workflow_root:
        return (Path(workflow_root).expanduser().resolve() / "skills").resolve()
    return None


def _skill_tree_details(path: Path) -> dict[str, Any]:
    details = {
        "exists": path_exists(path),
        "is_dir": path_is_dir(path),
        "files": [],
        "hashes": {},
        "symlinks": [],
        "unexpected_files": [],
        "active_entries": [],
        "executable_markdown": [],
    }
    if not path_is_dir(path):
        return details

    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        root_path = Path(root)
        for name in list(dirs):
            child = root_path / name
            if path_is_symlink(child):
                details["symlinks"].append(str(child.relative_to(path)))
        for name in files:
            child = root_path / name
            relative = str(child.relative_to(path))
            if path_is_symlink(child):
                details["symlinks"].append(relative)
                continue
            details["files"].append(relative)
            details["hashes"][relative] = sha256(child)
            executable = bool(child.stat().st_mode & 0o111)
            if _allowed_skill_doc(name):
                if executable:
                    details["executable_markdown"].append(relative)
                continue
            details["unexpected_files"].append(relative)
            if child.suffix.lower() in SKILL_ACTIVE_ENTRY_SUFFIXES or name.lower() in {item.lower() for item in SKILL_MANIFEST_NAMES}:
                details["active_entries"].append(relative)
    return details


def classify_windows_skill_mirror(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    dev_workflow_root = path / "dev-workflow"
    canonical_root = canonical_workflow_skill_root(authority)
    details = _skill_tree_details(dev_workflow_root)
    result = {
        "canonical_skill_root": str(canonical_root) if canonical_root else "",
        "windows_tree": details,
        "canonical_tree": {},
        "is_structural_mirror": False,
        "reason": "",
    }
    if not path_exists(path):
        result["reason"] = "Windows skill surface is absent."
        return result
    if not path_is_dir(path):
        result["reason"] = "Windows skill surface is not a directory."
        return result
    if not path_is_dir(dev_workflow_root):
        result["reason"] = "Windows skill surface does not contain a dev-workflow mirror."
        return result
    if canonical_root is None or not path_exists(canonical_root):
        result["reason"] = "Canonical Dev-Workflow skill root could not be resolved."
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
        and sorted(child.name for child in path.iterdir()) == ["dev-workflow"]
    )
    if result["is_structural_mirror"]:
        result["reason"] = (
            "Windows dev-workflow skills are a byte-for-byte mirror of the canonical Dev-Workflow skills tree, "
            "contain only SKILL.md files, and are stale policy-bearing residue."
        )
        return result

    if details["symlinks"]:
        result["reason"] = "Windows skill surface contains symlinks and cannot be auto-removed as a simple stale mirror."
    elif details["active_entries"]:
        result["reason"] = "Windows skill surface contains active manifests or executable/importable entries and must be treated as external state."
    elif details["files"] != canonical["files"]:
        result["reason"] = "Windows skill surface diverges from the canonical Dev-Workflow skill file set."
    else:
        result["reason"] = "Windows skill surface content diverges from the canonical Dev-Workflow skill content."
    return result


def _config_finding(path: Path, authority: dict[str, Any], *, expected_linux_hooks: str | None = None) -> dict[str, Any]:
    text = read_text(path)
    payload = _loads_toml(text)
    empty_placeholder = not text.strip()
    details: dict[str, Any] = {
        "bootstrap_features_required": list(WINDOWS_BOOTSTRAP_FEATURES),
        "feature_keys": [],
        "top_level_keys": [],
        "remote_control_enabled": False,
        "remote_connections_enabled": False,
        "remote_usability_ready": False,
        "safe_user_preferences_only": False,
        "mcp_servers": [],
        "warning_codes": [],
        "reason_codes": [],
    }
    finding = {
        "path": str(path),
        "present": path_exists(path),
        "kind": "file",
        "classification": "absent",
        "disposition": "ACCEPTED_NONBLOCKING",
        "operation": "retain",
        "status": "PASS",
        "generated_marker_found": False,
        "repo_owned": False,
        "reason": "path is absent",
        "details": details,
    }
    if not path_exists(path):
        finding.update(
            {
                "classification": "absent_app_bootstrap",
                "disposition": "ACCEPTED_NONBLOCKING",
                "operation": "retain",
                "status": "WARN",
                "reason": "Windows .codex/config.toml is absent, so Codex App remote bootstrap still needs explicit confirmation.",
            }
        )
        return finding

    generated = generated_header_present(path)
    finding["generated_marker_found"] = generated
    if generated:
        finding.update(
            {
                "classification": "generated_policy_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "file carries a Dev-Management generated marker and must be removed instead of preserved as Windows policy residue",
            }
        )
        return finding

    if empty_placeholder:
        finding.update(
            {
                "classification": "empty_placeholder_config",
                "disposition": "ACCEPTED_NONBLOCKING",
                "operation": "retain",
                "status": "WARN",
                "reason": "Windows .codex/config.toml is an empty placeholder and is not treated as authority.",
            }
        )
        return finding

    if not payload:
        finding.update(
            {
                "classification": "invalid_or_unclassified_config",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": "Windows .codex/config.toml is present but is not valid TOML.",
            }
        )
        return finding

    features = payload.get("features", {}) if isinstance(payload.get("features"), dict) else {}
    details["feature_keys"] = sorted(str(key) for key in features.keys())
    details["top_level_keys"] = sorted(str(key) for key in payload.keys())
    details["remote_control_enabled"] = features.get("remote_control") is True
    details["remote_connections_enabled"] = features.get("remote_connections") is True
    details["remote_usability_ready"] = details["remote_control_enabled"] and details["remote_connections_enabled"]

    if is_structural_devmgmt_windows_config(text, authority):
        details["reason_codes"].append("stale_devmgmt_bootstrap")
        finding.update(
            {
                "classification": "stale_devmgmt_bootstrap_config",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows .codex/config.toml contains stale Dev-Management bootstrap or project authority content and must be removed.",
            }
        )
        return finding

    reasons: list[str] = []
    warnings: list[str] = []
    blocked_top_level = sorted(WINDOWS_BLOCKED_TOP_LEVEL_KEYS.intersection(details["top_level_keys"]))
    if blocked_top_level:
        reasons.append(f"blocked top-level keys present: {', '.join(blocked_top_level)}")
    unknown_top_level = sorted(set(details["top_level_keys"]) - WINDOWS_SAFE_TOP_LEVEL_KEYS - WINDOWS_BLOCKED_TOP_LEVEL_KEYS)
    if unknown_top_level:
        warnings.append(f"unrecognized top-level keys present: {', '.join(unknown_top_level)}")
    blocked_feature_keys = sorted(WINDOWS_BLOCKED_FEATURE_KEYS.intersection(details["feature_keys"]))
    if blocked_feature_keys:
        reasons.append(f"blocked feature keys present: {', '.join(blocked_feature_keys)}")
    unknown_feature_keys = sorted(
        set(details["feature_keys"]) - WINDOWS_SAFE_FEATURE_KEYS - WINDOWS_BLOCKED_FEATURE_KEYS
    )
    if unknown_feature_keys:
        warnings.append(f"unrecognized feature keys present: {', '.join(unknown_feature_keys)}")

    approval_policy = str(payload.get("approval_policy", "")).strip()
    sandbox_mode = str(payload.get("sandbox_mode", "")).strip()
    if approval_policy and approval_policy not in {"never", "on-request", "untrusted"}:
        warnings.append(f"unrecognized approval_policy present: {approval_policy}")
    if sandbox_mode and sandbox_mode not in {"danger-full-access", "workspace-write", "read-only"}:
        warnings.append(f"unrecognized sandbox_mode present: {sandbox_mode}")

    shell_zsh_fork = payload.get("shell_zsh_fork") is True or features.get("shell_zsh_fork") is True
    zsh_path = str(payload.get("zsh_path", "")).strip()
    if shell_zsh_fork and not zsh_path:
        reasons.append("shell_zsh_fork=true without a verified zsh_path is blocked")
    elif shell_zsh_fork and zsh_path and not Path(zsh_path).is_absolute():
        reasons.append("shell_zsh_fork zsh_path must be an absolute path")

    if _contains_forbidden_runtime_reference(payload):
        reasons.append("Legacy Linux or remote runtime authority content is blocked in Windows .codex/config.toml")
    if _contains_authority_reference(payload, authority):
        reasons.append("Dev-Management authority or canonical path content is blocked in Windows .codex/config.toml")
    if any(key in details["top_level_keys"] for key in WINDOWS_BLOCKED_POINTER_KEYS):
        reasons.append("runtime or authority pointer keys are blocked in Windows .codex/config.toml")

    mcp_analysis = _mcp_server_analysis(payload)
    details["mcp_servers"] = sorted(
        set(
            [*mcp_analysis["approved_servers"], *mcp_analysis["warning_servers"], *mcp_analysis["blocked_servers"]]
        )
    )
    reasons.extend(str(item) for item in mcp_analysis["reasons"] if str(item).strip())
    warnings.extend(str(item) for item in mcp_analysis["warnings"] if str(item).strip())

    if reasons:
        details["reason_codes"] = reasons
        details["warning_codes"] = warnings
        finding.update(
            {
                "classification": "blocked_user_or_policy_config",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": reasons[0],
            }
        )
        return finding

    if _exact_minimal_bootstrap_payload(payload):
        details["safe_user_preferences_only"] = False
        details["warning_codes"] = warnings
        finding.update(
            {
                "classification": "exact_minimal_bootstrap",
                "disposition": "RETAIN_SAFE",
                "operation": "retain",
                "status": "PASS",
                "reason": "Windows .codex/config.toml contains the legacy minimal remote bootstrap.",
            }
        )
        return finding

    details["safe_user_preferences_only"] = _safe_bootstrap_payload(payload)
    details["warning_codes"] = warnings
    finding.update(
        {
            "classification": "validated_app_control_plane_config",
            "disposition": "RETAIN_SAFE",
            "operation": "retain",
            "status": "WARN" if warnings else "PASS",
            "reason": warnings[0]
            if warnings
            else "Windows .codex/config.toml is a user-managed app control plane config within validated safety boundaries.",
        }
    )
    return finding


def _agents_finding(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    text = read_text(path)
    normalized = text.strip()
    finding = {
        "path": str(path),
        "present": path_exists(path),
        "kind": "file",
        "classification": "absent",
        "disposition": "ACCEPTED_NONBLOCKING",
        "operation": "retain",
        "status": "PASS",
        "generated_marker_found": False,
        "repo_owned": False,
        "reason": "path is absent",
        "details": {
            "byte_length": len(text.encode("utf-8")),
            "nonempty_lines": [line for line in text.splitlines() if line.strip()],
            "pointer_only": False,
        },
    }
    if not path_exists(path):
        return finding

    generated = generated_header_present(path)
    finding["generated_marker_found"] = generated
    if generated or is_structural_devmgmt_agents_surface(text):
        finding.update(
            {
                "classification": "generated_policy_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows AGENTS.md is Dev-Management-generated or policy-bearing and must be removed.",
            }
        )
        return finding

    if not normalized:
        finding.update(
            {
                "classification": "APP_PLACEHOLDER_EMPTY",
                "disposition": "ACCEPTED_NONBLOCKING",
                "operation": "retain",
                "status": "WARN",
                "reason": "Windows AGENTS.md is a zero-byte placeholder and is not treated as authority.",
            }
        )
        return finding

    if normalized == approved_global_agents_text(authority).strip():
        finding["details"]["pointer_only"] = False
        finding["details"]["authority_capsule"] = True
        finding.update(
            {
                "classification": "APP_GLOBAL_AUTHORITY_CAPSULE",
                "disposition": "RETAIN_SAFE",
                "operation": "retain",
                "status": "PASS",
                "reason": "Windows AGENTS.md contains the approved concise global authority capsule.",
            }
        )
        return finding

    reasons = _agents_block_reasons(text, authority)
    if reasons:
        finding.update(
            {
                "classification": "policy_bearing_agents_surface",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": reasons[0],
            }
        )
        return finding

    finding.update(
        {
            "classification": "noncanonical_global_instruction_surface",
            "disposition": "MANUAL_REMEDIATION",
            "operation": "retain",
            "status": "BLOCKED",
            "reason": "Windows AGENTS.md must match the approved concise global authority capsule exactly; user-managed instruction exceptions are not allowed.",
        }
    )
    return finding


def _hooks_finding(path: Path, authority: dict[str, Any], *, expected_linux_hooks: str | None = None) -> dict[str, Any]:
    text = read_text(path)
    finding = {
        "path": str(path),
        "present": path_exists(path),
        "kind": "file",
        "classification": "absent",
        "disposition": "ACCEPTED_NONBLOCKING",
        "operation": "retain",
        "status": "PASS",
        "generated_marker_found": False,
        "repo_owned": False,
        "reason": "path is absent",
        "details": {},
    }
    if not path_exists(path):
        return finding

    generated = generated_header_present(path)
    if expected_linux_hooks is not None and text == expected_linux_hooks:
        generated = True
    finding["generated_marker_found"] = generated
    if is_expected_hooks_json(text, authority):
        finding.update(
            {
                "classification": "approved_scorecard_runtime_hook",
                "disposition": "RETAIN_SAFE",
                "operation": "retain",
                "status": "PASS",
                "repo_owned": True,
                "reason": "Windows hooks.json contains only the approved scorecard UserPromptSubmit hook.",
            }
        )
        return finding
    if generated or is_structural_devmgmt_hook_surface(text):
        finding.update(
            {
                "classification": "generated_policy_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows hooks content resembles Dev-Management hook policy but does not match the approved scorecard hook payload.",
            }
        )
        return finding

    finding.update(
        {
            "classification": "policy_bearing_hook_surface",
            "disposition": "REMOVE_NOW",
            "operation": "remove",
            "status": "BLOCKED",
            "reason": "Windows hooks.json is an unapproved active hook surface and must be removed.",
        }
    )
    return finding


def _skills_finding(path: Path, authority: dict[str, Any]) -> dict[str, Any]:
    finding = {
        "path": str(path),
        "present": path_exists(path),
        "kind": "directory",
        "classification": "absent",
        "disposition": "ACCEPTED_NONBLOCKING",
        "operation": "retain",
        "status": "PASS",
        "generated_marker_found": False,
        "repo_owned": False,
        "reason": "path is absent",
        "details": {},
    }
    if not path_exists(path):
        return finding
    if not path_is_dir(path):
        finding.update(
            {
                "classification": "policy_bearing_skill_surface",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": "Windows skills surface exists but is not a directory.",
            }
        )
        return finding

    generated = generated_directory_marker_present(path)
    finding["generated_marker_found"] = generated
    if generated:
        finding.update(
            {
                "classification": "generated_policy_surface",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": "Windows skills surface carries a Dev-Management generated marker and must be removed.",
            }
        )
        return finding

    entries = sorted(child.name for child in path.iterdir())
    skill_tree = _skill_tree_details(path)
    finding["details"] = {"entries": entries, "skill_tree": skill_tree}
    if not entries:
        finding.update(
            {
                "classification": "APP_PLACEHOLDER_EMPTY_DIR",
                "disposition": "ACCEPTED_NONBLOCKING",
                "operation": "retain",
                "status": "WARN",
                "reason": "Windows skills directory is empty and is treated as a harmless placeholder.",
            }
        )
        return finding

    mirror = classify_windows_skill_mirror(path, authority)
    finding["details"]["mirror"] = mirror
    if mirror.get("is_structural_mirror"):
        finding.update(
            {
                "classification": "stale_dev_workflow_skill_mirror",
                "disposition": "REMOVE_NOW",
                "operation": "remove",
                "status": "BLOCKED",
                "repo_owned": True,
                "reason": str(mirror.get("reason", "")),
            }
        )
        return finding

    if set(entries) == WINDOWS_SKILL_SYSTEM_ROOTS and not skill_tree["symlinks"]:
        finding.update(
            {
                "classification": "app_owned_system_skill_bundle",
                "disposition": "RETAIN_SAFE",
                "operation": "retain",
                "status": "PASS",
                "reason": "Windows skills surface contains the app-owned system skill bundle only.",
            }
        )
        return finding

    if skill_tree["symlinks"]:
        finding.update(
            {
                "classification": "policy_bearing_skill_surface",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": "Windows skills surface contains symlinks and requires manual review.",
            }
        )
        return finding
    if skill_tree["active_entries"] or skill_tree["unexpected_files"] or skill_tree["executable_markdown"]:
        finding.update(
            {
                "classification": "policy_bearing_skill_surface",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": "Windows skills surface contains executable payloads, manifests, or unsupported file types.",
            }
        )
        return finding

    text_reasons: list[str] = []
    for relative in skill_tree["files"]:
        child = path / relative
        if _allowed_skill_doc(child.name):
            text_reasons.extend(_skill_text_block_reasons(read_text(child)))
            if text_reasons:
                break
    if text_reasons:
        finding.update(
            {
                "classification": "policy_bearing_skill_surface",
                "disposition": "MANUAL_REMEDIATION",
                "operation": "retain",
                "status": "BLOCKED",
                "reason": text_reasons[0],
            }
        )
        return finding

    finding.update(
        {
            "classification": "user_managed_skill_surface",
            "disposition": "RETAIN_SAFE",
            "operation": "retain",
            "status": "PASS",
            "reason": "Windows skills surface contains user-managed markdown-only skill content with recorded provenance.",
        }
    )
    return finding


def classify_windows_policy_candidate(
    path: Path,
    authority: dict[str, Any],
    *,
    expected_linux_hooks: str | None = None,
) -> dict[str, Any]:
    if path.name == "config.toml":
        return _config_finding(path, authority, expected_linux_hooks=expected_linux_hooks)
    if path.name == "AGENTS.md":
        return _agents_finding(path, authority)
    if path.name == "hooks.json":
        return _hooks_finding(path, authority, expected_linux_hooks=expected_linux_hooks)
    return _skills_finding(path, authority)


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
    unknown_blocking: list[str] = []
    unknown_observed: list[str] = []

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
        if finding["operation"] == "remove":
            remove_now_candidates.append(str(path))
        if finding["repo_owned"] and finding["operation"] == "remove":
            known_generated_cleanup_candidates.append(str(path))
        if finding["status"] == "BLOCKED" and finding["operation"] != "remove":
            unknown_blocking.append(str(path))
        if finding["disposition"] == "MANUAL_REMEDIATION":
            manual_remediation_candidates.append(str(path))
        if finding["disposition"] == "ACCEPTED_NONBLOCKING":
            accepted_nonblocking_candidates.append(str(path))
        if finding["status"] != "PASS":
            unknown_observed.append(str(path))

    status = "PASS"
    if any(finding["status"] == "BLOCKED" for finding in findings):
        status = "BLOCKED"
    elif any(finding["status"] == "WARN" for finding in findings):
        status = "WARN"

    return {
        "status": status,
        "findings": findings,
        "known_generated_cleanup_candidates": sorted(set(known_generated_cleanup_candidates)),
        "remove_now_candidates": sorted(remove_now_candidates),
        "manual_remediation_candidates": sorted(set(manual_remediation_candidates)),
        "accepted_nonblocking_candidates": sorted(set(accepted_nonblocking_candidates)),
        "unknown_observed": sorted(set(unknown_observed)),
        "unknown_blocking": sorted(set(unknown_blocking)),
    }


def remove_directory_tree(path: Path) -> int:
    if not path_exists(path):
        return 0
    recycle_path(path)
    return 1
