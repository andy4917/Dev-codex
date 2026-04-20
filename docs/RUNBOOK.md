# Runbook

## Runtime Authority

- Codex App is the primary user control surface and remote session control surface.
- Windows host is the app host and SSH client surface.
- Dev-Management is the source of truth for policy, runtime authority, guard, audit, repair, and score gates.
- `devmgmt-wsl` is the canonical remote execution surface.
- Linux-native Codex CLI on the remote login-shell PATH is the canonical agent binary.
- `/mnt/c/Users/anise/.codex/bin/wsl/codex` is an external dependency and forbidden primary runtime.
- Generated mirrors are outputs only; use `/home/andy4917/.codex/user-config.toml` for allowed global overrides.

## Preflight

1. `git status --short`
2. `git diff --check`
3. `python3 scripts/check_global_runtime.py --json`
4. `python3 scripts/check_config_provenance.py --json`
5. `python3 scripts/check_toolchain_surface.py --json`
6. `python3 scripts/check_agent_instruction.py --instruction "<task>"`
7. `python3 scripts/check_startup_workflow.py --mode ssh-managed --json`
8. `python3 scripts/audit_workspace.py --json`

## Verify Loop

- `python3 scripts/check_global_runtime.py --json`
- `python3 scripts/check_config_provenance.py --json`
- `python3 scripts/check_toolchain_surface.py --json`
- `python3 scripts/check_artifact_hygiene.py --json`
- `python3 scripts/run_score_layer.py --json`
- `python3 scripts/check_git_surface.py --json`
- `python3 scripts/check_startup_workflow.py --mode ssh-managed --json`
- `python3 scripts/audit_workspace.py --json --write-report`

## Guard Expectations

- Serena-first before general code modification in the authority repo
- Context7-first before protected dependency, API, config, or migration work
- client PATH contamination is a warning when canonical remote execution is PASS
- local shell direct execution remains blocked when forbidden launcher paths are primary
- hooks are trigger-only and not the final enforcement surface
- app update or settings sync cannot redefine Dev-Management authority

## Failure Handling

- canonical SSH runtime unavailable => BLOCKED
- remote codex still resolving through Windows-mounted launcher => BLOCKED
- generated mirror self-feed => BLOCKED
- stale active config flags => BLOCKED
- missing Context7 for protected change => BLOCKED
- missing Serena activation for general code modification => BLOCKED
- workspace dependency tools disabled but unused => PASS or WARN depending on workflow need

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
