# AI Toolchain Usage

This document fixes the Windows-only toolchain roles for governed Codex work.

## Runtime Roles

- Codex App and Codex CLI are external OpenAI products. Use them as installed; do not fork, wrap, or treat local config as product source code.
- Dev-Management and Dev-Workflow are Python-first repositories for checkers, score, audit, oracle, RAG, and Serena/Context7 gates.
- Product repositories keep their own stack. If a product repo is Node/TypeScript, use its repo-owned package scripts and TypeScript workflow.
- App-integrated tools or plugins authored locally should be TypeScript-first unless the plugin contract explicitly requires another runtime.

## Python AI Packages

- `openai-agents` is the OpenAI Agents Python SDK.
- `langchain` is available for RAG and integration work when a repo contract or task requires it.
- `langgraph` is available for workflow graphs and agent orchestration when a repo contract or task requires it.
- `mcp` is available for Python MCP client/server integration support.

These packages do not become policy authority by being installed. Contracts, checkers, tests, and final reports remain the authority for environment claims.

## MCP And Evidence

- Context7 is external library/framework/API documentation evidence.
- Serena is codebase semantic retrieval, impact mapping, and refactor evidence.
- Domain RAG and product docs are business/domain requirement evidence.
- If Serena, Context7, or domain evidence is unavailable in the active harness, report that gap and do not fabricate the evidence.

## Marketplace Skill

Installed skill:

```text
C:\Users\anise\.agents\skills\minimalist-skill
```

Role:

- optional UI workflow style module
- workflow-only, not factual or policy authority
- lower priority than system/developer instructions, repo `AGENTS.md`, product design systems, and accessibility requirements

Important conflict rule:

- If the skill conflicts with Codex frontend instructions or repo UI rules, the higher-priority instructions win.

## Marketplace Hooks

Installed hooks:

```text
none
```

Role:

- Windows Codex hooks are disabled for the user/app control plane.
- PostToolUse hooks caused repeated hook runs and could launch `.sh` files through the Windows file association path.
- Hooks remain trigger-only when used in another controlled context; they are never Dev-Management policy authority or a replacement for tests, score gates, audit, or final reports.

Required app flag:

```toml
[features]
# codex_hooks must be absent in the Windows user control plane.
```

Dev-Management validates active Windows `hooks.json` as a removable hook surface instead of an approved marketplace exception.

## Adoption Status

The intended steady state is:

- Python packages installed in the active Windows Python environment.
- `C:\Users\anise\AppData\Roaming\Python\Python314\Scripts` present in the PowerShell profile PATH.
- Marketplace skill installed under `C:\Users\anise\.agents\skills`.
- No active marketplace hooks under `C:\Users\anise\.codex\hooks`.
- `C:\Users\anise\.codex\config.toml` does not enable `codex_hooks`.
