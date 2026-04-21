from __future__ import annotations

from pathlib import Path
from typing import Any

from .reports import load_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"


def authority_path_for(repo_root: str | Path | None = None, *, authority_path: str | Path | None = None) -> Path:
    if authority_path is not None:
        return Path(authority_path).expanduser().resolve()
    if repo_root is not None:
        candidate = Path(repo_root).expanduser().resolve() / "contracts" / "workspace_authority.json"
        if candidate.exists():
            return candidate
    return DEFAULT_AUTHORITY_PATH


def load_authority(repo_root: str | Path | None = None, *, authority_path: str | Path | None = None) -> dict[str, Any]:
    payload = load_json(authority_path_for(repo_root, authority_path=authority_path), default={})
    return payload if isinstance(payload, dict) else {}


def canonical_repo_root(authority: dict[str, Any], fallback_repo_root: str | Path | None = None) -> Path:
    roots = authority.get("canonical_roots", {}) if isinstance(authority.get("canonical_roots"), dict) else {}
    candidates = [
        authority.get("authority_root"),
        roots.get("management"),
        authority.get("canonical_remote_execution_surface", {}).get("repo_root") if isinstance(authority.get("canonical_remote_execution_surface"), dict) else None,
        authority.get("canonical_execution_surface", {}).get("repo_root") if isinstance(authority.get("canonical_execution_surface"), dict) else None,
        fallback_repo_root,
        DEFAULT_AUTHORITY_PATH.parents[1],
    ]
    for candidate in candidates:
        if not candidate:
            continue
        return Path(str(candidate)).expanduser().resolve()
    return DEFAULT_AUTHORITY_PATH.parents[1]


def canonical_authority_path(authority: dict[str, Any], fallback_repo_root: str | Path | None = None) -> Path:
    return canonical_repo_root(authority, fallback_repo_root) / "contracts" / "workspace_authority.json"


def module_registry(authority: dict[str, Any]) -> dict[str, Any]:
    payload = authority.get("module_registry", {})
    return payload if isinstance(payload, dict) else {}


def module_contract(authority: dict[str, Any], module_name: str) -> dict[str, Any]:
    payload = module_registry(authority).get(module_name, {})
    return payload if isinstance(payload, dict) else {}
