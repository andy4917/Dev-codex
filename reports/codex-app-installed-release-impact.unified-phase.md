# Codex App Installed Release Impact

- Status: PASS
- Installed app: OpenAI.Codex
- Installed version: 26.417.4842.0
- Install/update date: 2026-04-21
- Installed build matches 2026-04-21 evidence: true
- Installed app evidence wins over public changelog wording: true

## Operational Conclusion
- Codex App is the primary user control surface and remote session control surface.
- Windows host is the app host and SSH client surface.
- devmgmt-wsl is the canonical remote execution surface.
- Linux-native Codex CLI on the remote login-shell PATH is the canonical agent binary.
- Dev-Management remains the policy and runtime authority.
- Windows-mounted Codex launcher remains a forbidden primary runtime.

## Feature Surfaces
- remote connections: PASS — Codex App is the main UI for opening devmgmt-wsl remote projects while Dev-Management remains authority.
- Windows WSL agent selection: PASS — Windows host stays app_host/ssh_client_surface and devmgmt-wsl stays canonical_remote_execution_surface.
- integrated terminal and multiple terminals: WARN — Terminal-specific PATH drift becomes evidence, not default authority.
- plugins / skills / plugin-provided MCP: PASS — Plugins and MCP are toolchain surfaces with provenance, not authority sources.
- projectless chats / memories / chronicle: WARN — App memory is a hint only and projectless code modification without repo root stays blocked.
- automations / worktrees / local environments / browser / computer use / settings sync / app server: WARN — They are audit surfaces but cannot replace authority or canonical runtime.
