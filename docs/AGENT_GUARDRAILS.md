# Agent Guardrails

## Default Stance

- Treat Codex App as the primary user control surface.
- Treat Windows host as the app host and SSH client surface.
- Treat `devmgmt-wsl` as the canonical remote execution surface.
- Treat Linux-native Codex CLI as the canonical agent binary.
- Treat Dev-Management as the policy authority and runtime authority.
- Treat Linux generated runtime files as outputs only.
- Treat Windows `.codex` as app runtime state and evidence only.
- Treat the pinned `Dev-Management Control` thread as a routing and maintenance surface only.
- Treat persistent ops worktrees as optional execution conveniences only.

## Standard Reminders

- runtime authority conflict: Codex App is the primary user control surface, but execution authority belongs to `devmgmt-wsl` and Linux-native Codex CLI
- Serena-first unmet: activation, onboarding, or latest activation evidence is incomplete
- Context7 evidence missing: protected dependency, API, config, or migration change requires real evidence
- generated runtime blocked: Linux generated runtime files cannot be used as authority or override inputs
- hooks trigger only: hooks may trigger checks, but audit, tests, and score layer are the final gates
- unrelated dirty changes present: report them and leave them untouched

## Editing Rules

- Do not manually edit generated Linux config, shim, hook, or AGENTS files.
- Do not use `/home/andy4917/.codex/config.toml` as override input.
- Do not generate or rely on Windows `.codex` config, AGENTS, hooks, skills, or score wrappers.
- Use `/home/andy4917/.codex/user-config.toml` only for allowed global user overrides.
- Do not add hardcoded fallback paths or reintroduce `/mnt/c/Users/anise/.codex/bin/wsl/codex` as a primary runtime target.
- Treat app memories, projectless chat state, and restore seed as hints only.
- Do not let a worktree, thread, or app memory become a source of truth.
- Do not claim hook-only enforcement.
- For app usability work, keep user actions limited to app restart, Settings > Connections, devmgmt-wsl selection, remote project open, sign-in, and normal task input whenever safe automation exists.
- Use the `Dev-Management Control` thread for readiness and maintenance routing, and use separate Worktree mode only for scoped implementation tasks.

## Work Pattern

- Before code work, inspect git status, instruction guard, global runtime, config provenance, and startup workflow.
- When worktree mode is in use, record both `active_worktree_root` and `canonical_repo_root`.
- During work, touch only in-scope files and record subagent, skill, plugin, hook, and workspace dependency usage when used.
- After work, run hardcoding scans, stale feature scans, config provenance checks, artifact hygiene checks, `git diff --check`, and relevant tests before commit.
