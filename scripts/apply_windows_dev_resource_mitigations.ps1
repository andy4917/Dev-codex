param(
    [string[]]$Paths = @(
        "C:\Users\anise\code",
        "C:\Users\anise\.codex",
        "C:\Users\anise\AppData\Roaming\uv",
        "C:\Users\anise\AppData\Local\uv",
        "C:\Users\anise\AppData\Roaming\npm"
    ),
    [switch]$StopWindowsSearch,
    [switch]$SetWindowsSearchDemandStart,
    [switch]$DisableWindowsSearch,
    [switch]$StopDeliveryOptimization,
    [switch]$StopLenovoUdc,
    [switch]$Json
)

$ErrorActionPreference = "Continue"

function Test-IsElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Set-ServiceStartMode {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][ValidateSet("Automatic", "Manual", "Disabled")][string]$Mode
    )
    $result = [ordered]@{
        service = $Name
        requested_mode = $Mode
        actions = @()
        failed = @()
    }
    try {
        Set-Service -Name $Name -StartupType $Mode -ErrorAction Stop
        $result.actions += "set_service_$Mode"
        return $result
    } catch {
        $result.failed += "set_service_$($Mode): $($_.Exception.Message)"
    }

    $scMode = switch ($Mode) {
        "Automatic" { "auto" }
        "Manual" { "demand" }
        "Disabled" { "disabled" }
    }
    $scOutput = & sc.exe config $Name start= $scMode 2>&1
    if ($LASTEXITCODE -eq 0) {
        $result.actions += "sc_config_$scMode"
    } else {
        $result.failed += "sc_config_$($scMode): $($scOutput -join ' ')"
    }
    return $result
}

$isElevated = Test-IsElevated
$rows = [ordered]@{
    elevated = $isElevated
    paths = @()
    defender = [ordered]@{
        attempted = @()
        added = @()
        existing = @()
        failed = @()
    }
    windows_search = [ordered]@{
        stop_requested = [bool]$StopWindowsSearch
        demand_start_requested = [bool]$SetWindowsSearchDemandStart
        disable_requested = [bool]$DisableWindowsSearch
        status_before = $null
        status_after = $null
        start_type_after = $null
        actions = @()
        failed = @()
    }
    services = @()
}

try {
    $svcBefore = Get-Service -Name WSearch -ErrorAction Stop
    $rows.windows_search.status_before = $svcBefore.Status.ToString()
} catch {
    $rows.windows_search.failed += "query_before: $($_.Exception.Message)"
}

foreach ($path in $Paths) {
    $item = [ordered]@{
        path = $path
        exists = Test-Path -LiteralPath $path
        not_content_indexed = $false
        attribute_error = $null
    }
    if ($item.exists) {
        try {
            attrib +I $path | Out-Null
            $attrs = (Get-Item -LiteralPath $path -Force).Attributes
            $item.not_content_indexed = (($attrs -band [IO.FileAttributes]::NotContentIndexed) -ne 0)
        } catch {
            $item.attribute_error = $_.Exception.Message
        }
    }
    $rows.paths += [pscustomobject]$item
}

try {
    $preference = Get-MpPreference -ErrorAction Stop
    $current = @($preference.ExclusionPath)
    $rows.defender.existing = $current
    foreach ($path in $Paths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $rows.defender.attempted += $path
        if ($current -contains $path) {
            continue
        }
        try {
            Add-MpPreference -ExclusionPath $path -ErrorAction Stop
            $rows.defender.added += $path
        } catch {
            $rows.defender.failed += [pscustomobject]@{
                path = $path
                error = $_.Exception.Message
            }
        }
    }
} catch {
    $rows.defender.failed += [pscustomobject]@{
        path = $null
        error = $_.Exception.Message
    }
}

if ($DisableWindowsSearch) {
    $startMode = Set-ServiceStartMode -Name WSearch -Mode Disabled
    $rows.windows_search.actions += $startMode.actions
    $rows.windows_search.failed += $startMode.failed
} elseif ($SetWindowsSearchDemandStart) {
    $startMode = Set-ServiceStartMode -Name WSearch -Mode Manual
    $rows.windows_search.actions += $startMode.actions
    $rows.windows_search.failed += $startMode.failed
}

if ($StopWindowsSearch) {
    try {
        Stop-Service -Name WSearch -Force -ErrorAction Stop
        $rows.windows_search.actions += "stop_service"
    } catch {
        $rows.windows_search.failed += "stop_service: $($_.Exception.Message)"
    }
}

try {
    $svcAfter = Get-Service -Name WSearch -ErrorAction Stop
    $rows.windows_search.status_after = $svcAfter.Status.ToString()
    $rows.windows_search.start_type_after = $svcAfter.StartType.ToString()
} catch {
    $rows.windows_search.failed += "query_after: $($_.Exception.Message)"
}

if ($StopDeliveryOptimization) {
    $item = [ordered]@{
        service = "DoSvc"
        stop_requested = $true
        manual_start_requested = $true
        actions = @()
        status_after = $null
        start_type_after = $null
        failed = @()
    }
    $startMode = Set-ServiceStartMode -Name DoSvc -Mode Manual
    $item.actions = $startMode.actions
    $item.failed += $startMode.failed
    try {
        Stop-Service -Name DoSvc -Force -ErrorAction Stop
    } catch {
        $item.failed += "stop_service: $($_.Exception.Message)"
    }
    try {
        $svc = Get-Service -Name DoSvc -ErrorAction Stop
        $item.status_after = $svc.Status.ToString()
        $item.start_type_after = $svc.StartType.ToString()
    } catch {
        $item.failed += "query_after: $($_.Exception.Message)"
    }
    $rows.services += [pscustomobject]$item
}

if ($StopLenovoUdc) {
    $item = [ordered]@{
        service = "UDCService"
        stop_requested = $true
        manual_start_requested = $true
        actions = @()
        stopped_processes = @()
        status_after = $null
        start_type_after = $null
        failed = @()
    }
    $startMode = Set-ServiceStartMode -Name UDCService -Mode Manual
    $item.actions = $startMode.actions
    $item.failed += $startMode.failed
    try {
        Stop-Service -Name UDCService -Force -ErrorAction Stop
    } catch {
        $item.failed += "stop_service: $($_.Exception.Message)"
    }
    foreach ($proc in Get-Process -Name UDClientService, UDCUserAgent, MessagingPlugin -ErrorAction SilentlyContinue) {
        try {
            $item.stopped_processes += [pscustomobject]@{
                pid = $proc.Id
                name = $proc.ProcessName
            }
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        } catch {
            $item.failed += "stop_process_$($proc.Id): $($_.Exception.Message)"
        }
    }
    try {
        $svc = Get-Service -Name UDCService -ErrorAction Stop
        $item.status_after = $svc.Status.ToString()
        $item.start_type_after = $svc.StartType.ToString()
    } catch {
        $item.failed += "query_after: $($_.Exception.Message)"
    }
    $rows.services += [pscustomobject]$item
}

$result = [pscustomobject]$rows
if ($Json) {
    $result | ConvertTo-Json -Depth 5
} else {
    $result
}
