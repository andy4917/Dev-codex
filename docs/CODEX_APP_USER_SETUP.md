# Codex App User Setup

1. Restart Codex App.
2. Open Settings > Connections.
3. Enable or select SSH host devmgmt-wsl.
4. Open remote project /home/andy4917/Dev-Management.
5. Sign in if prompted.
6. Pin or keep the Dev-Management Control thread.
7. Send this readiness prompt:

   Run Dev-Management app usability readiness check and report PASS/WARN/BLOCKED. Do not modify code unless runtime, config provenance, startup, Context7, and score gates allow it.

8. For readiness and maintenance routing, keep using the Dev-Management Control thread.
9. Use separate Worktree mode only for scoped implementation tasks.
10. For normal work, type the task normally in the app.

Do not manually edit config.toml, AGENTS.md, hooks.json, PATH, ~/.local/bin/codex, Windows launcher files, /etc/wsl.conf, or Git global/system config unless a Dev-Management report explicitly instructs it.
