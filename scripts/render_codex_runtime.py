#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any


AUTHORITY_PATH = Path("/home/andy4917/Dev-Management/contracts/workspace_authority.json")


def load_authority() -> dict:
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def sync_generated_text(path: Path, text: str | None) -> None:
    if text is None:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        return
    write_text(path, text)


def relink(link: Path, target: Path) -> None:
    ensure_parent(link)
    if link.is_symlink() or link.exists():
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(target)


def sync_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def render_agents(authority: dict, windows: bool) -> str:
    roots = authority["canonical_roots"]
    cleanup = authority["cleanup_policy"]
    scorecard = authority["generation_targets"]["scorecard"]
    layering = authority["runtime_layering"]
    restore = layering["restore_seed_policy"]
    override = layering["user_override_policy"]
    blocked_features = [str(item) for item in override.get("blocked_feature_overrides", [])]
    header = ""
    if windows:
        header = authority["generation_targets"]["global_runtime"]["windows_mirror"]["generated_header"] + "\n\n"
    structural_override_line = ""
    if blocked_features:
        structural_override_line = (
            f"- Structural feature overrides stay pinned to authority defaults: `{', '.join(blocked_features)}`.\n"
        )
    return (
        f"{header}"
        f"# Generated Codex Workspace Contract\n\n"
        f"- Authority file: `{AUTHORITY_PATH}`\n"
        f"- Canonical roots are fixed to `{roots['management']}`, `{roots['workflow']}`, `{roots['product']}`.\n"
        f"- Global topology, classification, cleanup, and generation rules derive only from the authority file.\n"
        f"- Do not keep hardcoded legacy paths, fallback copies, shadow configs, deprecated outputs, or backup policy copies outside the authority file or generated runtime files.\n"
        f"- Project-specific rules are allowed only inside `{roots['product']}/<project>/` as `AGENTS.md`, `.codex/config.toml`, `contracts/`, and truly project-specific verify scripts.\n"
        f"- Treat auth, history, logs, caches, sqlite, recent workspaces, and favorites as runtime state, not policy.\n"
        f"- Runtime layers are fixed as L0 authority -> L1 user override -> L2 generated mirror -> L3 runtime restore seed -> L4 volatile runtime.\n"
        f"- L1 user override may change only `{', '.join(override['allowed_fields'])}` and must never override `{', '.join(override['protected_fields'])}`.\n"
        f"{structural_override_line}"
        f"- Runtime restore seed is derived-only, preserves named threads, drops stale projectless restore refs, removes stale remote environment state, and prefers `{restore['preferred_windows_access_host']}` UNC roots.\n"
        f"- Terminal restore must stay in `{restore['terminal_restore_policy']}` mode and conversation detail should default to `{restore['conversation_detail_mode']}` while stabilization is in progress.\n"
        f"- Use `.git` as the only project root marker.\n"
        f"- Hooks are not a primary enforcement surface; run deterministic verification before finishing work.\n"
        f"- User penalty scorecard is global and canonical at `{scorecard['policy']}` and `{scorecard['disqualifiers']}`.\n"
        f"- Writer self-scoring, writer bonus scores, shadow scores, and fallback scores are forbidden. User review is a protected layer and cannot change without explicit user approval or task request; confirmed work/performance awards are derived automatically, users may add extra awards mid-task only within budget, and the anti-cheat layer denies, penalizes, caps, or disqualifies score manipulation attempts.\n"
        f"- Reviewer truth is append-only runtime state under `{scorecard['reviewer_verdict_root']}`; `{scorecard['review_snapshot']}` is a derived human-readable snapshot only.\n"
        f"- Disqualifiers outrank score. PASS still requires reviewer green, existing readiness, and clean-room verify.\n"
        f"- The global scorecard layer is binding instruction-level guidance across canonical roots. Do not ignore requested vs credited score, anti-cheat output, gate status, summary export, or final audit results.\n"
        f"- Product-local `python scripts/delivery_gate.py --mode verify` wrappers are valid close-out surfaces only when they produce fresh evidence, refresh the derived review snapshot, then call the global scorecard gate and summary export.\n"
        f"- Canonical global scorecard order: `python {roots['management']}/scripts/prepare_user_scorecard_review.py --workspace-root <repo> --mode verify` -> `python {scorecard['delivery_gate']} --mode verify --workspace-root <repo>` -> `python {scorecard['summary_export']}`.\n"
        f"- Generated runtime hooks may replay the scorecard close-out reminder at session start and prompt submit, but the canonical enforcement surface remains the explicit verify chain.\n"
        f"- Verify/release require fresh evidence manifests plus a signed workspace authority lease under `{scorecard['workspace_authority_root']}`.\n"
        f"- Required scorecard gate command: `python {scorecard['delivery_gate']} --mode verify`\n"
        f"- Required scorecard summary command: `python {scorecard['summary_export']}`\n"
        f"- Required final verification command: `python {roots['management']}/scripts/audit_workspace.py --write-report`\n"
        f"- Ambiguous cleanup targets go to `{cleanup['quarantine_root']}` before deletion.\n"
    )


