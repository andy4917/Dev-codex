from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
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
DEFAULT_AUTHORITY_FILE = CONTRACTS / "workspace_authority.json"
DEFAULT_REVIEW_FILE = REPORTS / "user-scorecard.review.json"
DEFAULT_SCORECARD_FILE = REPORTS / "user-scorecard.json"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME", "").strip()
    if override:
        candidate = Path(override).expanduser()
        in_wsl = "microsoft" in platform.release().lower() or Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
        candidate_text = str(candidate).replace("\\", "/").lower()
        if not (in_wsl and candidate_text.startswith("/mnt/") and candidate.name == ".codex"):
            return candidate.resolve()
    authority: dict[str, Any] = {}
    if DEFAULT_AUTHORITY_FILE.exists():
        try:
            with DEFAULT_AUTHORITY_FILE.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                authority = loaded
        except (OSError, json.JSONDecodeError):
            authority = {}
    runtime = authority.get("generation_targets", {}).get("global_runtime", {}) if isinstance(authority, dict) else {}
    linux_agents = str(runtime.get("linux", {}).get("agents", "")).strip()
    if linux_agents:
        return Path(linux_agents).expanduser().resolve().parent
    scorecard = authority.get("generation_targets", {}).get("scorecard", {}) if isinstance(authority, dict) else {}
    lease_root = str(scorecard.get("workspace_authority_root", "")).strip()
    if lease_root:
        return Path(lease_root).expanduser().resolve().parent
    return (Path.home() / ".codex").resolve()


def state_root() -> Path:
    return codex_home() / "state"


DEFAULT_RUNTIME_AGENTS = codex_home() / "AGENTS.md"


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_authority(path: Path | None = None) -> dict[str, Any]:
    payload = load_json(path or DEFAULT_AUTHORITY_FILE, default={})
    return payload if isinstance(payload, dict) else {}


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


def default_user_review() -> dict[str, Any]:
    return {
        "status": "PENDING",
        "awards": [],
        "penalties": [],
        "notes": "",
    }


def normalize_user_review(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    return {
        "status": normalize_status(source.get("status"), "PENDING"),
        "awards": list(source.get("awards", [])),
        "penalties": list(source.get("penalties", [])),
        "notes": str(source.get("notes", "")).strip(),
    }


def user_review_update_authorized(payload: dict[str, Any] | None) -> bool:
    source = payload if isinstance(payload, dict) else {}
    candidates: list[dict[str, Any]] = [source]
    nested = source.get("user_review")
    if isinstance(nested, dict):
        candidates.append(nested)
    for candidate in candidates:
        if bool(candidate.get("user_review_update_authorized", False)) or bool(candidate.get("update_authorized", False)):
            return True
        if bool(candidate.get("user_review_approved", False)):
            return True
        for key in ("user_review_update_request", "user_review_request_id", "task_request_id", "request_id"):
            if str(candidate.get(key, "")).strip():
                return True
    return False


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


def stable_sequence_hash(items: list[str]) -> str:
    normalized = [str(item).strip() for item in items if str(item).strip()]
    return stable_json_hash(sorted(set(normalized)))


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


def git_output(repo_root: Path, *args: str) -> str:
    return _run_git(repo_root, *args)


def git_lines(repo_root: Path, *args: str) -> list[str]:
    output = git_output(repo_root, *args)
    if not output:
        return []
    return [line for line in output.splitlines() if line.strip()]


def git_sha(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "HEAD") or "nogit"


def worktree_id(repo_root: Path) -> str:
    return _run_git(repo_root, "rev-parse", "--show-toplevel") or str(repo_root.resolve())


def project_id(repo_root: Path) -> str:
    return repo_root.resolve().name


def workspace_git_root(repo_root: Path) -> Path:
    output = _run_git(repo_root, "rev-parse", "--show-toplevel")
    if output:
        return Path(output).expanduser().resolve()
    return repo_root.resolve()


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


def signature_valid(payload: dict[str, Any]) -> bool:
    signature = str(payload.get("signature", "")).strip()
    return bool(signature) and verify_truth_signature(strip_signature(payload), signature)


def fresh_evidence_manifest_path(workspace_root: Path) -> Path:
    return workspace_root / "reports" / "authority" / "fresh-evidence.json"


def load_fresh_evidence_manifest(workspace_root: Path) -> dict[str, Any]:
    return load_json(fresh_evidence_manifest_path(workspace_root))


def agent_runs_root(workspace_root: Path) -> Path:
    return workspace_root / ".agent-runs"


def latest_agent_run_file(workspace_root: Path, filename: str, run_id: str = "") -> Path | None:
    root = agent_runs_root(workspace_root)
    if not root.exists():
        return None
    normalized_run_id = str(run_id).strip()
    if normalized_run_id:
        return root / normalized_run_id / filename
    candidates = sorted(path for path in root.glob(f"*/{filename}") if path.is_file())
    if not candidates:
        return None
    return candidates[-1]


def published_evidence_manifest_path(workspace_root: Path, run_id: str = "") -> Path:
    return latest_agent_run_file(workspace_root, "EVIDENCE_MANIFEST.json", run_id=run_id) or fresh_evidence_manifest_path(workspace_root)


def load_published_evidence_manifest(workspace_root: Path, run_id: str = "") -> dict[str, Any]:
    return load_json(published_evidence_manifest_path(workspace_root, run_id=run_id))


def published_run_artifact_path(
    workspace_root: Path,
    filename: str,
    evidence_manifest_path: Path | None = None,
    run_id: str = "",
) -> Path | None:
    if evidence_manifest_path is not None and evidence_manifest_path.name == "EVIDENCE_MANIFEST.json":
        candidate = evidence_manifest_path.parent / filename
        if candidate.exists():
            return candidate
    return latest_agent_run_file(workspace_root, filename, run_id=run_id)


def published_workorder_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "WORKORDER.json", evidence_manifest_path, run_id=run_id)


