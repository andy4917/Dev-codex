# Global Runtime Architecture

## Goal

Align Codex App main control, SSH remote execution, Linux-native Codex CLI, and Dev-Management authority under one model.

- Codex App is the primary user control surface.
- Codex App is the remote session control surface.
- Codex App is not the execution authority.
- Codex App is not the policy authority.
- Windows host is the app host and SSH client surface.
- `devmgmt-wsl` is the canonical remote execution surface.
- Linux-native Codex CLI on the remote login-shell PATH is the canonical agent binary.
- Dev-Management is the policy authority and runtime authority.
- Generated config mirrors are outputs only.
- Windows-mounted Codex launcher paths remain forbidden as the primary runtime.

## Current vs Desired

```text
Codex App on Windows
  -> SSH remote connection
  -> devmgmt-wsl
  -> Linux-native Codex CLI
  -> Dev-Management guard/audit/repair
  -> repo changes/tests/reports
```

Forbidden relation:

```text
Codex App on Windows
  -> Windows-mounted launcher
  -> /mnt/c/Users/anise/.codex/bin/wsl/codex
  -> primary execution runtime
```

## Surface Roles

- `codex_app`: `primary_user_control_surface`, `remote_session_control_surface`
- `windows_host`: `app_host`, `ssh_client_surface`, `user_surface`
- `windows_codex_state`: app state and restore evidence only
- `windows_codex_launcher`: external dependency and forbidden primary runtime
- `wsl_linux_shell`: local diagnostic surface only
- `ssh_devmgmt_wsl`: `canonical_remote_execution_surface`
- `linux_native_codex_cli`: `canonical_agent_binary`
- `dev_management`: `policy_authority`, `runtime_authority`, `source_of_truth`

## Generated Mirrors

- `/home/andy4917/.codex/config.toml` and `/mnt/c/Users/anise/.codex/config.toml` are generated mirrors.
- Generated mirrors are outputs only.
- Generated mirrors must never be used as render input, authority input, or user override input.
- `/home/andy4917/.codex/user-config.toml` is the only optional user override source.

## Status Semantics

- Canonical remote PASS plus client PATH contamination means `overall_status = WARN` and `canonical_execution_status = PASS`.
- Canonical remote FAIL means `overall_status = BLOCKED`.
- Local shell direct execution plus forbidden launcher remains `BLOCKED`.
- Remote execution through `devmgmt-wsl` and Linux-native Codex CLI is the success path.
- Generated mirror self-feed is always `BLOCKED`.
- Hook-only enforcement claims are always `BLOCKED`.

## Guard And Audit Rules

- App state, projectless chats, memories, restore refs, and plugin state can be evidence, never authority.
- Plugin-provided MCP drift is audit-relevant before code modification.
- Hooks may trigger checks, but audit, tests, and score layer remain the final gates.
- `telepathy`, `workspace_dependencies` without re-authorization, `approval_policy = "never"`, and `sandbox_mode = "danger-full-access"` are stale active config blockers.

## App Usability Scope

- Default verification purpose remains code-modification.
- App-usability is a narrower readiness scope for app restart, Settings > Connections, remote project open, sign-in, and task submission.
- Serena onboarding or activation may keep code-modification blocked while app-usability is only WARN.
- Remote SSH failure, forbidden Windows launcher primary runtime, generated mirror self-feed, and stale active config flags remain BLOCKED even for app-usability.
