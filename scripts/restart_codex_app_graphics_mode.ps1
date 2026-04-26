param(
    [ValidateSet("ForceLowPowerGpu", "CappedRendering", "ReducedUiControls", "DisableGpu")]
    [string]$Mode = "ForceLowPowerGpu",
    [int]$DelaySeconds = 5,
    [switch]$ClearRenderCache,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$appId = "OpenAI.Codex_2p2nqsd0c76g0!App"
$switchesByMode = @{
    ForceLowPowerGpu = @("--force_low_power_gpu")
    CappedRendering = @(
        "--force_low_power_gpu",
        "--renderer-process-limit=2",
        "--num-raster-threads=1"
    )
    ReducedUiControls = @(
        "--force_low_power_gpu",
        "--renderer-process-limit=2",
        "--num-raster-threads=2",
        "--disable-smooth-scrolling"
    )
    DisableGpu = @(
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-gpu-rasterization",
        "--disable-zero-copy",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-smooth-scrolling",
        "--renderer-process-limit=2",
        "--num-raster-threads=1",
        "--disable-features=CalculateNativeWinOcclusion"
    )
}

function Get-CodexExecutablePath {
    try {
        $live = Get-Process -Name Codex,codex -ErrorAction SilentlyContinue |
            Where-Object { $_.Path } |
            Where-Object { $_.Path -match '\\app\\Codex\.exe$' } |
            Select-Object -First 1 -ExpandProperty Path
        if ($live) {
            return $live
        }
    } catch {
    }

    try {
        $live = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -ieq "Codex.exe" -and $_.ExecutablePath } |
            Where-Object { $_.ExecutablePath -match '\\app\\Codex\.exe$' } |
            Select-Object -First 1 -ExpandProperty ExecutablePath
        if ($live) {
            return $live
        }
    } catch {
    }

    $packageRoot = Join-Path $env:ProgramFiles "WindowsApps"
    $candidate = Get-ChildItem -Path $packageRoot -Directory -Filter "OpenAI.Codex_*_x64__2p2nqsd0c76g0" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($candidate) {
        $path = Join-Path $candidate.FullName "app\Codex.exe"
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    return $null
}

$arguments = $switchesByMode[$Mode]
$codexExe = Get-CodexExecutablePath
$plan = [pscustomobject]@{
    mode = $Mode
    delay_seconds = $DelaySeconds
    executable = $codexExe
    arguments = $arguments
    fallback_app_id = $appId
    clear_render_cache = [bool]$ClearRenderCache
    dry_run = [bool]$DryRun
}

if ($DryRun) {
    $plan | ConvertTo-Json -Depth 3
    exit 0
}

Start-Sleep -Seconds $DelaySeconds
Get-Process -Name Codex,codex -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 4

if ($ClearRenderCache) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
    $maintainScript = Join-Path $repoRoot "scripts\maintain_codex_app_state.py"
    if (Test-Path -LiteralPath $maintainScript) {
        python $maintainScript --apply --cleanup-render-cache --max-log-rows 10000 --json | Out-Null
    }
}

$env:RUST_LOG = "warn"
$env:LOG_FORMAT = "json"
if ($codexExe -and (Test-Path -LiteralPath $codexExe)) {
    try {
        Start-Process -FilePath $codexExe -ArgumentList $arguments
        [pscustomobject]@{status = "started"; mode = $Mode; executable = $codexExe; arguments = $arguments} |
            ConvertTo-Json -Depth 3
        exit 0
    } catch {
        $fallbackReason = $_.Exception.Message
    }
} else {
    $fallbackReason = "Codex.exe path not found"
}

Start-Process explorer.exe "shell:AppsFolder\$appId"
[pscustomobject]@{
    status = "started_with_fallback"
    mode = $Mode
    fallback_app_id = $appId
    reason = $fallbackReason
} | ConvertTo-Json -Depth 3
