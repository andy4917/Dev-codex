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

- app control-plane config: `C:\Users\anise\.codex\config.toml`
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

The app control-plane config keeps:

- `enabled = true`
- `required = false`
- `tool_timeout_sec = 30`

## Runtime Source

- `C:\Users\anise\.codex\config.toml` is the user/app control-plane config.
- repo config: `.codex/config.toml` is repo-local only when a product repo explicitly owns it.
- Dev-Management validates Context7 posture but does not mirror generated policy into product repos.

## Evidence

Protected dependency/config changes must leave `reports/context7-usage.json` with:

- `query`
- `resolved_library_id`
- `docs_retrieved`
- `version_evidence`
- `decision_summary`

If the change only configures Context7 itself, record the self-configuration evidence directly in `reports/context7-usage.json`. All other protected changes require an explicit evidence entry.
