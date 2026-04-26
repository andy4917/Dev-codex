$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $repoRoot

python .\scripts\run_codex_app_maintenance_cycle.py `
    --log-retention-days 1 `
    --max-log-rows 10000 `
    --max-session-files 60 `
    --output-file .\reports\codex-app-maintenance-cycle.scheduled-v2.json
