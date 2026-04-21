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


def module_registry(authority: dict[str, Any]) -> dict[str, Any]:
    payload = authority.get("module_registry", {})
    return payload if isinstance(payload, dict) else {}


def module_contract(authority: dict[str, Any], module_name: str) -> dict[str, Any]:
    payload = module_registry(authority).get(module_name, {})
    return payload if isinstance(payload, dict) else {}

