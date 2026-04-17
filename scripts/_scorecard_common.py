from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REPORTS = ROOT / "reports"
DEFAULT_POLICY_FILE = CONTRACTS / "user_score_policy.json"
DEFAULT_DISQUALIFIER_FILE = CONTRACTS / "disqualifier_policy.json"
DEFAULT_REVIEW_FILE = REPORTS / "user-scorecard.review.json"
DEFAULT_SCORECARD_FILE = REPORTS / "user-scorecard.json"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def state_root() -> Path:
    return codex_home() / "state"


DEFAULT_RUNTIME_AGENTS = codex_home() / "AGENTS.md"


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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            items.append(json.loads(text))
    return items


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_path(raw: str | None, base: Path | None = None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    return (base or ROOT).joinpath(path).resolve()


def normalize_status(value: object, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def merge_unique(existing: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for item in [*existing, *incoming]:
        token = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if token in seen:
            continue
        seen.add(token)
        merged.append(item)
    return merged


def status_exit_code(status: str) -> int:
    normalized = normalize_status(status)
    if normalized in {"PASS", "WAIVED"}:
        return 0
    if normalized == "BLOCKED":
        return 2
    return 1


def stable_json_hash(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_sha(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "HEAD") or "nogit"


def worktree_id(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "--show-toplevel") or str(repo_root.resolve())


def project_id(repo_root: Path) -> str:
    return repo_root.resolve().name


def truth_secret_path() -> Path:
    return state_root() / "truth-hmac.key"


def truth_secret() -> bytes:
    path = truth_secret_path()
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32).encode("utf-8")
    path.write_bytes(secret)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def truth_signature(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(truth_secret(), serialized.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_truth_signature(payload: dict[str, Any], signature: str) -> bool:
    expected = truth_signature(payload)
    return hmac.compare_digest(expected, str(signature or ""))


def signed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    data["signature"] = truth_signature(data)
    return data


def strip_signature(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "signature"}


def fresh_evidence_manifest_path(workspace_root: Path) -> Path:
    return workspace_root / "reports" / "authority" / "fresh-evidence.json"


def load_fresh_evidence_manifest(workspace_root: Path) -> dict[str, Any]:
    return load_json(fresh_evidence_manifest_path(workspace_root))


def fresh_trace_id(workspace_root: Path) -> str:
    manifest = load_fresh_evidence_manifest(workspace_root)
    return str(manifest.get("trace_id", "")).strip()


def scorecard_context_path(workspace_root: Path, trace_id: str) -> Path:
    return state_root() / "scorecard-context" / project_id(workspace_root) / f"{trace_id}.json"


def reviewer_verdict_dir(workspace_root: Path, trace_id: str) -> Path:
    return state_root() / "reviewer-verdicts" / project_id(workspace_root) / trace_id


def workspace_authority_path(workspace_root: Path) -> Path:
    return state_root() / "workspace-authority" / f"{project_id(workspace_root)}.json"
