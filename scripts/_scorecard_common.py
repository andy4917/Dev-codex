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
GATE_RECEIPT_SIGNATURE_POLICY = {
    "policy_id": "scorecard-gate-receipt-v1.3",
    "algorithm": "hmac-sha256",
    "authority_layer": "signed_gate_receipt",
    "state_root_required": True,
    "workspace_identity_required": True,
    "project_identity_required": True,
    "changed_file_hash_required": True,
    "release_profile": "L4",
}


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


def atomic_save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


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


def _legacy_gate_receipts_root(authority: dict[str, Any] | None = None) -> Path | None:
    scorecard = scorecard_targets(authority)
    raw = str(scorecard.get("gate_receipt_root", "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def resolve_iaw_state_home(authority: dict[str, Any] | None = None) -> Path:
    override = os.environ.get("IAW_STATE_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    scorecard = scorecard_targets(authority)
    raw = str(scorecard.get("receipt_state_root", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    legacy_root = _legacy_gate_receipts_root(authority)
    if legacy_root is not None:
        return legacy_root.parent
    return state_root() / "iaw"


def truth_secret_path(authority: dict[str, Any] | None = None) -> Path:
    return resolve_iaw_state_home(authority) / "truth-hmac.key"


def _truth_secret_candidate_paths(authority: dict[str, Any] | None = None) -> list[Path]:
    preferred = truth_secret_path(authority)
    legacy = state_root() / "truth-hmac.key"
    ordered: list[Path] = []
    for path in (preferred, legacy):
        resolved = path.expanduser().resolve()
        if resolved not in ordered:
            ordered.append(resolved)
    return ordered


def truth_secret(authority: dict[str, Any] | None = None, *, create: bool = True) -> bytes | None:
    for path in _truth_secret_candidate_paths(authority):
        if path.exists():
            return path.read_bytes()
    if not create:
        return None
    path = truth_secret_path(authority)
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32).encode("utf-8")
    path.write_bytes(secret)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def truth_signature(payload: dict[str, Any], authority: dict[str, Any] | None = None, *, create: bool = True) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    secret = truth_secret(authority, create=create)
    if secret is None:
        raise FileNotFoundError(f"truth-hmac.key is missing: {truth_secret_path(authority)}")
    return hmac.new(secret, serialized.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_truth_signature(payload: dict[str, Any], signature: str, authority: dict[str, Any] | None = None) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    provided = str(signature or "")
    if not provided:
        return False
    for path in _truth_secret_candidate_paths(authority):
        if not path.exists():
            continue
        expected = hmac.new(path.read_bytes(), serialized, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, provided):
            return True
    return False


def signed_payload(payload: dict[str, Any], authority: dict[str, Any] | None = None, *, create: bool = True) -> dict[str, Any]:
    data = dict(payload)
    data["signature"] = truth_signature(data, authority, create=create)
    return data


def strip_signature(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "signature"}


def signature_valid(payload: dict[str, Any], authority: dict[str, Any] | None = None) -> bool:
    signature = str(payload.get("signature", "")).strip()
    return bool(signature) and verify_truth_signature(strip_signature(payload), signature, authority)


def gate_receipt_signature_policy() -> dict[str, Any]:
    return dict(GATE_RECEIPT_SIGNATURE_POLICY)


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
    if os.environ.get("IAW_STATE_HOME", "").strip():
        return resolve_iaw_state_home(authority) / "gate-receipts"
    scorecard = scorecard_targets(authority)
    if str(scorecard.get("receipt_state_root", "")).strip():
        return resolve_iaw_state_home(authority) / "gate-receipts"
    legacy_root = _legacy_gate_receipts_root(authority)
    if legacy_root is not None:
        return legacy_root
    return resolve_iaw_state_home(authority) / "gate-receipts"


def gate_receipt_state_path(workspace_root: Path, run_id: str, authority: dict[str, Any] | None = None) -> Path:
    return gate_receipts_root(authority) / project_id(workspace_root) / f"{run_id}.json"


def gate_receipt_mirror_path(workspace_root: Path, run_id: str) -> Path:
    return agent_runs_root(workspace_root) / run_id / "gate_receipt.json"


def gate_receipt_lock_path(workspace_root: Path, run_id: str, authority: dict[str, Any] | None = None) -> Path:
    return resolve_iaw_state_home(authority) / "locks" / project_id(workspace_root) / f"{run_id}.lock"


def _project_id_collision_warnings(expected_state_root: Path, resolved_workspace: Path | None) -> list[str]:
    if not isinstance(resolved_workspace, Path):
        return []
    project_root = expected_state_root / project_id(resolved_workspace)
    if not project_root.exists():
        return []
    other_roots: set[str] = set()
    for path in project_root.glob("*.json"):
        receipt = load_json(path, default={})
        if not isinstance(receipt, dict):
            continue
        candidate = str(receipt.get("workspace_root_realpath", "")).strip()
        if candidate and candidate != str(resolved_workspace):
            other_roots.add(candidate)
    if not other_roots:
        return []
    return [
        "codex_project_id collision warning: "
        + ", ".join(sorted(other_roots))
    ]


def validate_gate_receipt(
    receipt: dict[str, Any],
    *,
    receipt_path: Path | None = None,
    authority: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    if not isinstance(receipt, dict) or not receipt:
        return {"ok": False, "reasons": ["gate receipt is missing"], "warnings": [], "state_path": "", "state_root": ""}

    reasons: list[str] = []
    warnings: list[str] = []
    if not signature_valid(receipt, authority):
        reasons.append("gate receipt signature is invalid")

    try:
        schema_version = int(receipt.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0
    if schema_version < 2:
        reasons.append("gate receipt schema_version is unsupported")

    if receipt.get("authoritative") is not True:
        reasons.append("gate receipt is not authoritative")

    signature_policy = receipt.get("signature_policy", {})
    expected_policy = gate_receipt_signature_policy()
    if not isinstance(signature_policy, dict):
        reasons.append("gate receipt signature_policy is missing")
    else:
        for key, expected_value in expected_policy.items():
            if signature_policy.get(key) != expected_value:
                reasons.append(f"gate receipt signature_policy {key} mismatch")

    resolved_workspace = workspace_root.resolve() if isinstance(workspace_root, Path) else None
    if resolved_workspace is None:
        resolved_workspace = resolve_path(str(receipt.get("workspace_root_realpath", "")))
    resolved_run_id = str(run_id).strip() or str(receipt.get("run_id", "")).strip()
    expected_state_root = gate_receipts_root(authority)
    expected_state_path = (
        gate_receipt_state_path(resolved_workspace, resolved_run_id, authority)
        if isinstance(resolved_workspace, Path) and resolved_run_id
        else None
    )
    warnings.extend(_project_id_collision_warnings(expected_state_root, resolved_workspace))

    authority_layer = receipt.get("authority_layer", {})
    if not isinstance(authority_layer, dict):
        reasons.append("gate receipt authority_layer is missing")
    else:
        if str(authority_layer.get("kind", "")).strip() != "signed_gate_receipt":
            reasons.append("gate receipt authority_layer kind mismatch")
        if str(authority_layer.get("state_root", "")).strip() != str(expected_state_root):
            reasons.append("gate receipt authority state_root mismatch")
        if expected_state_path is not None and str(authority_layer.get("state_path", "")).strip() != str(expected_state_path):
            reasons.append("gate receipt authority state_path mismatch")
        if not str(authority_layer.get("mirror_path", "")).strip():
            reasons.append("gate receipt authority mirror_path is missing")

    if receipt_path is not None and expected_state_path is not None and receipt_path.expanduser().resolve() != expected_state_path:
        reasons.append("gate receipt must be loaded from the authoritative state root")

    workspace_identity = receipt.get("workspace_identity", {})
    if not isinstance(workspace_identity, dict):
        reasons.append("gate receipt workspace_identity is missing")
    elif isinstance(resolved_workspace, Path):
        if str(workspace_identity.get("workspace_root_realpath", "")).strip() != str(resolved_workspace):
            reasons.append("gate receipt workspace_root_realpath mismatch")
        if str(workspace_identity.get("git_root", "")).strip() != str(workspace_git_root(resolved_workspace)):
            reasons.append("gate receipt git_root mismatch")
        if str(workspace_identity.get("codex_project_id", "")).strip() != project_id(resolved_workspace):
            reasons.append("gate receipt codex_project_id mismatch")
        if str(workspace_identity.get("worktree_id", "")).strip() != worktree_id(resolved_workspace):
            reasons.append("gate receipt worktree_id mismatch")

    if isinstance(workspace_identity, dict):
        if str(receipt.get("workspace_root_realpath", "")).strip() != str(workspace_identity.get("workspace_root_realpath", "")).strip():
            reasons.append("gate receipt top-level workspace_root_realpath mismatch")
        if str(receipt.get("git_root", "")).strip() != str(workspace_identity.get("git_root", "")).strip():
            reasons.append("gate receipt top-level git_root mismatch")
        if str(receipt.get("codex_project_id", "")).strip() != str(workspace_identity.get("codex_project_id", "")).strip():
            reasons.append("gate receipt top-level codex_project_id mismatch")
        if str(receipt.get("worktree_id", "")).strip() != str(workspace_identity.get("worktree_id", "")).strip():
            reasons.append("gate receipt top-level worktree_id mismatch")

    evidence_binding = receipt.get("evidence_binding", {})
    if not isinstance(evidence_binding, dict):
        reasons.append("gate receipt evidence_binding is missing")
    else:
        if not str(evidence_binding.get("changed_file_set_hash", "")).strip():
            reasons.append("gate receipt changed_file_set_hash is missing")
        if not str(evidence_binding.get("changed_file_content_hash", "")).strip():
            reasons.append("gate receipt changed_file_content_hash is missing")
        if not str(evidence_binding.get("evidence_manifest_hash", "")).strip():
            reasons.append("gate receipt evidence_manifest_hash is missing")
        if not isinstance(evidence_binding.get("policy_hashes", {}), dict):
            reasons.append("gate receipt policy_hashes are missing")
        if not isinstance(evidence_binding.get("script_hashes", {}), dict):
            reasons.append("gate receipt script_hashes are missing")
        if str(receipt.get("changed_file_set_hash", "")).strip() != str(evidence_binding.get("changed_file_set_hash", "")).strip():
            reasons.append("gate receipt top-level changed_file_set_hash mismatch")
        if str(receipt.get("evidence_manifest_hash", "")).strip() != str(evidence_binding.get("evidence_manifest_hash", "")).strip():
            reasons.append("gate receipt top-level evidence_manifest_hash mismatch")

    receipt_mode = normalize_status(receipt.get("mode"), "")
    receipt_profile = str(receipt.get("profile", "")).strip()
    gate_status = normalize_status(receipt.get("gate_status"), "UNKNOWN")
    release_semantics = receipt.get("release_semantics", {})
    if not isinstance(release_semantics, dict):
        reasons.append("gate receipt release_semantics are missing")
    else:
        expected_scope = "release" if receipt_mode == "RELEASE" else "verification"
        if str(release_semantics.get("scope", "")).strip() != expected_scope:
            reasons.append("gate receipt release_semantics scope mismatch")
        if bool(release_semantics.get("release_mode", False)) != (receipt_mode == "RELEASE"):
            reasons.append("gate receipt release_semantics release_mode mismatch")
        if str(release_semantics.get("release_profile_required", "")).strip() != "L4":
            reasons.append("gate receipt release_semantics release_profile_required mismatch")
        expected_scope_authoritative = receipt_mode == "RELEASE" and receipt_profile == "L4"
        if bool(release_semantics.get("release_scope_authoritative", False)) != expected_scope_authoritative:
            reasons.append("gate receipt release_semantics release_scope_authoritative mismatch")
        expected_release_ready = expected_scope_authoritative and gate_status == "PASS"
        if bool(release_semantics.get("release_ready", False)) != expected_release_ready:
            reasons.append("gate receipt release_semantics release_ready mismatch")
        if bool(release_semantics.get("verify_claims_authoritative", False)) is not True:
            reasons.append("gate receipt release_semantics verify_claims_authoritative mismatch")
    if receipt_mode == "RELEASE" and receipt_profile != "L4":
        reasons.append("gate receipt release mode requires the L4 profile")

    return {
        "ok": not reasons,
        "reasons": reasons,
        "warnings": warnings,
        "state_path": str(expected_state_path) if expected_state_path is not None else "",
        "state_root": str(expected_state_root),
    }
