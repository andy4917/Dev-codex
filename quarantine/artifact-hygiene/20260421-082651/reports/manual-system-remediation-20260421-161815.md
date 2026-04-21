# Manual System Remediation

- Generated at: 2026-04-21 16:18:15
- Windows Codex app and /mnt/c/Users/anise/.codex/bin/wsl/codex are external dependencies and are not repo repair targets.
- Edit /etc/wsl.conf manually to include:
  [interop]
  enabled=true
  appendWindowsPath=false
  [boot]
  systemd=true
- After editing /etc/wsl.conf, restart WSL manually from PowerShell with: wsl.exe --shutdown
- Add or verify the user-level SSH alias in ~/.ssh/config.d/dev-management.conf and ensure ~/.ssh/config includes ~/.ssh/config.d/*.conf.
- If SSH authentication still fails, review authorized_keys markers, private key permissions, and known_hosts manually.
- Windows PATH is not repo-owned; if Codex app sessions keep injecting .codex/tmp/arg0 or .codex/bin/wsl, treat that as a client-surface warning and correct it outside the repo.
- Reconcile Windows Git and WSL Git config drift manually. Current Git surface status: WARN
- Review Windows Git safe.directory, credential helper, core.autocrlf, and LFS settings against the WSL Git configuration before using mixed surfaces.
- Current Codex app settings disable workspace dependency tools; enable Codex dependencies in the app before expecting load/install workspace dependency tools to work.
- Install or expose a Linux-native codex binary inside the canonical SSH runtime if remote native detection remains incomplete.
- The local PATH normalizer at ~/.config/shell/wsl-runtime-paths.sh is currently not repo-owned; update it manually if you want to strip .codex/tmp/arg0 or .codex/bin/wsl entries.
- Rollback for user-level SSH activation: remove ~/.ssh/config.d/dev-management.conf, remove the Dev-Management include block from ~/.ssh/config, remove the marker block from authorized_keys, and delete ~/.ssh/devmgmt_wsl_ed25519(.pub) if it was created solely for this runtime.
- Current canonical execution status: PASS
