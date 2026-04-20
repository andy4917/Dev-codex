# Agent Guardrails

## Default Stance

- Treat Dev-Management as the authority repo.
- Treat Codex App as a user surface only.
- Treat Windows host as a client and UI surface only.
- Treat `ssh-devmgmt-wsl` as the canonical execution runtime.
- Treat Windows-mounted launchers as external dependencies, never as authority.

## Hard Blocks

The instruction guard must return `BLOCKED` for requests that:

- make the Windows launcher the primary runtime
- reintroduce `/mnt/c/Users/anise/.codex/bin/wsl` or `.codex/tmp/arg0` as preferred PATH targets
- ask for manual edits to generated config or shim files
- ask to modify code while Serena activation is still blocked
- ask for protected changes without real Context7 evidence
- ask to clean, revert, delete, or format unrelated dirty changes
- ask for destructive commands
- weaken sandbox or approval settings below the authority guard
- force Windows Git and WSL Git to be mixed as one execution surface

## Warnings

The instruction guard should return `WARN` when:

- the refactor scope is broad but not specific
- the requested test plan is missing
- app, CLI, IDE, and runtime surfaces are mixed together
- local and remote execution surfaces might not match
- the change is adjacent to protected files but not clearly protected
- Windows and WSL Git drift exists but the impact is not yet proven

## Bootstrap Exception

- The bootstrap implementation exception is process-local only.
- It must be enabled explicitly with `--activation-bootstrap`.
- Older wrappers may still pass `--bootstrap-implementation-exception` as a compatibility alias, but new guidance should use `--activation-bootstrap`.
- It must not be persisted in `contracts/instruction_guard_policy.json`.
- It does not allow Windows launcher promotion, forbidden PATH reintroduction, generated file hand edits, destructive commands, unrelated cleanup, sandbox weakening, or Context7 bypass.
- It is scoped to canonical runtime activation and Serena/bootstrap repair only. General code modification remains blocked while Serena startup is incomplete.

## Standard Reminder Messages

- runtime authority conflict: local runtime does not match the canonical SSH authority
- Serena-first unmet: project activation, metadata, or onboarding is incomplete
- Context7 evidence missing: protected change requires fresh `reports/context7-usage.json`
- unrelated dirty changes present: report them and leave them untouched
- destructive command blocked: capture the needed manual step in a remediation report instead
- sandbox or approval weakening blocked: authority guard cannot be relaxed by instruction text

## Editing Rules

- Do not hand-edit generated config or shim files.
- Do not overwrite live `~/.local/bin/codex` until canonical SSH readiness and local PATH precedence are both PASS.
- Prefer preview outputs under `reports/generated-runtime-preview/` while readiness is incomplete.
- If a system change is required, document it in `reports/manual-system-remediation-<timestamp>.md`.
