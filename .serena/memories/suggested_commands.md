# Suggested Commands

Run from `C:\Users\anise\code\Dev-Management` in PowerShell 7 unless noted.

- `git status --short --branch` before edits.
- `python -m unittest tests.test_check_user_dev_environment` for environment baseline checker edits.
- `python -m unittest tests.test_global_agent_workflow` for workflow-policy edits.
- `python -m unittest tests.test_windows_app_resource_health tests.test_windows_process_burst tests.test_codex_app_maintenance_cycle tests.test_serena_dashboard_repro` for Codex/Serena/process health edits.
- `python scripts\check_user_dev_environment.py --json` for Windows-native environment baseline reports.
- `python scripts\check_global_agent_workflow.py --json` for global workflow policy/doc checks.
- `python scripts\check_windows_app_resource_health.py --cpu-sample-seconds 3 --json` for live Codex/Serena process health.
- `python scripts\check_windows_process_burst.py --duration-seconds 3 --json` for process fanout bursts.
- `ruff check .` after Python code edits when feasible.
- `biome check .` after JS/TS/config-facing edits when feasible and a compatible config exists.
- `git diff --check` before commit.
- `python scripts\iaw_closeout.py --workspace-root C:\Users\anise\code\Dev-Management --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify` before final score/gate/release claims.

Windows utilities: prefer `rg` for search, `Get-ChildItem` over `ls` in scripts, `Remove-Item -LiteralPath` for deletes, `Get-ExecutionPolicy -List` for execution policy issues, and `schtasks.exe` fallback when PowerShell ScheduledTasks/CIM fails.
