# App Restart After Root-Cause Closeout V2

- Windows generated config/AGENTS/hooks were removed or quarantined earlier.
- Windows `skills/dev-workflow` disposition is now resolved.
- Windows SSH readiness is kept as bootstrap only.
- Dev-Management no longer generates Windows `.codex` policy surfaces.
- Codex App must be restarted.
- Open `Settings > Connections > devmgmt-wsl`.
- Open `/home/andy4917/Dev-Management`.
- Do not recreate Windows `.codex/config.toml`, `AGENTS.md`, `hooks.json`, or `skills`.
- If warnings remain after restart, collect app state evidence; do not reintroduce mirrors.

Readiness prompt:

`Run Dev-Management readiness after Windows .codex root-cause cleanup and report APP_READY / APP_READY_WITH_WARNINGS / APP_NOT_READY. Do not modify code unless runtime, config provenance, Serena/Context7, score, and audit gates allow it.`
