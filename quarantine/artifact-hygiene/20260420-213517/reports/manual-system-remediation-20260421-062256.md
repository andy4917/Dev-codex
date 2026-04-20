# Manual System Remediation

## Scope
- This report lists remaining user-run or system-level actions that Dev-Management will not repair automatically.
- Windows Codex app binaries, Windows PATH, Windows Git global/system config, /etc/wsl.conf, system services, and external launchers remain outside repo repair authority.

## Remaining Manual Steps
- Update `/etc/wsl.conf` manually if cross-session Windows PATH contamination must be reduced:
  - `[interop]`
  - `enabled=true`
  - `appendWindowsPath=false`
  - `[boot]`
  - `systemd=true` only if your WSL setup is intended to manage `sshd` via systemd.
- From PowerShell, run `wsl.exe --shutdown` after any `/etc/wsl.conf` change so the next WSL session picks up the new interop policy.
- Clean Windows or app-injected PATH sources that still reintroduce `.codex/tmp/arg0` and `/mnt/c/Users/anise/.codex/bin/wsl` into client sessions.
- Review Windows Git global/system drift and stale `safe.directory` entries; keep Dev-Management authority in repo-level policy, not Windows global settings.
- Install or expose `git-lfs` inside WSL if LFS-backed repos must be handled on the canonical Linux execution surface.
- Complete Serena onboarding and actual project activation using confirmed Serena commands so startup can move from BLOCKED to PASS/WARN.
- Keep Windows Codex app binaries and `/mnt/c/Users/anise/.codex/bin/wsl/codex` untouched; they are external dependencies, not repo-owned repair targets.

## Current Runtime Notes
- Codex App is the primary user control surface and remote session control surface.
- devmgmt-wsl is the canonical remote execution surface.
- Linux-native Codex CLI is installed remotely and resolves first on the remote login-shell PATH.
- Local client PATH contamination remains a warning surface.
- Local shell direct execution remains blocked until the live wrapper is safely aligned.

## Rollback
- Remove the Windows user SSH marker block for `Host devmgmt-wsl` from `C:\Users\anise\.ssh\config` if you need to undo app-side SSH discovery.
- Remove `/home/andy4917/.config/shell/dev-management-codex-paths.sh` and the matching include block from `/home/andy4917/.zshenv` if you need to undo the remote Linux-native Codex PATH helper.
- Restore `/home/andy4917/.local/bin/codex` from backup or regenerate it from Dev-Management authority if the safe wrapper apply must be rolled back.
- Move quarantined generated task artifacts back from the latest `quarantine/artifact-hygiene/<timestamp>` folder if artifact cleanup needs to be reversed.
