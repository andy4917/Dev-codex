# Global Agent Workflow

## Runtime Model

- Codex App is the user UI and Windows-native execution control plane.
- `C:\Users\anise\.codex` is `USER_CONTROL_PLANE + APP_STATE`, not repo authority.
- The user's explicit instruction is the highest project authority inside allowed system/developer constraints.
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

## Subagent Delegation

- before broad multi-surface audits, global cleanup, dirty closeout, policy/checker changes, L2+ verification, or explicit exhaustive file/folder review requests, decide whether subagents are applicable
- use `read_only_scouts` for parallel repo/app-state/report classification and evidence gathering
- use `verification_pair` for independent final-claim or line-reference verification when L2+ claims depend on broad evidence
- use `bounded_workers` only when write scopes are concrete, disjoint, and assigned before spawning
- if a triggered task remains `none` or `main_only`, record the waiver in `DELEGATION_DECISION.json` or `WORKORDER.json` using an allowed reason
- allowed waiver reasons are `critical_path_live_restart`, `narrow_leaf_change`, `tool_unavailable`, `no_parallelizable_sidecar`, and `plan_mode_read_only`
- subagent results must record evidence references and tool-surface gaps such as missing Serena availability; tool gaps require an explicit fallback path

Codex App performance maintenance:

- for restart, hover, renderer/GPU, stale-thread, or log-growth issues, run `python scripts/maintain_codex_app_state.py --json` first
- apply cleanup with `python scripts/maintain_codex_app_state.py --apply` only after the report identifies stale restore refs or old volatile logs
- keep only 1 day of logs in original live form; compress every older log row/file into durable maintenance archives
- keep session cleanup bounded by the configured maximum live session file count, currently 60 live session JSONL files
- run the recurring app maintenance cycle at logon and every 240 minutes; the cycle applies app-state maintenance and stale Serena/resource-health cleanup
- do not leave backups in `C:\Users\anise\.codex`; retain compressed archives under `C:\Users\anise\.codex\maintenance-archives`
- when the user gives a retention threshold or maximum file count, treat it as binding and report any skipped surface explicitly
- backups and temporary cleanup artifacts must not be retained in active workspace or `.codex` paths; dispose them through the Windows Recycle Bin
- compressed log/session archives under `C:\Users\anise\.codex\maintenance-archives` are durable retention evidence, not backup fallback roots

Scorecard hook:

- the approved Windows `hooks.json` surface is the generated scorecard `UserPromptSubmit` hook only
- the hook must run once per task turn with `user_prompt_throttle_seconds = 0` so the score layer cannot be silently skipped
- the hook is a trigger/binding reminder only; `iaw_closeout.py`, `delivery_gate.py`, tests, audits, and final reports remain the final gates

## Quality Gate

Production-grade work should include:

- happy path verification
- at least one relevant failure/error case
- touched-code runtime verification against actual behavior, not inferred behavior
- repo lint/test/typecheck/build/preflight when available
- a clear final verdict that distinguishes proof from assumption

## Reasoning And Quality Terms

- Think again / explain why: before asserting status, approval, readiness, or PASS, re-check the declared scope, oracle, evidence, and counterexamples, then explain the reason for the claim.
- Test: limited exploration for counterexamples plus partial evidence of expected behavior.
- Verification: checking whether current artifacts match the declared oracle, scope, and policy.
- Review: adversarial reading that exposes hidden assumptions, missing counterexamples, wrong oracles, and oversimplification.
- PASS: no counterexample was found inside the currently declared scope and oracle; it is not universal proof or formal approval.
- Formal approval: only an explicit user, reviewer, or gate authority can approve; tests, verification output, and PASS language alone do not grant approval.

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
