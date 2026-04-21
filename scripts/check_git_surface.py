#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from devmgmt_runtime.paths import git_worktree_inventory

AUTHORITY_PATH = ROOT / "contracts" / "workspace_authority.json"
EXECUTION_SURFACES_PATH = ROOT / "contracts" / "execution_surfaces.json"
DEFAULT_OUTPUT_PATH = ROOT / "reports" / "git-surface.json"
REQUESTED_OPTIONAL_REPO = Path("/home/andy4917/reservation-system")
PROPOSED_GITATTRIBUTES_LINES = [
    "* text=auto eol=lf",
    "*.bat text eol=crlf",
    "*.cmd text eol=crlf",
    "*.ps1 text eol=crlf",
]
RELEVANT_CONFIG_PREFIXES = (
    "core.autocrlf",
    "core.eol",
    "core.hookspath",
    "credential.helper",
    "filter.lfs",
    "lfs.",
    "safe.directory",
    "extensions.worktreeconfig",
    "core.sparsecheckout",
    "submodule.",
    "remote.",
)


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collapse_status(values: list[str]) -> str:
    normalized = [value for value in values if value]
    if any(value == "BLOCKED" for value in normalized):
        return "BLOCKED"
    if any(value == "WARN" for value in normalized):
        return "WARN"
    return "PASS"


def status_exit_code(status: str) -> int:
    if status == "PASS":
        return 0
    if status == "WARN":
        return 1
    return 2


def load_authority() -> dict[str, Any]:
    return load_json(AUTHORITY_PATH, default={})


def load_execution_surfaces() -> dict[str, Any]:
    return load_json(EXECUTION_SURFACES_PATH, default={})


def canonical_repo_roots(authority: dict[str, Any], extra_roots: list[Path] | None = None) -> list[Path]:
    roots = authority.get("canonical_roots", {})
    management = Path(str(roots.get("management", ROOT))).expanduser().resolve()
    workflow = Path(str(roots.get("workflow", management.parent / "Dev-Workflow"))).expanduser().resolve()
    product_root = Path(str(roots.get("product", management.parent / "Dev-Product"))).expanduser().resolve()
    reservation = product_root / "reservation-system"
    items = [management, workflow, reservation, REQUESTED_OPTIONAL_REPO]
    if extra_roots:
        items.extend(path.expanduser().resolve() for path in extra_roots)
    ordered: list[Path] = []
    seen: set[Path] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def run(argv: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd) if cwd else None,
        )
    except OSError as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "argv": argv,
        }
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "argv": argv,
    }