def load_context7_template() -> dict:
    policy_path = AUTHORITY_PATH.parent / "context7_policy.json"
    if not policy_path.exists():
        return {}
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    return payload.get("remote_template", {})


def user_override_config_paths(authority: dict) -> list[Path]:
    # The Windows mirror is generated output, so only the Linux config can feed overrides back in.
    runtime = authority.get("generation_targets", {}).get("global_runtime", {})
    paths: list[Path] = []
    raw_path = runtime.get("linux", {}).get("config")
    if raw_path:
        path = Path(raw_path)
        if path.exists():
            paths.append(path.resolve())
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in sorted(paths, key=lambda item: (item.stat().st_mtime, str(item))):
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def path_within_canonical_roots(path_str: str, authority: dict) -> bool:
    candidate = Path(path_str).expanduser().resolve()
    roots = authority.get("canonical_roots", {})
    for raw_root in roots.values():
        try:
            candidate.relative_to(Path(raw_root).expanduser().resolve())
            return True
        except ValueError:
            continue
    return False


def blocked_feature_overrides(authority: dict) -> set[str]:
    override = authority.get("runtime_layering", {}).get("user_override_policy", {})
    return {str(item) for item in override.get("blocked_feature_overrides", [])}


def merge_nested_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_nested_dict(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def nested_diff_from_base(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    diff: dict[str, Any] = {}
    for key, value in candidate.items():
        base_value = base.get(key)
        if isinstance(value, dict):
            child_base = base_value if isinstance(base_value, dict) else {}
            child_diff = nested_diff_from_base(child_base, value)
            if child_diff:
                diff[key] = child_diff
            continue
        if key not in base or base_value != value:
            diff[key] = copy.deepcopy(value)
    return diff


def build_effective_global_config(authority: dict, override_paths: list[Path] | None = None) -> dict[str, Any]:
    cfg = authority["generation_targets"]["global_config"]
    blocked_features = blocked_feature_overrides(authority)
    base_features = {
        str(feature): True
        for feature in cfg.get("enabled_features", [])
        if str(feature) not in blocked_features
    }
    base_context7 = copy.deepcopy(load_context7_template())
    effective: dict[str, Any] = {
        "model": cfg["model"],
        "model_reasoning_effort": cfg["model_reasoning_effort"],
        "approval_policy": cfg["approval_policy"],
        "sandbox_mode": cfg["sandbox_mode"],
        "web_search": cfg["web_search"],
        "network_access": bool(cfg["network_access"]),
        "context7": copy.deepcopy(base_context7),
        "features": copy.deepcopy(base_features),
        "trusted_projects": list(dict.fromkeys(str(project) for project in cfg.get("trusted_projects", []))),
        "enabled_plugins": [str(plugin) for plugin in cfg.get("enabled_plugins", [])],
    }
    for key in ("ux", "workspace_preference", "memories"):
        if key in cfg:
            effective[key] = copy.deepcopy(cfg[key])

    override_source_paths = override_paths if override_paths is not None else user_override_config_paths(authority)
    for path in override_source_paths:
        payload = load_toml(path)
        for key in ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode", "web_search"):
            if key in payload and payload[key] != cfg[key]:
                effective[key] = payload[key]

        sandbox_cfg = payload.get("sandbox_workspace_write", {})
        if (
            isinstance(sandbox_cfg, dict)
            and isinstance(sandbox_cfg.get("network_access"), bool)
            and sandbox_cfg["network_access"] != cfg["network_access"]
        ):
            effective["network_access"] = sandbox_cfg["network_access"]

        mcp_servers = payload.get("mcp_servers", {})
        if isinstance(mcp_servers, dict):
            context7_cfg = mcp_servers.get("context7", {})
            if isinstance(context7_cfg, dict):
                context7_override = nested_diff_from_base(base_context7, context7_cfg)
                if context7_override:
                    effective["context7"] = merge_nested_dict(effective.get("context7", {}), context7_override)

        feature_cfg = payload.get("features", {})
        if isinstance(feature_cfg, dict):
            for feature, enabled in feature_cfg.items():
                if str(feature) in blocked_features or not isinstance(enabled, bool):
                    continue
                feature_name = str(feature)
                if feature_name in base_features and base_features[feature_name] == enabled:
                    continue
                effective["features"][feature_name] = enabled

        projects_cfg = payload.get("projects", {})
        if isinstance(projects_cfg, dict):
            trusted_projects = list(effective["trusted_projects"])
            for project_path, project_cfg in projects_cfg.items():
                if not isinstance(project_cfg, dict):
                    continue
                if str(project_cfg.get("trust_level", "")).strip().lower() != "trusted":
                    continue
                project_str = str(project_path)
                if project_str in trusted_projects or not path_within_canonical_roots(project_str, authority):
                    continue
                trusted_projects.append(project_str)
            effective["trusted_projects"] = trusted_projects

        for key in ("ux", "workspace_preference", "memories"):
            value = payload.get(key)
            if isinstance(value, dict) and value != cfg.get(key):
                effective[key] = copy.deepcopy(value)

    return effective


def toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_literal(item) for item in value) + "]"
    raise TypeError(f"Unsupported TOML value: {value!r}")


def append_table(lines: list[str], header: str, payload: dict[str, Any]) -> None:
    if not payload:
        return
    lines.append(f"[{header}]")
    nested: list[tuple[str, dict[str, Any]]] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            nested.append((key, value))
            continue
        lines.append(f"{key} = {toml_literal(value)}")
    lines.append("")
    for key, value in nested:
        append_table(lines, f"{header}.{key}", value)


def render_context7_lines(context7: dict[str, Any]) -> list[str]:
    if not context7:
        return []
    lines = ["[mcp_servers.context7]"]
    ordered_keys = ("url", "bearer_token_env_var", "enabled", "required", "startup_timeout_sec", "tool_timeout_sec")
    handled: set[str] = {"env_http_headers"}
    for key in ordered_keys:
        if key not in context7:
            continue
        lines.append(f"{key} = {toml_literal(context7[key])}")
        handled.add(key)
    for key in sorted(context7):
        if key in handled or isinstance(context7[key], dict):
            continue
        lines.append(f"{key} = {toml_literal(context7[key])}")
    lines.append("")
    headers = context7.get("env_http_headers", {})
    if isinstance(headers, dict) and headers:
        append_table(lines, "mcp_servers.context7.env_http_headers", headers)
    return lines


def render_config(authority: dict, windows: bool, effective_cfg: dict[str, Any] | None = None) -> str:
    cfg = effective_cfg or build_effective_global_config(authority)
    trusted = cfg["trusted_projects"]
    lines = []
    if windows:
        lines.append(f"# {authority['generation_targets']['global_runtime']['windows_mirror']['generated_header']}")
    lines.extend(
        [
            f'model = "{cfg["model"]}"',
            f'model_reasoning_effort = "{cfg["model_reasoning_effort"]}"',
            f'approval_policy = "{cfg["approval_policy"]}"',
            f'sandbox_mode = "{cfg["sandbox_mode"]}"',
            f'web_search = "{cfg["web_search"]}"',
            'project_root_markers = [".git"]',
            "",
            "[sandbox_workspace_write]",
            f'network_access = {"true" if cfg["network_access"] else "false"}',
            "",
        ]
    )
    context7_lines = render_context7_lines(cfg.get("context7", {}))
    if context7_lines:
        lines.extend(context7_lines + [""])
    features = cfg.get("features", {})
    if features:
        lines.append("[features]")
        for feature, enabled in features.items():
            lines.append(f"{feature} = {'true' if enabled else 'false'}")
        lines.append("")
    for project in trusted:
        lines.extend(
            [
                f'[projects."{project}"]',
                'trust_level = "trusted"',
                "",
            ]
        )
    for plugin in cfg["enabled_plugins"]:
        lines.extend(
            [
                f'[plugins."{plugin}"]',
                "enabled = true",
                "",
            ]
        )
    for table_name in ("ux", "workspace_preference", "memories"):
        table_payload = cfg.get(table_name)
        if isinstance(table_payload, dict) and table_payload:
            append_table(lines, table_name, table_payload)
    return "\n".join(lines).rstrip() + "\n"


def render_hooks(authority: dict, windows: bool) -> str | None:
    runtime_hook = authority.get("generation_targets", {}).get("scorecard", {}).get("runtime_hook", {})
    script = str(runtime_hook.get("script", "")).strip()
    events = runtime_hook.get("events", {})
    if not script or not isinstance(events, dict) or not events:
        return None

    hooks: dict[str, list[dict[str, Any]]] = {}
    linux_prefix = str(runtime_hook.get("linux_command_prefix", "python3")).strip() or "python3"
    windows_prefix = str(runtime_hook.get("windows_command_prefix", "wsl.exe python3")).strip() or "wsl.exe python3"
    for event_name, payload in events.items():
        matcher = ".*"
        if isinstance(payload, dict):
            matcher = str(payload.get("matcher", ".*")).strip() or ".*"
        command = f"{linux_prefix} {script} --event {event_name}"
        if windows:
            command = f"{windows_prefix} {script} --event {event_name}"
        hooks[str(event_name)] = [
            {
                "matcher": matcher,
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                    }
                ],
            }
        ]
    return json.dumps({"hooks": hooks}, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render generated Codex runtime files from workspace authority.")
    parser.add_argument("--skip-skills", action="store_true", help="Skip skill exposure synchronization.")
    args = parser.parse_args()

    authority = load_authority()
    runtime = authority["generation_targets"]["global_runtime"]
    effective_cfg = build_effective_global_config(authority)
    write_text(Path(runtime["linux"]["agents"]), render_agents(authority, windows=False))
    write_text(Path(runtime["linux"]["config"]), render_config(authority, windows=False, effective_cfg=effective_cfg))
    write_text(Path(runtime["windows_mirror"]["agents"]), render_agents(authority, windows=True))
    write_text(Path(runtime["windows_mirror"]["config"]), render_config(authority, windows=True, effective_cfg=effective_cfg))
    linux_hooks = runtime["linux"].get("hooks_config")
    if linux_hooks:
        sync_generated_text(Path(linux_hooks), render_hooks(authority, windows=False))
    windows_hooks = runtime["windows_mirror"].get("hooks_config")
    if windows_hooks:
        sync_generated_text(Path(windows_hooks), render_hooks(authority, windows=True))
    relink(Path.home() / ".codex" / "workspace_authority.json", AUTHORITY_PATH)

    if not args.skip_skills:
        skill_cfg = authority["generation_targets"]["skill_exposure"]
        relink(Path(skill_cfg["wsl_symlink"]["link"]), Path(skill_cfg["wsl_symlink"]["target"]))
        source = Path(skill_cfg["windows_generated_mirror"]["source"])
        target = Path(skill_cfg["windows_generated_mirror"]["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        sync_tree(source, target)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
