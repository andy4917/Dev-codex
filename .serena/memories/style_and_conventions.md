# Style And Conventions

- Follow repo contracts and tests before external style guides.
- Python code uses type hints, small focused functions, explicit status payloads, and `unittest` coverage for changed checker behavior.
- Use `ruff check .` as the global Python lint guardrail when feasible.
- Use JSON contracts for machine-checkable policy and Markdown docs for human-facing operating rules.
- Prefer exact status labels (`PASS`, `WARN`, `BLOCKED`, `READY_WITH_WARNINGS`) and explicit reason strings over vague summaries.
- Preserve unrelated dirty work; do not revert user changes.
- Use PowerShell-native object handling on Windows; do not assume Unix text semantics behind aliases.
- For JS/TS work, use repo scripts first, then global Biome fallback; Zod is the preferred runtime schema tool and zx is the preferred JS shell-scripting tool when a repo allows it.
- For Python shell parsing/quoting, use standard-library `shlex` where appropriate instead of ad hoc splitting.
