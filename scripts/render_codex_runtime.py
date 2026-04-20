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
DEFAULT_MCP_SERVERS = ("context7", "serena")
DEFAULT_MCP_TRANSPORTS = {
    "context7": "remote_http",
    "serena": "stdio",
}
HTTP_ONLY_KEYS = {"url", "bearer_token_env_var", "http_headers", "env_http_headers"}
STDIO_ONLY_KEYS = {"command", "args", "env", "env_vars", "cwd"}
NESTED_MCP_KEYS = ("env_http_headers", "http_headers", "env", "env_vars")
HTTP_RENDER_ORDER = (
    "url",
    "enabled",
    "required",
    "startup_timeout_sec",
    "tool_timeout_sec",
    "enabled_tools",
    "disabled_tools",
)
STDIO_RENDER_ORDER = (
    "enabled",
    "required",
    "startup_timeout_sec",
    "tool_timeout_sec",
    "command",
    "args",
    "cwd",
    "enabled_tools",
    "disabled_tools",
)


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
    receipt_state_root = scorecard.get("receipt_state_root", "")
    receipt_root_text = (
        f"{receipt_state_root}/gate-receipts"
        if isinstance(receipt_state_root, str) and receipt_state_root.strip()
        else scorecard.get("gate_receipt_root", "")
    )
    layering = authority["runtime_layering"]
    restore = layering["restore_seed_policy"]
    override = layering["user_override_policy"]
    runtime_hook = scorecard.get("runtime_hook", {})
    hook_events = [str(name) for name in runtime_hook.get("events", {}).keys()]
    blocked_features = [str(item) for item in override.get("blocked_feature_overrides", [])]
    header = ""
    if windows:
        header = authority["generation_targets"]["global_runtime"]["windows_mirror"]["generated_header"] + "\n\n"
    structural_override_line = ""
    if blocked_features:
        structural_override_line = (
            f"- Structural feature overrides stay pinned to authority defaults: `{', '.join(blocked_features)}`.\n"
        )
    hook_notice = "- Generated runtime hooks may replay the scorecard close-out reminder at prompt submit, but the canonical enforcement surface remains the explicit verify chain.\n"
    if not hook_events:
        hook_notice = "- Generated runtime hooks are disabled; the canonical enforcement surface remains the explicit verify chain.\n"
    elif hook_events != ["UserPromptSubmit"]:
        hook_notice = (
            "- Generated runtime hooks may replay the scorecard close-out reminder for configured runtime events, "
            "but the canonical enforcement surface remains the explicit verify chain.\n"
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
        f"- Before code work, activate the current project or worktree with Serena when it is available.\n"
        f"- Check Serena onboarding and project memories before major code changes.\n"
        f"- Prefer Serena symbol and reference tools over repeated whole-file reads when Serena is available.\n"
        f"- Use Context7 before changing external libraries, frameworks, APIs, configuration, or migration behavior.\n"
        f"- If Serena or Context7 is unavailable, report the failure and use a clearly stated fallback.\n"
        f"- Hooks are not a primary enforcement surface; run deterministic verification before finishing work.\n"
        f"- User penalty scorecard is global and canonical at `{scorecard['policy']}` and `{scorecard['disqualifiers']}`.\n"
        f"- Writer self-scoring, writer bonus scores, shadow scores, and fallback scores are forbidden. User review is a protected layer and cannot change without explicit user approval or task request; confirmed work/performance awards are derived automatically, users may add extra awards mid-task only within budget, and the anti-cheat layer denies, penalizes, caps, or disqualifies score manipulation attempts.\n"
        f"- Reviewer truth is append-only runtime state under `{scorecard['reviewer_verdict_root']}`; `{scorecard['review_snapshot']}` is a derived human-readable snapshot only.\n"
        f"- Disqualifiers outrank score. PASS still requires reviewer green, existing readiness, and clean-room verify.\n"
        f"- The global scorecard layer is binding instruction-level guidance across canonical roots. Do not ignore requested vs credited score, anti-cheat output, gate status, summary export, or final audit results.\n"
        f"- Product-local `python scripts/delivery_gate.py --mode verify` wrappers are valid close-out surfaces only when they produce fresh evidence, refresh the derived review snapshot, then delegate into the canonical global close-out command.\n"
        f"- Canonical global close-out command: `python {scorecard['closeout']} --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify`.\n"
        f"- Canonical global scorecard internals remain: `python {roots['management']}/scripts/prepare_user_scorecard_review.py --workspace-root <repo> --mode verify` -> `python {scorecard['delivery_gate']} --mode verify --workspace-root <repo>` -> `python {scorecard['summary_export']}` -> `python {roots['management']}/scripts/audit_workspace.py --phase post-export --write-report`.\n"
        f"{hook_notice}"
        f"- Verify/release require fresh evidence manifests plus a signed workspace authority lease under `{scorecard['workspace_authority_root']}` and a signed gate receipt under `{receipt_root_text}`.\n"
        f"- Required scorecard close-out command: `python {scorecard['closeout']} --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify`\n"
        f"- Required scorecard gate command: `python {scorecard['delivery_gate']} --mode verify`\n"
        f"- Required scorecard summary command: `python {scorecard['summary_export']}`\n"
        f"- Required final verification command: `python {roots['management']}/scripts/audit_workspace.py --write-report`\n"
        f"- Ambiguous cleanup targets go to `{cleanup['quarantine_root']}` before deletion.\n"
    )


