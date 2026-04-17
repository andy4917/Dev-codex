# Context7 Usage

## Default Rule

Use Context7 before changing:

- libraries
- APIs
- frameworks
- configuration with external runtime implications
- migrations
- security-sensitive dependencies
- deprecations

## Config Targets

- global config: canonical Linux `~/.codex/config.toml`
- repo config: `.codex/config.toml`
- repo-local agent copies are not canonical and are not required.

## Selection Rule

- if `CONTEXT7_API_KEY` exists:
  - use remote HTTP mode
  - the key may come from the current shell env or the Windows user/machine environment
- else:
  - use `npx -y @upstash/context7-mcp`

Both modes keep:

- `enabled = true`
- `required = false`
- `startup_timeout_sec = 40`
- `tool_timeout_sec = 120`

## Evidence

Protected dependency/config changes must leave `reports/context7-usage.json` with:

- `query`
- `resolved_library_id`
- `docs_retrieved`
- `version_evidence`
- `decision_summary`

If the change only configures Context7 itself, `check_context7.py` may auto-generate a self-configuration evidence entry. All other protected changes require an explicit evidence entry.
