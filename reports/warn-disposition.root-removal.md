# WARN Disposition

- Status: BLOCKED

## Entries
- path_preflight.env_absent :: ACCEPTED_NONBLOCKING :: app=false :: code=false :: .env is optional and absent in this workspace.
- path_preflight.direnv_missing :: ACCEPTED_NONBLOCKING :: app=false :: code=false :: direnv is not installed on this machine.
- windows_app.global_state_backups :: MANUAL_REMEDIATION :: app=false :: code=false :: External Windows Codex app-state backups predate this root-removal pass.
- global_runtime.client_path_contamination :: ACCEPTED_NONBLOCKING :: app=false :: code=false :: Codex App client session still injects /mnt/c-backed launcher and tmp arg0 paths into PATH.
- toolchain.workspace_dependency_tools_disabled :: ACCEPTED_NONBLOCKING :: app=false :: code=false :: Workspace dependency tools are disabled in current Codex App settings.
- startup.serena_onboarding :: MANUAL_REMEDIATION :: app=false :: code=true :: Serena onboarding has not been completed for /home/andy4917/Dev-Management.
- startup.serena_activation :: MANUAL_REMEDIATION :: app=false :: code=true :: Latest Serena MCP log shows the session started without activating the current project.
- global_runtime.app_project_unobserved :: MANUAL_REMEDIATION :: app=true :: code=false :: Codex App has not yet proven that /home/andy4917/Dev-Management opened on devmgmt-wsl after cleanup.
