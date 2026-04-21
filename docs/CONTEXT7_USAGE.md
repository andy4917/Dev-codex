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

- this workspace renders Context7 only in remote HTTP mode
- the canonical config block is:

```toml
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
enabled = true
required = false
tool_timeout_sec = 30
env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }
```

- `CONTEXT7_API_KEY` may come from the current shell env or the Windows user/machine environment
- `bearer_token_env_var` is not a valid Context7 transport field in this workspace and must be stripped from generated Codex configs

The generated runtime keeps:

- `enabled = true`
- `required = false`
- `tool_timeout_sec = 30`

## Runtime Source

- global config: `~/.codex/config.toml` is the runtime source of truth
- repo config: `.codex/config.toml` is a Linux trusted-project support surface
- Windows `.codex` is app runtime state and evidence only; Dev-Management must not generate Context7-related policy mirrors there

## Evidence

Protected dependency/config changes must leave `reports/context7-usage.json` with:

- `query`
- `resolved_library_id`
- `docs_retrieved`
- `version_evidence`
- `decision_summary`

If the change only configures Context7 itself, `check_context7.py` may auto-generate a self-configuration evidence entry. All other protected changes require an explicit evidence entry.
