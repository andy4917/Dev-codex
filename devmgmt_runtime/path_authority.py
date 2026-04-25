from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .reports import load_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH_POLICY_PATH = ROOT / "contracts" / "path_authority_policy.json"
DEFAULT_WORKSPACE_AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"

LEGACY_ROOT_ALIASES = {
    "management": "dev_management",
    "workflow": "dev_workflow",
    "product": "dev_product",
}
ROOT_ENV_VARS = {
    "dev_management": "DEVMGMT_ROOT",
    "dev_workflow": "DEV_WORKFLOW_ROOT",
    "dev_product": "DEV_PRODUCT_ROOT",
}
WINDOWS_POLICY_RELATIVE_PATHS = {
    "policy_config": Path("config.toml"),
    "agents": Path("AGENTS.md"),
    "hooks": Path("hooks.json"),
    "skills": Path("skills"),
}


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else path.resolve(strict=False)


def path_policy_path_for(repo_root: str | Path | None = None, *, policy_path: str | Path | None = None) -> Path:
    if policy_path is not None:
        return _resolve_path(policy_path)
    if repo_root is not None:
        candidate = _resolve_path(repo_root) / "contracts" / "path_authority_policy.json"
        if candidate.exists():
            return candidate
    return DEFAULT_PATH_POLICY_PATH


def workspace_authority_path_for(
    repo_root: str | Path | None = None,
    *,
    authority_path: str | Path | None = None,
) -> Path:
    if authority_path is not None:
        return _resolve_path(authority_path)
    if repo_root is not None:
        candidate = _resolve_path(repo_root) / "contracts" / "workspace_authority.json"
        if candidate.exists():
            return candidate
    return DEFAULT_WORKSPACE_AUTHORITY_PATH


def normalize_root_name(root_name: str) -> str:
    normalized = str(root_name or "").strip().lower()
    if not normalized:
        raise KeyError("root name is required")
    return LEGACY_ROOT_ALIASES.get(normalized, normalized)


def canonical_roots(policy: dict[str, Any]) -> dict[str, Path]:
    roots = policy.get("canonical_roots", {})
    if not isinstance(roots, dict):
        return {}
    return {
        str(name): _resolve_path(str(raw))
        for name, raw in roots.items()
        if str(name).strip() and str(raw).strip()
    }


def legacy_canonical_roots(policy: dict[str, Any]) -> dict[str, str]:
    roots = canonical_roots(policy)
    return {
        legacy: str(roots[canonical])
        for legacy, canonical in LEGACY_ROOT_ALIASES.items()
        if canonical in roots
    }


def runtime_paths(policy: dict[str, Any]) -> dict[str, Path]:
    payload = policy.get("runtime_paths", {})
    if not isinstance(payload, dict):
        return {}
    return {
        str(name): _resolve_path(str(raw))
        for name, raw in payload.items()
        if str(name).strip() and str(raw).strip()
    }


def forbidden_primary_paths(policy: dict[str, Any]) -> list[str]:
    return [str(item).strip() for item in policy.get("forbidden_primary_paths", []) if str(item).strip()]


def windows_codex_home(policy: dict[str, Any] | None = None, authority: dict[str, Any] | None = None) -> Path:
    policy = policy or {}
    authority = authority or {}
    runtime = runtime_paths(policy)
    if runtime.get("windows_codex_home"):
        return runtime["windows_codex_home"]
    windows_state = authority.get("windows_app_state", {}) if isinstance(authority.get("windows_app_state"), dict) else {}
    raw = str(windows_state.get("codex_home", "")).strip()
    if raw:
        return _resolve_path(raw)
    return (Path.home() / ".codex").resolve(strict=False)


def codex_user_home(policy: dict[str, Any] | None = None) -> Path:
    payload = runtime_paths(policy or {})
    if payload.get("codex_user_home"):
        return payload["codex_user_home"]
    return (Path.home() / ".codex").resolve(strict=False)


def linux_user_home(policy: dict[str, Any] | None = None) -> Path:
    return codex_user_home(policy).parent.resolve(strict=False)


