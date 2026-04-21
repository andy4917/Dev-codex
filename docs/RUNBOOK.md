# Runbook

## Runtime Authority

- Codex App is the primary user control surface and remote session control surface.
- Windows host is the app host and SSH client surface.
- Dev-Management is the source of truth for policy, runtime authority, guard, audit, repair, and score gates.
- Path authority is defined in `contracts/path_authority_policy.json`; `.env`, `.envrc`, and direnv are exported runtime views only.
- `devmgmt-wsl` is the canonical remote execution surface.
- Linux-native Codex CLI on the remote login-shell PATH is the canonical agent binary.
- The Windows-mounted Codex launcher is an external dependency and forbidden primary runtime.
- Linux generated runtime files are outputs only; use `$HOME/.codex/user-config.toml` for allowed global overrides.
- Windows `.codex` is app runtime state and evidence only and must not contain Dev-Management-generated policy files.
- Tracked source rollback uses Git history, and generated output rollback uses deterministic regeneration rather than `.bak` or fallback copies.
- Windows Codex App bootstrap must preserve `[features] remote_control = true` and `remote_connections = true`; removing `remote_connections` hides the Connections UI.
- Keep a pinned `Dev-Management Control` thread for readiness, maintenance routing, and non-destructive diagnostics.
- Persistent ops worktrees are optional, non-authoritative, and must never replace the canonical repo root.
- Default implementation work to task-scoped ephemeral worktrees when Worktree mode is used.

## Preflight

1. `git status --short`
2. `git diff --check`
3. `python3 scripts/check_global_runtime.py --json`
4. `python3 scripts/preflight_path_context.py --json`
5. `python3 scripts/check_config_provenance.py --json`
6. `python3 scripts/check_toolchain_surface.py --json`
7. `python3 scripts/check_agent_instruction.py --instruction "<task>"`
8. `python3 scripts/check_startup_workflow.py --mode ssh-managed --json`
9. `python3 scripts/audit_workspace.py --json`
10. `python3 scripts/activate_codex_app_usability.py --dry-run --json` when the goal is app readiness rather than general code modification
11. If working in a worktree, confirm `active_worktree_root` and `canonical_repo_root` before modifications

## Verify Loop

- `python3 scripts/check_global_runtime.py --json`
- `python3 scripts/preflight_path_context.py --json`
- `python3 scripts/check_config_provenance.py --json`
- `python3 scripts/check_toolchain_surface.py --json`
- `python3 scripts/check_artifact_hygiene.py --json`
- `python3 scripts/run_score_layer.py --json`
- `python3 scripts/check_git_surface.py --json`
- `python3 scripts/check_startup_workflow.py --mode ssh-managed --json`
- `python3 scripts/audit_workspace.py --json --write-report`
- For app usability, also require explicit project-open proof in `reports/windows-app-ssh-remote-readiness.final.json` and `reports/codex-app-usability-final.json`

## Guard Expectations

- Serena-first before general code modification in the authority repo
- Context7-first before protected dependency, API, config, or migration work
- client PATH contamination is a warning when canonical remote execution is PASS
- local shell direct execution remains blocked when forbidden launcher paths are primary
- hooks are trigger-only and not the final enforcement surface
- app update or settings sync cannot redefine Dev-Management authority
- a pinned control thread is allowed, but thread context and app memory remain hints only
- Linux generated runtime files always bind to the canonical repo root, never a task worktree root
- quarantine is inert evidence only and must not be executable, importable, or treated as a restore source

## Failure Handling

- canonical SSH runtime unavailable => BLOCKED
- remote codex still resolving through Windows-mounted launcher => BLOCKED
- generated Linux runtime self-feed => BLOCKED
- stale active config flags => BLOCKED
- missing Context7 for protected change => BLOCKED
- missing Serena activation for general code modification => BLOCKED
- workspace dependency tools disabled but unused => PASS or WARN depending on workflow need
- app usability may be WARN when Serena still blocks general code modification but the remote project has opened and remote codex, config provenance, and auth flow are ready
- app usability is NOT READY until Codex App proves that `${DEVMGMT_ROOT}` opened on `devmgmt-wsl`

## Close-Out

- `python3 scripts/iaw_closeout.py --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify`
- The commands below are the internal chain that `iaw_closeout.py` runs. Use them directly only for debugging or focused verification of a single stage.
- `python3 scripts/prepare_user_scorecard_review.py --workspace-root <repo> --mode verify`
- `python3 scripts/audit_workspace.py --phase pre-gate --blocking-only --write-report`
- `python3 scripts/delivery_gate.py --mode verify --workspace-root <repo>`
- `python3 scripts/audit_workspace.py --phase pre-export --blocking-only --write-report`
- `python3 scripts/export_user_score_summary.py`
- `python3 scripts/audit_workspace.py --phase post-export --write-report`
- `python3 scripts/run_score_layer.py --json`
