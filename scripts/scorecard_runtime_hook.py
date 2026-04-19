#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


DEFAULT_AUTHORITY_PATH = Path("/home/andy4917/Dev-Management/contracts/workspace_authority.json")
DEFAULT_THROTTLE_SECONDS = {
    "SessionStart": 0,
    "UserPromptSubmit": 300,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_authority(path: Path | None = None) -> dict[str, Any]:
    authority_path = path or DEFAULT_AUTHORITY_PATH
    return load_json(authority_path)


def canonical_roots(authority: dict[str, Any]) -> dict[str, Path]:
    return {
        name: Path(raw).expanduser().resolve()
        for name, raw in authority.get("canonical_roots", {}).items()
    }


def path_within_roots(path: Path, roots: dict[str, Path]) -> bool:
    resolved = path.expanduser().resolve()
    for root in roots.values():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def nearest_git_root(start: Path) -> Path | None:
    current = start.expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def workspace_root_for_cwd(cwd: Path, roots: dict[str, Path]) -> Path | None:
    git_root = nearest_git_root(cwd)
    if git_root is not None and path_within_roots(git_root, roots):
        return git_root
    if path_within_roots(cwd, roots):
        return cwd.expanduser().resolve()
    return None


def hook_cfg(authority: dict[str, Any]) -> dict[str, Any]:
    return authority.get("generation_targets", {}).get("scorecard", {}).get("runtime_hook", {})


def hook_state_dir(authority: dict[str, Any]) -> Path:
    state_root = hook_cfg(authority).get("state_root")
    if state_root:
        return Path(state_root).expanduser().resolve()
    return (Path.home() / ".codex" / "state" / "scorecard-hook").resolve()


def throttle_seconds(authority: dict[str, Any], event: str) -> int:
    cfg = hook_cfg(authority)
    if event == "UserPromptSubmit":
        return int(cfg.get("user_prompt_throttle_seconds", DEFAULT_THROTTLE_SECONDS[event]))
    return DEFAULT_THROTTLE_SECONDS.get(event, 0)


def state_file_for(state_dir: Path, workspace_root: Path, event: str) -> Path:
    digest = hashlib.sha1(f"{workspace_root}:{event}".encode("utf-8")).hexdigest()
    return state_dir / f"{digest}.json"


def should_emit(state_dir: Path, workspace_root: Path, event: str, throttle: int, now: float) -> bool:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_file_for(state_dir, workspace_root, event)
    if throttle > 0 and state_path.exists():
        try:
            payload = load_json(state_path)
            previous = float(payload.get("emitted_at_epoch", 0))
            if now - previous < throttle:
                return False
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    state_path.write_text(
        json.dumps(
            {
                "workspace_root": str(workspace_root),
                "event": event,
                "emitted_at_epoch": now,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True


def build_notice(authority: dict[str, Any], workspace_root: Path) -> str:
    management_root = canonical_roots(authority)["management"]
    scorecard = authority.get("generation_targets", {}).get("scorecard", {})
    prepare = management_root / "scripts" / "prepare_user_scorecard_review.py"
    delivery_gate = Path(scorecard["delivery_gate"])
    summary_export = Path(scorecard["summary_export"])
    audit = management_root / "scripts" / "audit_workspace.py"
    workspace = str(workspace_root)
    return "\n".join(
        [
            f"[scorecard-hook] Global scorecard layer is binding for {workspace}. Do not ignore requested vs credited score, anti-cheat, gate, or audit output.",
            "[scorecard-hook] Advisory reminder only. The explicit verify chain remains the canonical enforcement path.",
            "[scorecard-hook] Before finalizing run: "
            f"python {prepare} --workspace-root {workspace} --mode verify -> "
            f"python {delivery_gate} --mode verify --workspace-root {workspace} -> "
            f"python {summary_export} -> "
            f"python {audit} --write-report",
        ]
    )


def emit_notice(
    *,
    authority: dict[str, Any],
    cwd: Path,
    event: str,
    now: float | None = None,
    state_dir: Path | None = None,
) -> str:
    roots = canonical_roots(authority)
    workspace_root = workspace_root_for_cwd(cwd, roots)
    if workspace_root is None:
        return ""
    now_value = now if now is not None else time.time()
    state_root = state_dir if state_dir is not None else hook_state_dir(authority)
    if not should_emit(state_root, workspace_root, event, throttle_seconds(authority, event), now_value):
        return ""
    return build_notice(authority, workspace_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit the global scorecard close-out reminder from a Codex runtime hook.")
    parser.add_argument("--event", required=True, help="Hook event name such as SessionStart or UserPromptSubmit.")
    parser.add_argument("--authority-path", default=os.environ.get("CODEX_SCORECARD_HOOK_AUTHORITY_PATH", str(DEFAULT_AUTHORITY_PATH)))
    parser.add_argument("--cwd", default=os.environ.get("CODEX_SCORECARD_HOOK_CWD", os.getcwd()))
    args = parser.parse_args()

    authority = load_authority(Path(args.authority_path))
    notice = emit_notice(
        authority=authority,
        cwd=Path(args.cwd),
        event=str(args.event),
    )
    if notice:
        print(notice)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
