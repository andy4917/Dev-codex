# Global Runtime Architecture

## Verdict

The canonical runtime model is Windows-native only.

- App control plane: `C:\Users\anise\.codex` (`USER_CONTROL_PLANE + APP_STATE`, not repo authority)
- Canonical workspace: `C:\Users\anise\code`
- Policy and verification authority: `C:\Users\anise\code\Dev-Management`
- Workflow assets: `C:\Users\anise\code\Dev-Workflow`
- Product repos: `C:\Users\anise\code\Dev-Product`

Linux/remote execution is decommissioned for steady state. Migration evidence remains only under `C:\Users\anise\code\Dev-Management\reports\migration-evidence` until the user explicitly removes those records.

## Authority Split

- Dev-Management owns environment policy, path authority, checks, gates, and final reports.
- Each repo owns its own stack/workflow rules through `AGENTS.md`, package scripts, and repo-local contracts.
- Codex App owns user intent, app settings, local sessions, plugins, skills, and live UI state.
- Docker is optional build, verification, packaging, and integration support, not the canonical development runtime.

## Required Baseline

- Codex App agent: Windows native
- Integrated terminal: PowerShell 7
- PowerShell policy surface: `Documents\PowerShell\policies\utf8.ps1`, `Documents\PowerShell\policies\native-args.ps1`, and a profile that dot-sources them.
- Codex config: `sandbox_mode = "danger-full-access"`, `approval_policy = "never"`, `[windows] sandbox = "elevated"`
- Git global EOL: `core.autocrlf=false`, `core.safecrlf=true`
- Repo EOL: `.gitattributes` controls LF/CRLF per repo

## Final Gate

Run from `C:\Users\anise\code\Dev-Management`:

```powershell
python scripts\check_windows_app_local_readiness.py --json
python scripts\check_user_dev_environment.py --json
```

Expected verdicts:

- App readiness: `APP_READY`
- User environment baseline: `PASS`
