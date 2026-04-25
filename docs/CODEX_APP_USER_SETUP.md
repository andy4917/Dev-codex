# Codex App User Setup

Open local Windows projects, not legacy remote projects.

Required settings:

- Agent environment: Windows native
- Integrated terminal: PowerShell 7
- Default workspace: `C:\Users\anise\code`
- Dev-Management project: `C:\Users\anise\code\Dev-Management`

The user-level control plane is `USER_CONTROL_PLANE + APP_STATE`, not repo authority:

```text
C:\Users\anise\.codex
```

The expected `config.toml` posture is trusted Windows-native full access:

```toml
sandbox_mode = "danger-full-access"
approval_policy = "never"

[windows]
sandbox = "elevated"
```

`model_reasoning_effort` can be changed per task/session by the user; it is not part of the readiness gate.

Keep global custom instructions short. Repo-specific stack, commands, and workflow rules belong in each repo's `AGENTS.md` and package scripts.

AI packages, MCP evidence roles, marketplace skills, and marketplace hooks are defined in [AI_TOOLCHAIN_USAGE.md](./AI_TOOLCHAIN_USAGE.md).

Verify:

```powershell
python C:\Users\anise\code\Dev-Management\scripts\check_windows_app_local_readiness.py --json
```
