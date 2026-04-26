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
    [switch]$Json
)

$ErrorActionPreference = "Continue"

function Test-IsElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
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
        status_before = $null
        status_after = $null
        actions = @()
        failed = @()
    }
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

if ($SetWindowsSearchDemandStart) {
    try {
        sc.exe config WSearch start= demand | Out-Null
        $rows.windows_search.actions += "set_start_demand"
    } catch {
        $rows.windows_search.failed += "set_start_demand: $($_.Exception.Message)"
    }
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
} catch {
    $rows.windows_search.failed += "query_after: $($_.Exception.Message)"
}

$result = [pscustomobject]$rows
if ($Json) {
    $result | ConvertTo-Json -Depth 5
} else {
    $result
}