def load_mcp_policy(server_name: str) -> dict[str, Any]:
    policy_path = AUTHORITY_PATH.parent / f"{server_name}_policy.json"
    if not policy_path.exists():
        return {}
    return json.loads(policy_path.read_text(encoding="utf-8"))


def load_context7_template() -> dict[str, Any]:
    return load_mcp_policy("context7").get("remote_template", {})


def load_serena_template() -> dict[str, Any]:
    return load_mcp_policy("serena").get("template", {})


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


def mcp_server_key_policies(authority: dict) -> dict[str, dict[str, Any]]:
    override = authority.get("runtime_layering", {}).get("user_override_policy", {})
    raw = override.get("mcp_server_key_policies", {})
    if not isinstance(raw, dict):
        return {}
    return {str(name): value for name, value in raw.items() if isinstance(value, dict)}


def known_mcp_servers(authority: dict) -> list[str]:
    names = list(DEFAULT_MCP_SERVERS)
    for server_name in sorted(mcp_server_key_policies(authority)):
        if server_name not in names:
            names.append(server_name)
    return names


def server_transport(authority: dict, server_name: str) -> str:
    policy = mcp_server_key_policies(authority).get(server_name, {})
    transport = str(policy.get("transport", "")).strip()
    if transport:
        return transport
    return DEFAULT_MCP_TRANSPORTS.get(server_name, "")


def sanitize_mcp_server_config(server_name: str, payload: dict[str, Any], authority: dict) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    key_policy = mcp_server_key_policies(authority).get(server_name, {})
    allowed = {str(item) for item in key_policy.get("allowed_override_keys", [])}
    forbidden = {str(item) for item in key_policy.get("forbidden_keys", [])}
    transport = server_transport(authority, server_name)
    if transport == "remote_http":
        forbidden.update(STDIO_ONLY_KEYS)
    elif transport == "stdio":
        forbidden.update(HTTP_ONLY_KEYS)
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text in forbidden:
            continue
        if allowed and key_text not in allowed:
            continue
        sanitized[key_text] = copy.deepcopy(value)
    return sanitized


def load_mcp_server_templates(authority: dict) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    loaders = {
        "context7": load_context7_template,
        "serena": load_serena_template,
    }
    for server_name in known_mcp_servers(authority):
        loader = loaders.get(server_name)
        if loader is None:
            continue
        template = sanitize_mcp_server_config(server_name, loader(), authority)
        if template:
            templates[server_name] = template
    return templates


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
    base_mcp_servers = load_mcp_server_templates(authority)
    effective: dict[str, Any] = {
        "model": cfg["model"],
        "model_reasoning_effort": cfg["model_reasoning_effort"],
        "approval_policy": cfg["approval_policy"],
        "sandbox_mode": cfg["sandbox_mode"],
        "web_search": cfg["web_search"],
        "network_access": bool(cfg["network_access"]),
        "mcp_servers": copy.deepcopy(base_mcp_servers),
        "features": copy.deepcopy(base_features),
        "trusted_projects": list(dict.fromkeys(str(project) for project in cfg.get("trusted_projects", []))),
        "enabled_plugins": [str(plugin) for plugin in cfg.get("enabled_plugins", [])],
    }
    for server_name, template in base_mcp_servers.items():
        effective[server_name] = copy.deepcopy(template)
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
            for server_name in known_mcp_servers(authority):
                server_payload = mcp_servers.get(server_name, {})
                if not isinstance(server_payload, dict):
                    continue
                server_override = sanitize_mcp_server_config(server_name, server_payload, authority)
                if not server_override:
                    continue
                merged = merge_nested_dict(effective["mcp_servers"].get(server_name, {}), server_override)
                effective["mcp_servers"][server_name] = merged
                effective[server_name] = copy.deepcopy(merged)

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

    for server_name in known_mcp_servers(authority):
        if server_name in effective["mcp_servers"]:
            effective[server_name] = copy.deepcopy(effective["mcp_servers"][server_name])

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