def published_command_log_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "COMMAND_LOG.jsonl", evidence_manifest_path, run_id=run_id)


def published_waivers_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "WAIVERS.json", evidence_manifest_path, run_id=run_id)


def published_task_tree_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "TASK_TREE.json", evidence_manifest_path, run_id=run_id)


def published_repeated_verify_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "REPEATED_VERIFY.json", evidence_manifest_path, run_id=run_id)


def published_cross_verification_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "CROSS_VERIFICATION.json", evidence_manifest_path, run_id=run_id)


def published_claim_ledger_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "CLAIM_LEDGER.json", evidence_manifest_path, run_id=run_id)


def published_summary_coverage_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "SUMMARY_COVERAGE.json", evidence_manifest_path, run_id=run_id)


def published_convention_lock_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "CONVENTION_LOCK.json", evidence_manifest_path, run_id=run_id)


def published_taste_gate_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "TASTE_GATE.json", evidence_manifest_path, run_id=run_id)


def published_gate_receipt_path(workspace_root: Path, evidence_manifest_path: Path | None = None, run_id: str = "") -> Path | None:
    return published_run_artifact_path(workspace_root, "gate_receipt.json", evidence_manifest_path, run_id=run_id)


def current_policy_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in (DEFAULT_POLICY_FILE, DEFAULT_DISQUALIFIER_FILE):
        if path.exists():
            hashes[path.name] = file_hash(path)
    return hashes


def fresh_trace_id(workspace_root: Path) -> str:
    manifest = load_fresh_evidence_manifest(workspace_root)
    return str(manifest.get("trace_id", "")).strip()


def scorecard_context_path(workspace_root: Path, trace_id: str) -> Path:
    return state_root() / "scorecard-context" / project_id(workspace_root) / f"{trace_id}.json"


def reviewer_verdict_dir(workspace_root: Path, trace_id: str) -> Path:
    return state_root() / "reviewer-verdicts" / project_id(workspace_root) / trace_id


def workspace_authority_lease_root(authority: dict[str, Any] | None = None) -> Path:
    scorecard = scorecard_targets(authority)
    raw = str(scorecard.get("workspace_authority_root", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return state_root() / "workspace-authority"


def workspace_authority_lease_path(workspace_root: Path, authority: dict[str, Any] | None = None) -> Path:
    return workspace_authority_lease_root(authority) / f"{project_id(workspace_root)}.json"


def workspace_authority_path(workspace_root: Path) -> Path:
    return workspace_authority_lease_path(workspace_root)


def validate_workspace_authority_lease(
    workspace_root: Path,
    *,
    required: bool,
    lease_path: Path | None = None,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_path = (lease_path or workspace_authority_lease_path(workspace_root, authority)).expanduser().resolve()
    if not required:
        return {"ok": True, "reasons": [], "lease": {}, "path": str(resolved_path)}
    if not resolved_path.exists():
        return {"ok": False, "reasons": ["workspace authority lease is missing"], "lease": {}, "path": str(resolved_path)}
    lease = load_json(resolved_path, default={})
    if not isinstance(lease, dict) or not signature_valid(lease):
        return {"ok": False, "reasons": ["workspace authority lease signature is invalid"], "lease": lease, "path": str(resolved_path)}
    reasons: list[str] = []
    resolved_root = workspace_root.resolve()
    if str(lease.get("workspace_root", "")).strip() != str(resolved_root):
        reasons.append("workspace authority workspace_root mismatch")
    if str(lease.get("git_sha", "")).strip() != git_sha(resolved_root):
        reasons.append("workspace authority git_sha mismatch")
    if str(lease.get("worktree_id", "")).strip() != worktree_id(resolved_root):
        reasons.append("workspace authority worktree_id mismatch")
    if str(lease.get("codex_project_id", "")).strip() != project_id(resolved_root):
        reasons.append("workspace authority codex_project_id mismatch")
    expires_at = str(lease.get("expires_at", "")).strip()
    if not expires_at:
        reasons.append("workspace authority expires_at is missing")
    else:
        try:
            if datetime.fromisoformat(expires_at).astimezone(timezone.utc) <= datetime.now(timezone.utc):
                reasons.append("workspace authority lease is expired")
        except ValueError:
            reasons.append("workspace authority expires_at is invalid")
    return {"ok": not reasons, "reasons": reasons, "lease": lease, "path": str(resolved_path)}


def scorecard_targets(authority: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = authority if isinstance(authority, dict) else load_authority()
    return payload.get("generation_targets", {}).get("scorecard", {})


def gate_receipts_root(authority: dict[str, Any] | None = None) -> Path:
    scorecard = scorecard_targets(authority)
    raw = str(scorecard.get("gate_receipt_root", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return state_root() / "gate-receipts"


def gate_receipt_state_path(workspace_root: Path, run_id: str, authority: dict[str, Any] | None = None) -> Path:
    return gate_receipts_root(authority) / project_id(workspace_root) / f"{run_id}.json"


def gate_receipt_mirror_path(workspace_root: Path, run_id: str) -> Path:
    return agent_runs_root(workspace_root) / run_id / "gate_receipt.json"
