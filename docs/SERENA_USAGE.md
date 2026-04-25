# Serena Usage

## Default Rule

- Serena remains a startup gate for general code modification in the authority repo.
- Run Serena from the local Windows project root, not from projectless or stale runtime assumptions.
- Treat project activation, onboarding, and latest activation evidence as deterministic checks, not prompt memory.

## Runtime Pairing

- Codex App drives the session with the Windows-native agent.
- Serena MCP must agree on the current local Windows repo root for authority work.
- Windows `.codex` app state is user control-plane state; Dev-Management contracts and repo files remain policy authority.

## Readiness Semantics

- metadata and index can be repaired only through deterministic Serena CLI or MCP paths
- onboarding memory cannot be forged
- latest `not activating any project` evidence keeps startup blocked until fresh activation proof exists
- if activation proof remains unavailable, only activation-bootstrap-scoped work is allowed
- app usability readiness may still be WARN rather than BLOCKED while Serena blocks general code modification

## Repair Boundary

- `serena project create --index` or equivalent deterministic indexing command is allowed when confirmed
- onboarding memory is report-only until a deterministic Serena command is confirmed
- never infer Serena readiness from app memory, restore seed, or projectless chat context

## Pairing With Context7

- Use Serena first to activate repo context for code work.
- Use Context7 first when the intended change touches external libraries, frameworks, APIs, configuration, or migration behavior.
- If Serena or Context7 is unavailable, report the blocker and use a clearly stated fallback without inventing evidence.
