# Codex App User Setup

Windows generated `.codex/config.toml`, `AGENTS.md`, and hooks were removed earlier; they must not be recreated as fallback or backup surfaces.
Windows `.codex/skills/dev-workflow` has been resolved as stale residue and must not be recreated.
Windows `.codex` is app runtime state only, not path or policy authority.
Codex App `Settings > Connections` visibility depends on Windows `.codex/config.toml` keeping both `remote_control = true` and `remote_connections = true` under `[features]`; do not collapse that file to `remote_control` only.
Codex App SSH discovery is executed from WSL in this environment, so `C:/Users/...` identity paths can be discovered but then dropped during probe; use `IdentityFile ~/.ssh/codex_wsl_ed25519` and keep the same key name available in both Windows and WSL homes.

1. Restart Codex App.
2. Open Settings > Connections.
3. If `devmgmt-wsl` is listed, select it.
4. If it is not listed, use `Connections > Add host > devmgmt-wsl`.
5. Open remote project `${DEVMGMT_ROOT}`.
6. Sign in if prompted.
7. Report one exact result:

   - `listed + project opened`
   - `manual add worked + project opened`
   - `manual add failed`
   - `project open failed`
   - `sign-in blocker`

8. Pin or keep the Dev-Management Control thread.
9. Send this readiness prompt:

   Run Dev-Management readiness after Windows .codex root-cause cleanup and report APP_READY / APP_READY_WITH_WARNINGS / APP_NOT_READY. Do not modify code unless runtime, config provenance, Serena/Context7, score, and audit gates allow it.

10. For readiness and maintenance routing, keep using the Dev-Management Control thread.
11. Use separate Worktree mode only for scoped implementation tasks.
12. For normal work, type the task normally in the app.

Do not manually create or recreate Windows `.codex/config.toml`, Windows `.codex/AGENTS.md`, Windows `.codex/hooks.json`, or Windows `.codex/skills`.
If warnings remain after restart, collect app state evidence and keep Windows `.codex` as evidence-only state; do not restore mirrors, backups, or parity copies.
Tracked source rollback uses Git history. Generated output rollback uses deterministic regeneration, not backup copies.
Do not manually edit PATH, ~/.local/bin/codex, Windows launcher files, /etc/wsl.conf, or Git global/system config unless a Dev-Management report explicitly instructs it.
App readiness is not complete until Codex App proves that `${DEVMGMT_ROOT}` actually opened on `devmgmt-wsl` and Linux-native codex executed there.
