# Codex App Usability

- Status: APP_READY_WITH_WARNINGS
- Windows App SSH readiness: PASS
- Canonical SSH runtime: PASS
- Remote codex: PASS
- Linux-native Codex CLI: PASS
- Config provenance: PASS
- Generated AGENTS: PASS
- Control thread: PASS
- Canonical repo root: /home/andy4917/Dev-Management
- Active worktree root: /home/andy4917/Dev-Management
- Auth readiness: PASS
- Serena status: WARN
- Git surface: WARN
- Score status: WARN
- Audit status: WARN

## Status Reasons
- Canonical runtime is usable with warnings.
- Serena still blocks general code modification, but app setup/readiness can proceed.
- Toolchain surface still reports warnings.
- Hooks remain trigger-only advisory surfaces.
- Artifact hygiene still reports warnings.
- Audit still reports warnings.
- Score layer still reports warnings.
- Git surface still reports warnings.

## User Actions
- Restart Codex App.
- Open Settings > Connections.
- Enable or select devmgmt-wsl.
- Open remote project /home/andy4917/Dev-Management.
- Complete sign-in if prompted.
- Pin or keep the Dev-Management Control thread.
- Send the readiness prompt in the app.
- Use separate Worktree mode only for scoped implementation tasks.
