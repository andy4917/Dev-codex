#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


AUTHORITY_PATH = Path("/home/andy4917/Dev-Management/contracts/workspace_authority.json")


def load_authority() -> dict:
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")


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
    header = ""
    if windows:
        header = authority["generation_targets"]["global_runtime"]["windows_mirror"]["generated_header"] + "\n\n"
    return (
        f"{header}"
        f"# Generated Codex Workspace Contract\n\n"
        f"- Authority file: `{AUTHORITY_PATH}`\n"
        f"- Canonical roots are fixed to `{roots['management']}`, `{roots['workflow']}`, `{roots['product']}`.\n"
        f"- Global topology, classification, cleanup, and generation rules derive only from the authority file.\n"
        f"- Do not keep hardcoded legacy paths, fallback copies, shadow configs, deprecated outputs, or backup policy copies outside the authority file or generated runtime files.\n"
        f"- Project-specific rules are allowed only inside `{roots['product']}/<project>/` as `AGENTS.md`, `.codex/config.toml`, `contracts/`, and truly project-specific verify scripts.\n"
        f"- Treat auth, history, logs, caches, sqlite, recent workspaces, and favorites as runtime state, not policy.\n"
        f"- Use `.git` as the only project root marker.\n"
        f"- Hooks are not a primary enforcement surface; run deterministic verification before finishing work.\n"
        f"- User penalty scorecard is global and canonical at `{scorecard['policy']}` and `{scorecard['disqualifiers']}`.\n"
        f"- Writer self-scoring, bonus scores, shadow scores, and fallback scores are forbidden.\n"
        f"- Reviewer truth is append-only runtime state under `{scorecard['reviewer_verdict_root']}`; `{scorecard['review_snapshot']}` is a derived human-readable snapshot only.\n"
        f"- Disqualifiers outrank score. PASS still requires reviewer green, existing readiness, and clean-room verify.\n"
        f"- Product-local `python scripts/delivery_gate.py --mode verify` wrappers are valid close-out surfaces only when they produce fresh evidence, refresh the derived review snapshot, then call the global scorecard gate and summary export.\n"
        f"- Canonical global scorecard order: `python {roots['management']}/scripts/prepare_user_scorecard_review.py --workspace-root <repo> --mode verify` -> `python {scorecard['delivery_gate']} --mode verify --workspace-root <repo>` -> `python {scorecard['summary_export']}`.\n"
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


def render_context7_lines() -> list[str]:
    template = load_context7_template()
    if not template:
        return []
    lines = ["[mcp_servers.context7]"]
    if template.get("url"):
        lines.append(f'url = "{template["url"]}"')
    for key in ("enabled", "required"):
        if key in template:
            lines.append(f'{key} = {"true" if template[key] else "false"}')
    for key in ("startup_timeout_sec", "tool_timeout_sec"):
        if key in template:
            lines.append(f'{key} = {int(template[key])}')
    headers = template.get("env_http_headers", {})
    if headers:
        lines.append("")
        lines.append("[mcp_servers.context7.env_http_headers]")
        for key, value in headers.items():
            lines.append(f'{key} = "{value}"')
    return lines


def render_config(authority: dict, windows: bool) -> str:
    cfg = authority["generation_targets"]["global_config"]
    trusted = cfg["trusted_projects"]
    lines = []
    if windows:
        lines.append(f"# {authority['generation_targets']['global_runtime']['windows_mirror']['generated_header']}")
    lines.extend(
        [
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
    context7_lines = render_context7_lines()
    if context7_lines:
        lines.extend(context7_lines + [""])
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
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render generated Codex runtime files from workspace authority.")
    parser.add_argument("--skip-skills", action="store_true", help="Skip skill exposure synchronization.")
    args = parser.parse_args()

    authority = load_authority()
    runtime = authority["generation_targets"]["global_runtime"]
    write_text(Path(runtime["linux"]["agents"]), render_agents(authority, windows=False))
    write_text(Path(runtime["linux"]["config"]), render_config(authority, windows=False))
    write_text(Path(runtime["windows_mirror"]["agents"]), render_agents(authority, windows=True))
    write_text(Path(runtime["windows_mirror"]["config"]), render_config(authority, windows=True))
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
