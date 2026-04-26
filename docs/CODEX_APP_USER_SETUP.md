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

Keep global custom instructions to this exact concise authority capsule. Repo-specific stack, commands, and workflow rules belong in each repo's `AGENTS.md` and package scripts.

```text
Global authority capsule:
- The user's explicit instruction is the highest project authority inside allowed system/developer constraints.
- Before work, read and follow:
C:\Users\anise\code\Dev-Management\docs\GLOBAL_AGENT_WORKFLOW.md

- Codex App is my UI and Windows-native execution control plane. Repo-specific stack and commands come from that repo's AGENTS.md and package scripts.

- Use Serena for codebase exploration, Context7 for external docs, and tests/reports for final claims. If required evidence is missing, report the gap and do not fabricate it.

- Always run the exact code path touched before claiming behavior; exercise all touched functions directly when practical, and use C:\Users\anise\code\.scratch\Dev-Management scratch harnesses to copy relevant production context and observe actual behavior.
- Test means limited counterexample search plus partial evidence; verification means declared oracle/scope/policy match; review means adversarial reading; PASS means no counterexample found within declared scope/oracle, not formal approval.
```

AI packages, MCP evidence roles, marketplace skills, and marketplace hooks are defined in [AI_TOOLCHAIN_USAGE.md](./AI_TOOLCHAIN_USAGE.md).

The approved global hook surface is the Dev-Management scorecard `UserPromptSubmit` hook only. Install or verify it with:

```powershell
python C:\Users\anise\code\Dev-Management\scripts\install_scorecard_runtime_hook.py --apply --json
```

Current under-development app feature flags should be limited to the observed supported set: `apps`, `memories`, `plugins`, `tool_search`, `tool_suggest`, and `tool_call_mcp_elicitation`. Do not enable `workspace_dependencies` as an app feature flag unless the live app starts accepting it.

Verify:

```powershell
python C:\Users\anise\code\Dev-Management\scripts\check_windows_app_local_readiness.py --json
```