def render_mcp_server_lines(authority: dict, server_name: str, payload: dict[str, Any]) -> list[str]:
    if not payload:
        return []
    lines = [f"[mcp_servers.{server_name}]"]
    transport = server_transport(authority, server_name)
    ordered_keys = HTTP_RENDER_ORDER if transport == "remote_http" else STDIO_RENDER_ORDER
    handled: set[str] = set(NESTED_MCP_KEYS)
    for key in ordered_keys:
        if key not in payload or isinstance(payload[key], dict):
            continue
        lines.append(f"{key} = {toml_literal(payload[key])}")
        handled.add(key)
    for key in sorted(payload):
        if key in handled or isinstance(payload[key], dict):
            continue
        lines.append(f"{key} = {toml_literal(payload[key])}")
    lines.append("")
    for nested_key in NESTED_MCP_KEYS:
        nested_payload = payload.get(nested_key, {})
        if isinstance(nested_payload, dict) and nested_payload:
            append_table(lines, f"mcp_servers.{server_name}.{nested_key}", nested_payload)
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
    for server_name in known_mcp_servers(authority):
        mcp_lines = render_mcp_server_lines(authority, server_name, cfg.get("mcp_servers", {}).get(server_name, {}))
        if mcp_lines:
            lines.extend(mcp_lines + [""])
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
    windows_prefix = str(runtime_hook.get("windows_command_prefix", "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File")).strip() or "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File"
    windows_wrapper_path = str(runtime_hook.get("windows_wrapper_path", "")).strip()
    for event_name, payload in events.items():
        matcher = ".*"
        if isinstance(payload, dict):
            matcher = str(payload.get("matcher", ".*")).strip() or ".*"
        command = f"{linux_prefix} {script} --event {event_name}"
        if windows:
            wrapper_command_path = linux_path_to_windows_command_path(windows_wrapper_path) if windows_wrapper_path else ""
            if wrapper_command_path:
                command = f"{windows_prefix} {wrapper_command_path} -Event {event_name} -AuthorityPath {AUTHORITY_PATH}"
            else:
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


def linux_path_to_windows_command_path(raw_path: str) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    if text.startswith("/mnt/") and len(text) > 7:
        drive = text[5]
        remainder = text[7:]
        return f"{drive.upper()}:/{remainder}"
    return text.replace("\\", "/")


def render_windows_hook_wrapper(authority: dict) -> str | None:
    runtime_hook = authority.get("generation_targets", {}).get("scorecard", {}).get("runtime_hook", {})
    script = str(runtime_hook.get("script", "")).strip()
    wrapper_path = str(runtime_hook.get("windows_wrapper_path", "")).strip()
    if not script or not wrapper_path:
        return None
    generated_header = str(runtime_hook.get("windows_wrapper_generated_header", "GENERATED - DO NOT EDIT")).strip() or "GENERATED - DO NOT EDIT"
    return (
        f"# {generated_header}\n"
        "param(\n"
        "  [Parameter(Mandatory=$true)][string]$Event,\n"
        f"  [string]$AuthorityPath = \"{AUTHORITY_PATH}\",\n"
        f"  [string]$HookScript = \"{script}\"\n"
        ")\n\n"
        "$ErrorActionPreference = \"SilentlyContinue\"\n\n"
        "function Convert-ToLinuxPath([string]$Value) {\n"
        "  if ([string]::IsNullOrWhiteSpace($Value)) { return \"\" }\n"
        "  $trimmed = $Value.Trim()\n"
        "  if ($trimmed.StartsWith('\\\\wsl.localhost\\', [System.StringComparison]::OrdinalIgnoreCase) -or $trimmed.StartsWith('\\\\wsl$\\', [System.StringComparison]::OrdinalIgnoreCase)) {\n"
        "    $parts = $trimmed -split '\\\\'\n"
        "    if ($parts.Length -lt 5) { return \"\" }\n"
        "    $segments = @()\n"
        "    for ($index = 4; $index -lt $parts.Length; $index++) {\n"
        "      if ($parts[$index]) { $segments += $parts[$index] }\n"
        "    }\n"
        "    if ($segments.Count -eq 0) { return '/' }\n"
        "    return '/' + ($segments -join '/')\n"
        "  }\n"
        "  if ($trimmed -match '^[A-Za-z]:\\\\') {\n"
        "    $converted = (& wsl.exe wslpath -a \"$trimmed\" 2>$null)\n"
        "    if ($LASTEXITCODE -eq 0 -and $converted) {\n"
        "      return (($converted | Out-String).Trim())\n"
        "    }\n"
        "  }\n"
        "  return \"\"\n"
        "}\n\n"
        "$cwdPath = \"\"\n"
        "try { $cwdPath = (Get-Location).ProviderPath } catch { $cwdPath = \"\" }\n"
        "$linuxCwd = Convert-ToLinuxPath $cwdPath\n"
        "if ([string]::IsNullOrWhiteSpace($linuxCwd)) { exit 0 }\n"
        "$output = & wsl.exe python3 $HookScript --event $Event --authority-path $AuthorityPath --cwd $linuxCwd 2>$null\n"
        "if ($LASTEXITCODE -eq 0 -and $output) {\n"
        "  if ($output -is [System.Array]) {\n"
        "    foreach ($line in $output) {\n"
        "      if (-not [string]::IsNullOrWhiteSpace($line)) { [Console]::Out.WriteLine($line) }\n"
        "    }\n"
        "  } else {\n"
        "    [Console]::Out.WriteLine($output)\n"
        "  }\n"
        "}\n"
        "exit 0\n"
    )


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
    wrapper_path = authority.get("generation_targets", {}).get("scorecard", {}).get("runtime_hook", {}).get("windows_wrapper_path")
    if wrapper_path:
        sync_generated_text(Path(wrapper_path), render_windows_hook_wrapper(authority))
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
