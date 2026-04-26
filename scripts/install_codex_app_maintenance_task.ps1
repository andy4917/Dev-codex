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

try {
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
} catch {
    Write-Warning "ScheduledTasks module failed, falling back to schtasks.exe: $($_.Exception.Message)"
    $taskCommand = "powershell.exe $arguments"
    schtasks.exe /Create /TN $TaskName /TR $taskCommand /SC MINUTE /MO $IntervalMinutes /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed to register recurring task: $TaskName"
    }
    schtasks.exe /Create /TN "$TaskName-Logon" /TR $taskCommand /SC ONLOGON /F | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Output "Registered scheduled tasks with schtasks.exe fallback: $TaskName, $TaskName-Logon"
    } else {
        Write-Warning "Registered recurring scheduled task only; ONLOGON fallback task requires a permission surface unavailable in this session."
        Write-Output "Registered scheduled task with schtasks.exe fallback: $TaskName"
    }
}
