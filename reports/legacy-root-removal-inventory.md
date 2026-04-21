# Legacy Root Removal Inventory

- Generated at: 2026-04-21T17:55:49.756409+00:00
- Removed: 7
- Inert archive: 4
- Manual remediation: 4
- Accepted nonblocking: 2

## Entries
- [REMOVE_NOW] REMOVED :: /home/andy4917/Dev-Management/quarantine/windows-codex-policy-mirrors/20260421-081829/AGENTS.md :: Stale Windows policy payload remained in quarantine even though remove-only root-cause cleanup requires payload deletion.
- [REMOVE_NOW] REMOVED :: /home/andy4917/Dev-Management/quarantine/windows-codex-policy-mirrors/20260421-081829/config.toml :: Stale Windows policy payload remained in quarantine even though remove-only root-cause cleanup requires payload deletion.
- [REMOVE_NOW] REMOVED :: /mnt/c/Users/anise/.codex/config.toml :: Windows .codex policy-bearing config was structurally stale Dev-Management residue.
- [REMOVE_NOW] REMOVED :: /mnt/c/Users/anise/.codex/config.toml.bak-20260422-004228 :: Policy-bearing backup copies are forbidden rollback surfaces for removed Windows .codex residue.
- [REMOVE_NOW] REMOVED :: /mnt/c/Users/anise/.codex/config.toml.bak-20260422-connections-restore :: Policy-bearing backup copies are forbidden rollback surfaces for removed Windows .codex residue.
- [REMOVE_NOW] REMOVED :: /mnt/c/Users/anise/.codex/AGENTS.md.bak-20260422-004228 :: Policy-bearing backup copies are forbidden rollback surfaces for removed Windows .codex residue.
- [REMOVE_NOW] REMOVED :: /mnt/c/Users/anise/.codex/AGENTS.md.bak-20260422-connections-restore :: Policy-bearing backup copies are forbidden rollback surfaces for removed Windows .codex residue.
- [INERT_ARCHIVE] RETAINED :: /home/andy4917/Dev-Management/quarantine/2026-04-16/MANIFEST.json :: Manifest is retained as inert forensic context and is not executable, importable, or restoreable by automation.
- [INERT_ARCHIVE] RETAINED :: /home/andy4917/Dev-Management/quarantine/artifact-hygiene/20260421-102140/MANIFEST.json :: Manifest is retained as inert forensic context and is not executable, importable, or restoreable by automation.
- [INERT_ARCHIVE] RETAINED :: /home/andy4917/Dev-Management/quarantine/windows-codex-policy-mirrors/20260421-081829/MANIFEST.json :: Manifest is retained as inert forensic context and is not executable, importable, or restoreable by automation.
- [INERT_ARCHIVE] RETAINED :: /home/andy4917/Dev-Management/quarantine/windows-codex-policy-mirrors/20260421-111515/MANIFEST.json :: Manifest is retained as inert forensic context and is not executable, importable, or restoreable by automation.
- [MANUAL_REMEDIATION] PRESENT :: /mnt/c/Users/anise/.codex/.codex-global-state.json.bak-20260422-global-state-full-repair :: External app-state backup is not Dev-Management authority, but should be manually reviewed outside repo automation.
- [MANUAL_REMEDIATION] PRESENT :: /mnt/c/Users/anise/.codex/.codex-global-state.json.bak-20260422-host-alias-hardening :: External app-state backup is not Dev-Management authority, but should be manually reviewed outside repo automation.
- [MANUAL_REMEDIATION] PRESENT :: /mnt/c/Users/anise/.codex/.codex-global-state.json.bak-20260422-last-chance-fix :: External app-state backup is not Dev-Management authority, but should be manually reviewed outside repo automation.
- [MANUAL_REMEDIATION] PRESENT :: /mnt/c/Users/anise/.codex/.codex-global-state.json.bak-20260422-remote-app-fix :: External app-state backup is not Dev-Management authority, but should be manually reviewed outside repo automation.
- [ACCEPTED_NONBLOCKING] PRESENT :: /mnt/c/Users/anise/.codex/bin/wsl/codex :: Protected Windows Codex launcher binary must remain untouched; only its promotion to primary runtime is forbidden.
- [ACCEPTED_NONBLOCKING] PRESENT :: /mnt/c/Users/anise/.codex/tmp/arg0 :: Client PATH contamination remains observable but canonical SSH runtime and Linux-native Codex CLI are now PASS.
