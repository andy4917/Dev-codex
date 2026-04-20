# Serena Usage

## Default Rule

- install Serena with `uv tool install -p 3.13 serena-agent@latest --prerelease=allow`
- initialize Serena with `serena init`
- create project metadata with `cd <repo> && serena project create --index`
- in Codex, activate the current project with Serena before major code work
- check onboarding and project memories before large edits
- prefer Serena symbol and reference tools over repeated whole-file reads when Serena is available

Serena is a startup gate, not an optional suggestion, when the current diff requires code changes in the authority repo.

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
- `python scripts/check_startup_workflow.py` turns the Serena-first startup sequence into a deterministic repo-level verify surface
- the checker reads the latest Serena MCP log and surfaces the common `not activating any project` failure mode instead of relying on prompt memory
- when authority declares `ssh-devmgmt-wsl`, startup verification is fail-closed around the canonical SSH runtime rather than silently falling back to a contaminated local runtime

Current expected blocked state for Dev-Management:

- repo-local `.serena` metadata is missing
- latest Serena MCP log shows `not activating any project`
- these conditions must remain reported as `BLOCKED` until the runtime is repaired deliberately

## Repair Boundary

- Do not auto-create `.serena` metadata unless the schema is deterministically confirmed.
- When the schema is not confirmed, `check_startup_workflow.py` should emit repair advice and manual remediation only.
- When `serena project index` is available and explicitly chosen, it is the only allowed deterministic metadata repair path for this repo in the current migration state.
- Onboarding memory remains manual until a deterministic Serena CLI or MCP surface is confirmed for that workflow.
- Do not treat Windows-side Serena state as authoritative for the Linux repo.
- Do not claim Serena readiness from prompt memory; use project metadata, onboarding memories, and the latest MCP log.

## First-Time Flow

1. `uv tool install -p 3.13 serena-agent@latest --prerelease=allow`
2. `serena init`
3. `cd <repo> && serena project create --index`
4. In Codex, ask Serena to activate the current project
5. Run onboarding, review created memories, and start a fresh task thread

## Startup Pairing With Context7

- Use Serena first to activate the project and load onboarding context.
- Use Context7 first when the planned change touches external libraries, frameworks, APIs, protected configuration, or migration behavior.
- If Serena or Context7 is unavailable, report the blocker and continue only with an explicit fallback that does not invent missing evidence.