def windows_user_home(policy: dict[str, Any] | None = None, authority: dict[str, Any] | None = None) -> Path:
    return windows_codex_home(policy, authority=authority).parent.resolve(strict=False)


def linux_home_prefix(policy: dict[str, Any] | None = None) -> Path:
    payload = policy or load_path_policy()
    roots = canonical_roots(payload)
    devmgmt_root = roots.get("dev_management")
    if devmgmt_root is not None:
        return devmgmt_root.parent.resolve(strict=False)
    return linux_user_home(payload)


def workflow_doc_path(policy: dict[str, Any] | None = None) -> Path:
    payload = policy or load_path_policy()
    roots = canonical_roots(payload)
    devmgmt_root = roots.get("dev_management")
    if devmgmt_root is None:
        devmgmt_root = get_devmgmt_root(payload)
    return (devmgmt_root / "docs" / "GLOBAL_AGENT_WORKFLOW.md").resolve(strict=False)


def windows_ssh_config_path(policy: dict[str, Any] | None = None, authority: dict[str, Any] | None = None) -> Path:
    raise RuntimeError(r"C:\Users\anise\.ssh is decommissioned in the Windows-native runtime model")


def linux_ssh_config_path(policy: dict[str, Any] | None = None) -> Path:
    raise RuntimeError("Linux SSH config paths are decommissioned in the Windows-native runtime model")


def linux_ssh_managed_config_path(policy: dict[str, Any] | None = None) -> Path:
    raise RuntimeError("Linux managed SSH config paths are decommissioned in the Windows-native runtime model")


