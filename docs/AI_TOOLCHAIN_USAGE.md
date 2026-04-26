# AI Toolchain Usage

This document fixes the Windows-only toolchain roles for governed Codex work.

Detailed Windows-native runtime/tool adoption is recorded in:

```text
C:\Users\anise\code\Dev-Management\docs\WINDOWS_NATIVE_TOOLCHAIN.md
```

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

## Scorecard Hook

Approved global hook:

```text
C:\Users\anise\.codex\hooks.json
```

Role:

- The only approved Windows Codex hook is the Dev-Management scorecard `UserPromptSubmit` hook.
- It runs once per task turn with no throttle and binds the score layer so it cannot be silently skipped.
- Hooks remain trigger-only; they are never Dev-Management policy authority or a replacement for tests, score gates, audit, or final reports.
- PostToolUse hooks remain blocked because they previously caused repeated runs and unsafe file-association launch paths.

Required app flag:

```toml
[features]
codex_hooks = true
```

Dev-Management validates Windows `hooks.json` as PASS only when it exactly matches the approved scorecard `UserPromptSubmit` payload.

## Under-Development App Features

Observed supported experimental feature names:

```text
apps, memories, plugins, tool_search, tool_suggest, tool_call_mcp_elicitation
```

`workspace_dependencies` is not an approved app experimental flag in the current Windows app surface. The app log reports it as unsupported for `experimentalFeature/enablement/set`, so Dev-Management must not require or enable it in `C:\Users\anise\.codex\config.toml`.

## Adoption Status

The intended steady state is:

- Python packages installed in the active Windows Python environment.
- Java, JavaScript, TypeScript, and Python development tools installed on the Windows-native control plane.
- Zod, zx, Python `shlex`, ruff, Biome, and Zig are part of the active global coding/toolchain baseline.
- Airbnb JavaScript Style Guide, Google Python Style Guide, Refactoring.Guru, 30 seconds of code, and Greptile are recorded as coding/review references, subordinate to repo contracts and tests.
- `.env.example` tracked as the repo-local variable contract, with local `.env` ignored by Git and loaded through npm `dotenv-cli`.
- Scoop shims, Java, Maven, Bun, npm globals, winget links, and Python script paths made visible in the PowerShell profile PATH.
- Everything HTTP enabled on `127.0.0.1:8088` with file downloads disabled and `C:\Users\anise\code` folder-indexed.
- `C:\Users\anise\AppData\Roaming\Python\Python314\Scripts` present in the PowerShell profile PATH.
- Marketplace skill installed under `C:\Users\anise\.agents\skills`.
- No active marketplace hooks under `C:\Users\anise\.codex\hooks`.
- `C:\Users\anise\.codex\config.toml` enables `codex_hooks` only for the approved scorecard runtime hook.
