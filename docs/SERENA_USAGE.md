# Serena Usage

## Default Rule

- install Serena with `uv tool install -p 3.13 serena-agent@latest --prerelease=allow`
- initialize Serena with `serena init`
- create project metadata with `cd <repo> && serena project create --index`
- in Codex, activate the current project with Serena before major code work
- check onboarding and project memories before large edits
- prefer Serena symbol and reference tools over repeated whole-file reads when Serena is available

## Codex Config

The generated Codex runtime renders Serena in STDIO mode:

```toml
[mcp_servers.serena]
enabled = true
required = false
startup_timeout_sec = 15
tool_timeout_sec = 120
command = "serena"
args = ["start-mcp-server", "--project-from-cwd", "--context=codex"]
disabled_tools = ["execute_shell_command", "remove_project"]
```

## Readiness Semantics

- Serena is default-on for Codex runtime generation
- Serena readiness is advisory in `user-readiness.json` and `delivery-gate.json`
- Serena tool availability is still meaningful for editing and refactoring work; only the gate semantics are advisory
- Linux and Windows Serena executable readiness are reported separately

## First-Time Flow

1. `uv tool install -p 3.13 serena-agent@latest --prerelease=allow`
2. `serena init`
3. `cd <repo> && serena project create --index`
4. In Codex, ask Serena to activate the current project
5. Run onboarding, review created memories, and start a fresh task thread
