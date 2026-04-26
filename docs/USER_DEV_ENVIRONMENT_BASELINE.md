# User Dev Environment Baseline

This baseline defines the user development environment for a Windows-only Codex App workflow. The workflow authority is [GLOBAL_AGENT_WORKFLOW.md](./GLOBAL_AGENT_WORKFLOW.md).

## Source Of Truth

- `C:\Users\anise\.codex` is `USER_CONTROL_PLANE + APP_STATE`, not repo authority.
- `C:\Users\anise\code` is the canonical workspace root.
- `C:\Users\anise\code\Dev-Management` owns environment policy and verification.
- Repo `AGENTS.md` remains stack/workflow authority for each repo.
- Package scripts remain command authority.

## Windows Responsibilities

- Run OpenAI Codex App with the Windows-native agent.
- Use PowerShell 7 as the integrated terminal.
- Keep PowerShell UTF-8 and native-argument policy under `C:\Users\anise\Documents\PowerShell\policies`.
- Keep `config.toml`, global custom instructions, MCP settings, and app state under `C:\Users\anise\.codex`.
- Keep governed repos under `C:\Users\anise\code`.
- Use repo-owned scripts and tests for verification.

## Required Config Posture

```toml
approval_policy = "never"
sandbox_mode = "danger-full-access"

[windows]
sandbox = "elevated"
```

`model_reasoning_effort` is a user-selected runtime preference. Verification records the observed value but does not gate readiness on a fixed effort level.

## Optional Tools

- Docker Desktop is optional for build, verification, packaging, or integration checks.
- GitHub CLI, uv, dotnet, and other toolchains are optional unless a repo script requires them.

## Forbidden

- Treating app memory as repo policy authority.
- Moving repo-specific stack or product rules into global app instructions.
- Using remote Linux execution as a governed runtime.
- Using mounted Linux launchers or remote routes as the primary agent path.
- Deleting migration evidence without an explicit cleanup decision.

## Verification

```powershell
python C:\Users\anise\code\Dev-Management\scripts\check_windows_app_local_readiness.py --json
python C:\Users\anise\code\Dev-Management\scripts\check_user_dev_environment.py --json
python C:\Users\anise\code\Dev-Management\scripts\check_global_agent_workflow.py --json
```