def first_existing_git_exe() -> Path | None:
    candidates = [
        shutil.which("git.exe"),
        "/mnt/c/Program Files/Git/cmd/git.exe",
        "/mnt/c/Program Files/Git/bin/git.exe",
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None


def relevant_config_lines(output: str) -> list[str]:
    lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip().replace("\r", "")
        if not stripped:
            continue
        if any(part in stripped.lower() for part in RELEVANT_CONFIG_PREFIXES):
            lines.append(stripped)
    return lines


def config_map(lines: list[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for line in lines:
        try:
            _origin, rest = line.split("\t", 1)
            key, value = rest.split("=", 1)
        except ValueError:
            continue
        mapped[key.strip().lower()] = value.strip()
    return mapped


def git_lfs_available(git_binary: str) -> dict[str, Any]:
    result = run([git_binary, "lfs", "version"])
    return {
        "available": bool(result["ok"]),
        "stdout": str(result["stdout"]).strip(),
        "stderr": str(result["stderr"]).strip(),
    }


def probe_git_scope(git_binary: str, scope: str, *, cwd: Path | None = None) -> dict[str, Any]:
    result = run([git_binary, "config", f"--{scope}", "--list", "--show-origin"], cwd=cwd)
    lines = relevant_config_lines(str(result["stdout"]))
    return {
        "available": result["ok"],
        "scope": scope,
        "lines": lines,
        "map": config_map(lines),
        "stderr": str(result["stderr"]).strip(),
        "exit_code": result["exit_code"],
    }


def stale_safe_directories(lines: list[str]) -> list[str]:
    stale: list[str] = []
    for line in lines:
        try:
            _origin, rest = line.split("\t", 1)
            key, value = rest.split("=", 1)
        except ValueError:
            continue
        if key.strip().lower() != "safe.directory":
            continue
        candidate = Path(value.strip()).expanduser()
        if not candidate.exists():
            stale.append(value.strip())
    return sorted(set(stale))


def repo_canonical_root(repo_root: Path, authority: dict[str, Any]) -> Path:
    management = Path(str(authority.get("canonical_roots", {}).get("management", ROOT))).expanduser().resolve()
    if repo_root.resolve() == management:
        return management
    common_dir = run(["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"])
    raw_common = str(common_dir.get("stdout", "")).strip()
    if raw_common:
        common_path = Path(raw_common)
        if not common_path.is_absolute():
            common_path = (repo_root / common_path).resolve()
        if common_path == (management / ".git").resolve():
            return management
    return repo_root.resolve()


def worktree_policy(execution_surfaces: dict[str, Any]) -> dict[str, Any]:
    payload = execution_surfaces.get("worktree_policy", {})
    return payload if isinstance(payload, dict) else {}


def repo_git_probe(repo_root: Path, authority: dict[str, Any], execution_surfaces: dict[str, Any]) -> dict[str, Any]:
    canonical_root = repo_canonical_root(repo_root, authority)
    if not (repo_root / ".git").exists():
        status = "requested-path-missing" if repo_root == REQUESTED_OPTIONAL_REPO else "missing"
        return {
            "repo_root": str(repo_root),
            "canonical_repo_root": str(canonical_root),
            "active_worktree_root": str(repo_root.resolve()),
            "status": status,
            "dirty": [],
            "local_config": {"available": False, "lines": [], "map": {}},
            "top_level": "",
            "hooks_path": "",
            "is_worktree": False,
            "is_sparse_checkout": False,
            "superproject": "",
            "worktree_inventory": {
                "canonical_repo_root": str(canonical_root),
                "active_worktree_root": str(repo_root.resolve()),
                "worktrees": [],
                "stale_worktrees": [],
                "duplicate_branch_checkouts": {},
                "current_branch_conflict": False,
            },
            "worktree_policy_status": "PASS",
            "branch_lock_status": "PASS",
            "warnings": [],
        }

    local_config = probe_git_scope("git", "local", cwd=repo_root)
    dirty = run(["git", "-C", str(repo_root), "status", "--short"])
    top_level = run(["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"])
    hooks_path = run(["git", "-C", str(repo_root), "rev-parse", "--git-path", "hooks"])
    sparse = run(["git", "-C", str(repo_root), "sparse-checkout", "list"])
    worktree_inventory = git_worktree_inventory(
        repo_root,
        authority if canonical_root == Path(str(authority.get("canonical_roots", {}).get("management", ROOT))).expanduser().resolve() else {"authority_root": str(canonical_root)},
    )
    worktree_rules = worktree_policy(execution_surfaces)

    warnings: list[str] = []
    if dirty["stdout"].strip():
        warnings.append("repo is dirty")
    if local_config["map"].get("core.autocrlf"):
        warnings.append("repo overrides core.autocrlf locally")
    if worktree_inventory.get("stale_worktrees"):
        warnings.append("stale or prunable worktrees were detected")
    if worktree_inventory.get("current_branch_conflict"):
        warnings.append("current branch is checked out in multiple worktree locations")
    persistent_root = str(worktree_rules.get("persistent_ops_worktree_root", "")).strip()
    if persistent_root and not Path(persistent_root).expanduser().exists():
        warnings.append("configured persistent ops worktree path is stale or missing")

    worktree_policy_status = "WARN" if worktree_inventory.get("stale_worktrees") or (persistent_root and not Path(persistent_root).expanduser().exists()) else "PASS"
    branch_lock_status = "BLOCKED" if worktree_inventory.get("current_branch_conflict") else "PASS"

    return {
        "repo_root": str(repo_root),
        "canonical_repo_root": str(canonical_root),
        "active_worktree_root": str(worktree_inventory.get("active_worktree_root", repo_root.resolve())),
        "status": "present",
        "dirty": [line for line in str(dirty["stdout"]).splitlines() if line.strip()],
        "local_config": local_config,
        "top_level": str(top_level["stdout"]).strip(),
        "hooks_path": str(hooks_path["stdout"]).strip(),
        "is_worktree": bool(worktree_inventory.get("is_linked_worktree")) or str(worktree_inventory.get("active_worktree_root", "")) != str(canonical_root),
        "is_sparse_checkout": bool(sparse["ok"] and str(sparse["stdout"]).strip()),
        "superproject": "",
        "worktree_inventory": worktree_inventory,
        "worktree_policy_status": worktree_policy_status,
        "branch_lock_status": branch_lock_status,
        "warnings": warnings,
    }


def dev_management_gitattributes_proposal(repo_root: Path) -> dict[str, Any]:
    if repo_root.resolve() != ROOT.resolve():
        return {
            "repo_root": str(repo_root),
            "status": "WAIVED",
            "path": str(repo_root / ".gitattributes"),
            "reason": "repo-local .gitattributes proposals are only emitted for Dev-Management",
            "missing_lines": [],
        }
    path = repo_root / ".gitattributes"
    if not path.exists():
        return {
            "repo_root": str(repo_root),
            "status": "PROPOSED",
            "path": str(path),
            "reason": "Dev-Management does not define a repo-local .gitattributes policy yet",
            "missing_lines": PROPOSED_GITATTRIBUTES_LINES,
        }
    content = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    missing = [line for line in PROPOSED_GITATTRIBUTES_LINES if line not in content]
    return {
        "repo_root": str(repo_root),
        "status": "PASS" if not missing else "PROPOSED",
        "path": str(path),
        "reason": "" if not missing else "Dev-Management .gitattributes is missing recommended repo-local line ending rules",
        "missing_lines": missing,
    }


def compare_global_maps(wsl_global: dict[str, Any], windows_global: dict[str, Any]) -> list[dict[str, str]]:
    if not windows_global.get("available"):
        return []
    differences: list[dict[str, str]] = []
    keys = sorted(set(wsl_global.get("map", {})) | set(windows_global.get("map", {})))
    for key in keys:
        left = str(wsl_global.get("map", {}).get(key, ""))
        right = str(windows_global.get("map", {}).get(key, ""))
        if left == right:
            continue
        differences.append({"key": key, "wsl": left, "windows": right})
    return differences


def evaluate_git_surfaces(repo_roots: list[Path] | None = None) -> dict[str, Any]:
    authority = load_authority()
    execution_surfaces = load_execution_surfaces()
    roots = canonical_repo_roots(authority, repo_roots)
    git_exe = first_existing_git_exe()
    wsl_global = probe_git_scope("git", "global")
    wsl_system = probe_git_scope("git", "system")
    windows_global = (
        probe_git_scope(str(git_exe), "global")
        if git_exe is not None
        else {"available": False, "scope": "global", "lines": [], "map": {}, "stderr": "git.exe not found", "exit_code": None}
    )
    windows_system = (
        probe_git_scope(str(git_exe), "system")
        if git_exe is not None
        else {"available": False, "scope": "system", "lines": [], "map": {}, "stderr": "git.exe not found", "exit_code": None}
    )
    wsl_lfs = git_lfs_available("git")
    windows_lfs = git_lfs_available(str(git_exe)) if git_exe is not None else {"available": False, "stdout": "", "stderr": "git.exe not found"}
    repos = [repo_git_probe(path, authority, execution_surfaces) for path in roots]
    proposals = [dev_management_gitattributes_proposal(path) for path in roots]

    warnings: list[str] = []
    blockers: list[str] = []
    if not windows_global.get("available"):
        warnings.append("Windows Git global config could not be observed from WSL.")
    if stale_safe_directories(wsl_global.get("lines", [])):
        warnings.append("WSL global safe.directory contains stale paths.")
    if windows_global.get("available") and stale_safe_directories(windows_global.get("lines", [])):
        warnings.append("Windows Git global safe.directory contains stale paths.")
    if compare_global_maps(wsl_global, windows_global):
        warnings.append("Windows Git and WSL Git global config differ.")
    if not wsl_lfs.get("available") and (
        any(key.startswith("filter.lfs") or key.startswith("lfs.") for key in wsl_global.get("map", {}))
        or any(key.startswith("filter.lfs") or key.startswith("lfs.") for key in windows_global.get("map", {}))
    ):
        warnings.append("Git LFS is configured but unavailable in WSL.")
    if any(repo.get("dirty") for repo in repos if repo.get("status") == "present"):
        warnings.append("Dirty repos were detected and are reported only.")
    if any(repo.get("worktree_policy_status") == "WARN" for repo in repos if repo.get("status") == "present"):
        warnings.append("Stale or missing persistent worktree evidence was detected.")
    if any(repo.get("branch_lock_status") == "BLOCKED" for repo in repos if repo.get("status") == "present"):
        blockers.append("A branch is checked out in multiple worktree locations.")
    if any(item.get("status") == "PROPOSED" for item in proposals):
        warnings.append("Dev-Management repo-local .gitattributes proposal is available.")

    status = collapse_status(["BLOCKED" if blockers else "", "WARN" if warnings else ""])
    return {
        "status": status,
        "repo_reports": repos,
        "repo_local_guard_proposals": proposals,
        "canonical_repo_root": str(repo_canonical_root(Path(str(authority.get("canonical_roots", {}).get("management", ROOT))).expanduser().resolve(), authority)),
        "worktree_policy": worktree_policy(execution_surfaces),
        "wsl": {
            "global": wsl_global,
            "system": wsl_system,
            "lfs": wsl_lfs,
            "stale_safe_directories": stale_safe_directories(wsl_global.get("lines", [])),
        },
        "windows": {
            "git_exe": str(git_exe) if git_exe else "",
            "global": windows_global,
            "system": windows_system,
            "lfs": windows_lfs,
            "stale_safe_directories": stale_safe_directories(windows_global.get("lines", [])),
        },
        "global_drift": compare_global_maps(wsl_global, windows_global),
        "blocked_reasons": blockers,
        "warnings": warnings,
    }


def render_text_summary(report: dict[str, Any]) -> str:
    lines = [f"git surface status: {report['status']}"]
    for blocker in report.get("blocked_reasons", []):
        lines.append(f"- BLOCKED: {blocker}")
    for warning in report.get("warnings", []):
        lines.append(f"- {warning}")
    for repo in report.get("repo_reports", []):
        if repo.get("status") != "present":
            lines.append(f"- {repo['repo_root']}: {repo['status']}")
            continue
        dirty = len(repo.get("dirty", []))
        lines.append(
            f"- {repo['repo_root']}: dirty={dirty}, sparse={repo.get('is_sparse_checkout')}, worktree={repo.get('is_worktree')}, active_worktree_root={repo.get('active_worktree_root')}, canonical_repo_root={repo.get('canonical_repo_root')}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Git surface drift across WSL, Windows observation, and canonical repos.")
    parser.add_argument("--repo-root", action="append", default=[], help="Additional repo root to audit.")
    parser.add_argument("--output-file", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a text summary.")
    args = parser.parse_args()

    extra_roots = [Path(item).expanduser().resolve() for item in args.repo_root]
    report = evaluate_git_surfaces(extra_roots or None)
    output_path = Path(args.output_file).expanduser().resolve()
    save_json(output_path, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_summary(report))
        print(f"wrote {output_path}")
    return status_exit_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
