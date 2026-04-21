# App Restart Required

- Windows `.codex` policy mirrors created by Dev-Management were removed or quarantined.
- Codex App must be restarted.
- Open Settings > Connections > `devmgmt-wsl`.
- Open `/home/andy4917/Dev-Management`.
- Do not recreate Windows `.codex/config.toml`, Windows `.codex/AGENTS.md`, Windows `.codex/hooks.json`, or Windows `.codex/skills`.
- If app settings still show AGENTS or dependency warnings after restart, report app state evidence; do not recreate mirrors.

Readiness prompt:

`Run Dev-Management readiness after Windows mirror removal and report APP_READY / APP_READY_WITH_WARNINGS / APP_NOT_READY. Do not modify code unless runtime, config provenance, Serena/Context7, score, and audit gates allow it.`
