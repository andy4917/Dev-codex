# Global Agent Workflow

## Runtime Model

- Codex App is the user UI and Windows-native execution control plane.
- `C:\Users\anise\.codex` is `USER_CONTROL_PLANE + APP_STATE`, not repo authority.
- `C:\Users\anise\code` is the canonical workspace root.
- `C:\Users\anise\code\Dev-Management` is the environment policy and verification authority.
- Repo `AGENTS.md` and package scripts remain the repo-local stack/workflow authority.
- Repo `AGENTS.md`: stack/workflow authority for that repo.
- package scripts: command authority.
- AI/toolchain usage: [AI_TOOLCHAIN_USAGE.md](./AI_TOOLCHAIN_USAGE.md).
- Linux/remote execution authority is decommissioned. Migration evidence is retained under Dev-Management reports.

## Evidence Roles

- Context7: external library/framework/API documentation evidence.
- Serena: codebase semantic retrieval, impact mapping, and refactor evidence.
- Domain RAG/Product Docs: business/domain requirement evidence.
- Skills: repeatable workflow modules, not factual authority.
- Marketplace hooks: triggers only, not final gates.
- Tests and reports: final claim discipline.

## Work Cycle

Before modification:

- inspect git status
- classify dirty files and preserve unrelated changes
- read repo `AGENTS.md`
- inspect package scripts
- gather required Serena/Context7/RAG evidence
- frame material work as parent domain, parent objective, this-turn goal, done-when evidence, and closeout authority

After modification:

- run the exact code path that was touched, exercising all touched functions directly when practical
- refresh impacted authoritative artifacts or record WAIVED/BLOCKED before closeout
- use `C:\Users\anise\code\.scratch\Dev-Management\` for local scratch harnesses that copy relevant production code/config/data needed to observe actual production behavior
- run relevant lint/test/typecheck/build
- run `git diff --check`
- run Dev-Management checks for environment-level work
- report WARN/BLOCKED with disposition

## Quality Gate

Production-grade work should include:

- happy path verification
- at least one relevant failure/error case
- touched-code runtime verification against actual behavior, not inferred behavior
- repo lint/test/typecheck/build/preflight when available
- a clear final verdict that distinguishes proof from assumption

## Mission Refresh

- Material turns must preserve the parent objective instead of treating the latest prompt as the whole job.
- Dev-Workflow publishes mission frame and refresh artifacts under `.agent-runs/<run_id>/`.
- Dev-Management enforces L2+ closeout through tests, reports, checkers, receipts, and impacted artifact refresh.
- Windows hooks remain triggers only, not final gates.
- The standard is impacted authoritative artifact refresh, not blanket updates to every historical document.

## Forbidden

- fabricating missing evidence
- moving repo-specific stack rules into app global instructions
- treating skills as factual authority
- using Linux/remote execution as the steady-state runtime
- deleting migration evidence without a separate explicit cleanup request
