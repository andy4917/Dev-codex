param(
    [string]$TaskName = "DevManagementCodexAppMaintenance",
    [string]$RepoRoot = "C:\Users\anise\code\Dev-Management",
    [string]$Python = "python",
    [string]$RunAt = "04:30",
    [int]$IntervalMinutes = 240
)

$ErrorActionPreference = "Stop"

$script = Join-Path $RepoRoot "scripts\run_codex_app_maintenance_scheduled.ps1"
# The Python parameter is retained for CLI compatibility; the scheduled wrapper resolves python on PATH.
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $RepoRoot
$dailyTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At ([DateTime]::ParseExact($RunAt, "HH:mm", $null)) `
    -RepetitionInterval ([TimeSpan]::FromMinutes($IntervalMinutes)) `
    -RepetitionDuration ([TimeSpan]::FromDays(3650))
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($dailyTrigger, $logonTrigger) -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Registered scheduled task: $TaskName"
