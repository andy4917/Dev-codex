from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def runtime_hook_config(authority: dict[str, Any]) -> dict[str, Any]:
    scorecard = authority.get("generation_targets", {}).get("scorecard", {})
    hook = scorecard.get("runtime_hook", {}) if isinstance(scorecard, dict) else {}
    return hook if isinstance(hook, dict) else {}


def hook_script(authority: dict[str, Any]) -> Path:
    hook = runtime_hook_config(authority)
    script = str(hook.get("script", "")).strip()
    if script:
        return Path(script).expanduser().resolve()
    return Path(r"C:\Users\anise\code\Dev-Management\scripts\scorecard_runtime_hook.py")


def hook_command(authority: dict[str, Any]) -> str:
    hook = runtime_hook_config(authority)
    prefix = str(hook.get("windows_command_prefix", "python")).strip() or "python"
    return f'{prefix} "{hook_script(authority)}" --event UserPromptSubmit'


def hooks_payload(authority: dict[str, Any]) -> dict[str, Any]:
    hook = runtime_hook_config(authority)
    events = hook.get("events", {}) if isinstance(hook.get("events"), dict) else {}
    user_prompt = events.get("UserPromptSubmit", {}) if isinstance(events.get("UserPromptSubmit"), dict) else {}
    matcher = str(user_prompt.get("matcher", ".*")).strip() or ".*"
    return {
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(authority),
                        }
                    ],
                }
            ]
        }
    }


def render_hooks_json(authority: dict[str, Any]) -> str:
    return json.dumps(hooks_payload(authority), ensure_ascii=False, indent=2) + "\n"


def is_expected_hooks_json(text: str, authority: dict[str, Any]) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return payload == hooks_payload(authority)


def codex_hooks_enabled(config_text: str) -> bool:
    in_features = False
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_features = line == "[features]"
            continue
        if in_features and re.match(r"^codex_hooks\s*=\s*true\b", line, flags=re.IGNORECASE):
            return True
        if in_features and re.match(r"^codex_hooks\s*=\s*false\b", line, flags=re.IGNORECASE):
            return False
    return False


def ensure_codex_hooks_feature(config_text: str) -> tuple[str, bool]:
    lines = config_text.splitlines()
    if not lines:
        return "[features]\ncodex_hooks = true\n", True
    in_features = False
    features_index: int | None = None
    changed = False
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            if in_features and not changed:
                lines.insert(index, "codex_hooks = true")
                changed = True
                break
            in_features = line == "[features]"
            if in_features:
                features_index = index
            continue
        if in_features and re.match(r"^codex_hooks\s*=", line, flags=re.IGNORECASE):
            if not re.match(r"^codex_hooks\s*=\s*true\b", line, flags=re.IGNORECASE):
                lines[index] = "codex_hooks = true"
                changed = True
            return "\n".join(lines) + "\n", changed
    if not changed:
        if in_features:
            lines.append("codex_hooks = true")
        elif features_index is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(["[features]", "codex_hooks = true"])
        changed = True
    return "\n".join(lines) + "\n", changed


def installed_hook_status(codex_home: Path, authority: dict[str, Any]) -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    hooks_path = codex_home / "hooks.json"
    config_text = config_path.read_text(encoding="utf-8", errors="ignore") if config_path.exists() else ""
    hooks_text = hooks_path.read_text(encoding="utf-8", errors="ignore") if hooks_path.exists() else ""
    enabled = codex_hooks_enabled(config_text)
    exact = bool(hooks_text) and is_expected_hooks_json(hooks_text, authority)
    return {
        "status": "PASS" if enabled and exact else "BLOCKED",
        "config_path": str(config_path),
        "hooks_path": str(hooks_path),
        "codex_hooks_enabled": enabled,
        "hooks_json_exact": exact,
        "reasons": [] if enabled and exact else [
            reason
            for reason, ok in (
                ("config.toml must enable features.codex_hooks=true", enabled),
                ("hooks.json must match the approved scorecard UserPromptSubmit hook", exact),
            )
            if not ok
        ],
    }


def install_scorecard_hook(codex_home: Path, authority: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    hooks_path = codex_home / "hooks.json"
    config_text = config_path.read_text(encoding="utf-8", errors="ignore") if config_path.exists() else ""
    next_config, config_changed = ensure_codex_hooks_feature(config_text)
    next_hooks = render_hooks_json(authority)
    hooks_changed = (hooks_path.read_text(encoding="utf-8", errors="ignore") if hooks_path.exists() else "") != next_hooks
    if apply:
        codex_home.mkdir(parents=True, exist_ok=True)
        config_path.write_text(next_config, encoding="utf-8")
        hooks_path.write_text(next_hooks, encoding="utf-8")
    status = installed_hook_status(codex_home, authority) if apply else {
        "status": "PASS" if not config_changed and not hooks_changed else "WARN",
        "config_path": str(config_path),
        "hooks_path": str(hooks_path),
        "codex_hooks_enabled": codex_hooks_enabled(next_config),
        "hooks_json_exact": True,
        "reasons": [],
    }
    status.update(
        {
            "applied": apply,
            "config_changed": config_changed,
            "hooks_changed": hooks_changed,
            "hook_command": hook_command(authority),
        }
    )
    return status