def get_codex_cli_bin(policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    payload = policy or load_path_policy()
    runtime = runtime_paths(payload)
    expected = runtime.get("codex_cli_bin")
    if expected is None:
        raise KeyError("path authority is missing runtime_paths.codex_cli_bin")
    env_value = (env or os.environ).get("CODEX_CLI_BIN", "").strip()
    if env_value:
        resolved = _resolve_path(env_value)
        if resolved != expected:
            raise ValueError(f"CODEX_CLI_BIN diverges from path authority: {resolved} != {expected}")
        return resolved
    return expected


def env_export_view(policy: dict[str, Any] | None = None) -> dict[str, str]:
    payload = policy or load_path_policy()
    roots = canonical_roots(payload)
    runtime = runtime_paths(payload)
    return {
        "DEVMGMT_ROOT": str(roots.get("dev_management", "")),
        "DEV_WORKFLOW_ROOT": str(roots.get("dev_workflow", "")),
        "DEV_PRODUCT_ROOT": str(roots.get("dev_product", "")),
        "CANONICAL_EXECUTION_HOST": str(payload.get("canonical_execution_host", "")),
        "CODEX_CLI_BIN": str(runtime.get("codex_cli_bin", "")),
        "CODEX_HOME": str(runtime.get("windows_codex_home", runtime.get("codex_user_home", ""))),
    }


def validate_env_alignment(policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    payload = policy or load_path_policy()
    expected = env_export_view(payload)
    env_map = env or os.environ
    findings: list[dict[str, str]] = []
    ordered_env_vars = list(dict.fromkeys([*payload.get("allowed_env_vars", []), "CANONICAL_EXECUTION_HOST", "CODEX_CLI_BIN"]))
    for name in ordered_env_vars:
        if name not in expected:
            continue
        actual = str(env_map.get(name, "")).strip()
        if not actual:
            findings.append({"env_var": name, "status": "ABSENT", "expected": expected[name], "actual": ""})
            continue
        if name == "CANONICAL_EXECUTION_HOST":
            matches = actual == expected[name]
            normalized_actual = actual
        else:
            normalized_actual = str(_resolve_path(actual))
            matches = normalized_actual == expected[name]
        findings.append(
            {
                "env_var": name,
                "status": "MATCH" if matches else "MISMATCH",
                "expected": expected[name],
                "actual": normalized_actual,
            }
        )
    status = "BLOCKED" if any(item["status"] == "MISMATCH" for item in findings) else "PASS"
    return {
        "status": status,
        "findings": findings,
        "expected": expected,
        "allowed_env_vars": list(payload.get("allowed_env_vars", [])),
    }


def get_root_path(root_name: str, policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    payload = policy or load_path_policy()
    normalized_name = normalize_root_name(root_name)
    roots = canonical_roots(payload)
    if normalized_name not in roots:
        raise KeyError(f"unknown canonical root: {root_name}")
    expected = roots[normalized_name]
    env_var = ROOT_ENV_VARS.get(normalized_name)
    env_value = (env or os.environ).get(env_var, "").strip() if env_var else ""
    if env_value:
        resolved = _resolve_path(env_value)
        if resolved != expected:
            raise ValueError(f"{env_var} diverges from path authority: {resolved} != {expected}")
        return resolved
    return expected


def get_devmgmt_root(policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    return get_root_path("dev_management", policy=policy, env=env)


def get_dev_workflow_root(policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    return get_root_path("dev_workflow", policy=policy, env=env)


def get_dev_product_root(policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    return get_root_path("dev_product", policy=policy, env=env)


def _workspace_authority_mirror(policy: dict[str, Any]) -> dict[str, Any]:
    roots = legacy_canonical_roots(policy)
    management_root = roots.get("management", "")
    host_alias = str(policy.get("canonical_execution_host", "")).strip()
    forbidden = forbidden_primary_paths(policy)
    forbidden_primary = next((item for item in forbidden if item.endswith("/codex")), "")
    return {
        "canonical_roots": roots,
        "forbidden_primary_runtime_paths": forbidden,
        "canonical_execution_surface": {
            "host_alias": host_alias,
            "repo_root": management_root,
            "forbidden_primary_resolution": forbidden_primary,
        },
        "canonical_remote_execution_surface": {
            "host_alias": host_alias,
            "repo_root": management_root,
            "forbidden_primary_resolution": forbidden_primary,
        },
    }


def compare_workspace_authority(policy: dict[str, Any], authority: dict[str, Any]) -> list[str]:
    if not isinstance(authority, dict) or not authority:
        return []
    mirror = _workspace_authority_mirror(policy)
    mismatches: list[str] = []
    authority_roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    for name, expected in mirror["canonical_roots"].items():
        actual = str(authority_roots.get(name, "")).strip()
        if actual and _resolve_path(actual) != _resolve_path(expected):
            mismatches.append(f"workspace_authority canonical_roots.{name} diverges from path authority")
    actual_forbidden = [str(item).strip() for item in authority.get("forbidden_primary_runtime_paths", []) if str(item).strip()]
    if actual_forbidden and actual_forbidden != mirror["forbidden_primary_runtime_paths"]:
        mismatches.append("workspace_authority forbidden_primary_runtime_paths diverges from path authority")
    for surface_key in ("canonical_execution_surface", "canonical_remote_execution_surface"):
        expected_surface = mirror[surface_key]
        actual_surface = authority.get(surface_key, {}) if isinstance(authority.get(surface_key), dict) else {}
        for field in ("host_alias", "repo_root", "forbidden_primary_resolution"):
            actual = str(actual_surface.get(field, "")).strip()
            expected = str(expected_surface.get(field, "")).strip()
            if actual and expected:
                if field == "repo_root":
                    matches = _resolve_path(actual) == _resolve_path(expected)
                else:
                    matches = actual == expected
                if not matches:
                    mismatches.append(f"workspace_authority {surface_key}.{field} diverges from path authority")
    return mismatches


def apply_path_policy_compatibility(authority: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    payload = dict(authority)
    mirror = _workspace_authority_mirror(policy)
    payload["canonical_roots"] = mirror["canonical_roots"]
    payload["forbidden_primary_runtime_paths"] = mirror["forbidden_primary_runtime_paths"]
    for surface_key in ("canonical_execution_surface", "canonical_remote_execution_surface"):
        surface = payload.get(surface_key, {})
        if not isinstance(surface, dict):
            surface = {}
        payload[surface_key] = {
            **surface,
            **mirror[surface_key],
        }
    payload.setdefault("module_registry", {})
    if isinstance(payload["module_registry"], dict):
        payload["module_registry"].setdefault(
            "path_authority_policy",
            {
                "path": str(path_policy_path_for(policy_path=policy.get("_path_policy_path"))),
                "kind": "standalone_contract",
                "final_authority": True,
                "compatibility_mode": "dual-read",
            },
        )
    return payload


def load_path_policy(
    repo_root: str | Path | None = None,
    *,
    policy_path: str | Path | None = None,
    workspace_authority: dict[str, Any] | None = None,
    authority_path: str | Path | None = None,
) -> dict[str, Any]:
    policy_file = path_policy_path_for(repo_root, policy_path=policy_path)
    payload = load_json(policy_file, default={})
    policy = payload if isinstance(payload, dict) else {}
    policy["_path_policy_path"] = str(policy_file)
    if workspace_authority is not None:
        authority = workspace_authority
    else:
        authority_file = workspace_authority_path_for(repo_root, authority_path=authority_path)
        authority_payload = load_json(authority_file, default={})
        authority = authority_payload if isinstance(authority_payload, dict) else {}
    mismatches = compare_workspace_authority(policy, authority)
    if mismatches:
        raise ValueError("; ".join(mismatches))
    return policy


def classify_path(
    path: Path | str,
    policy: dict[str, Any] | None = None,
    *,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = policy or load_path_policy(workspace_authority=authority)
    resolved = _resolve_path(str(path))
    roots = canonical_roots(payload)
    runtime = runtime_paths(payload)
    windows_home = windows_codex_home(payload, authority=authority)
    forbidden = [path_text.replace("\\", "/").lower() for path_text in forbidden_primary_paths(payload)]

    normalized = str(resolved).replace("\\", "/").lower()
    for item in forbidden:
        if item and (normalized == item or normalized.startswith(item + "/")):
            return {"path": str(resolved), "classification": "forbidden_primary_path", "status": "BLOCKED"}

    for name, root in roots.items():
        try:
            resolved.relative_to(root)
            return {"path": str(resolved), "classification": f"canonical_root:{name}", "status": "PASS"}
        except ValueError:
            continue

    for name, runtime_path in runtime.items():
        if resolved == runtime_path:
            return {"path": str(resolved), "classification": f"runtime_path:{name}", "status": "PASS"}

    try:
        relative = resolved.relative_to(windows_home)
    except ValueError:
        relative = None
    if relative is not None:
        surface_map = payload.get("windows_surfaces", {}) if isinstance(payload.get("windows_surfaces"), dict) else {}
        if relative == Path("."):
            return {
                "path": str(resolved),
                "classification": "windows_codex_home",
                "surface": "codex_home",
                "surface_status": str(surface_map.get("codex_home", "app_state_only")),
                "status": "WARN",
            }
        for surface, relative_path in WINDOWS_POLICY_RELATIVE_PATHS.items():
            if relative == relative_path or str(relative).startswith(str(relative_path) + "/"):
                return {
                    "path": str(resolved),
                    "classification": "windows_policy_surface",
                    "surface": surface,
                    "surface_status": str(surface_map.get(surface, "forbidden")),
                    "status": "BLOCKED" if str(surface_map.get(surface, "forbidden")) == "forbidden" else "WARN",
                }
        return {
            "path": str(resolved),
            "classification": "windows_codex_state",
            "surface": "codex_home",
            "surface_status": str(surface_map.get("codex_home", "app_state_only")),
            "status": "WARN",
        }
    return {"path": str(resolved), "classification": "unclassified", "status": "WARN"}


def assert_not_forbidden_path(path: Path | str, policy: dict[str, Any] | None = None) -> None:
    result = classify_path(path, policy=policy)
    if result.get("status") == "BLOCKED":
        raise ValueError(f"forbidden path usage detected: {result['path']} ({result['classification']})")


def resolve_under(root_name: str, *parts: str, policy: dict[str, Any] | None = None, env: dict[str, str] | None = None) -> Path:
    base = get_root_path(root_name, policy=policy, env=env)
    for part in parts:
        if Path(part).is_absolute():
            raise ValueError(f"absolute path segment is not allowed: {part}")
    candidate = base.joinpath(*parts).resolve(strict=False)
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escape outside canonical root '{root_name}': {candidate}") from exc
    assert_not_forbidden_path(candidate, policy=policy)
    return candidate
