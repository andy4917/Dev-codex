# Codex App Usability

- Status: APP_READY_WITH_WARNINGS
- Windows App SSH readiness: PASS
- Canonical SSH runtime: PASS
- Remote codex: PASS
- Linux-native Codex CLI: PASS
- Config provenance: PASS
- Generated AGENTS: PASS
- Auth readiness: PASS
- Serena status: WARN
- Score status: WARN
- Audit status: WARN

## Status Reasons
- Canonical runtime is usable with warnings.
- Serena still blocks general code modification, but app setup/readiness can proceed.
- Toolchain surface still reports warnings.
- Artifact hygiene still reports warnings.
- Audit still reports warnings.
- Score layer still reports warnings.

## User Actions
- Restart Codex App.
- Open Settings > Connections.
- Enable or select devmgmt-wsl.
- Open remote project /home/andy4917/Dev-Management.
- Complete sign-in if prompted.
- Send the readiness prompt in the app.
