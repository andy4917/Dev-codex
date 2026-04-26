# Agent Guardrails

## Default Stance

- Follow [GLOBAL_AGENT_WORKFLOW.md](./GLOBAL_AGENT_WORKFLOW.md).
- Treat Codex App as the UI and Windows-native execution control plane.
- Treat `windows-native` as the canonical execution surface.
- Treat the Windows-native Codex App agent as the canonical agent binary.
- Treat Dev-Management docs/contracts/checkers as runtime and workflow authority.
- Treat `C:\Users\anise\.codex` as the validated Codex App user control plane.

## Evidence Rules

- Use Serena for codebase semantic evidence.
- Use Context7 for external documentation evidence.
- Use product docs or Domain RAG for business/domain evidence.
- Treat Skills as workflow modules, not factual authority.
- Do not fabricate evidence.

## Editing Rules

- Read repo `AGENTS.md` before modifying code.
- Use package scripts as the command authority for that repo.
- Do not move repo stack or product policy into Windows `.codex`.
- Validate Windows `.codex` and report blocked authority-breaking settings, but do not overwrite it by default.
- Do not generate or restore Windows `.codex` policy mirrors.
- Do not use legacy Linux, SSH remote routes, or mounted launchers as governed runtime.
- Do not use mounted Linux paths as governed repo roots.
- Treat Docker as build/verification/packaging support only; `direnv` and dotfile managers are optional bootstrap surfaces.

## Verification Rules

- Exploration, artifact, clean execution, and verification are mandatory.
- Verification requires Happy Path, Error Case A, and Error Case B, plus repo lint/test/typecheck/build/preflight when available.
- Static analysis, dynamic testing, technical review, audit, and test documentation are valid quality gates.
- Report remaining WARN/BLOCKED dispositions explicitly.
