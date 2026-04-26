# Codex App Maintenance

Codex App state is a user control-plane surface, not repo authority. Dev-Management may sanitize it only for stale restore references, legacy runtime paths, and volatile log retention.

## Entry Points

- Dry run: `python scripts/maintain_codex_app_state.py --json`
- Apply: `python scripts/maintain_codex_app_state.py --apply`
- Full cycle: `python scripts/run_codex_app_maintenance_cycle.py --json`
- Resource-health CPU sample: the full cycle samples Codex App CPU for `3` seconds by default; set `--resource-cpu-sample-seconds 0` only when the machine is too sluggish to sample.
- Renderer/GPU/app-server evidence: `python scripts/check_windows_app_resource_health.py --cpu-sample-seconds 5 --json` records Codex CPU by subprocess role.
- Git worker loop evidence: the resource-health report flags dirty tracked files whose working-tree line endings are `CRLF` or mixed even though repo attributes require `eol=lf`; this catches `safecrlf` failures that can keep Codex App review/git workers busy.
- CPU sample unit: `codex_cpu_pct` is percent of one logical CPU; `codex_system_cpu_pct` is the system-normalized estimate using the current logical processor count.
- Low-power GPU preference: `python scripts/check_windows_app_resource_health.py --prefer-low-power-gpu --json` sets Windows per-app graphics preference for Codex executables to Power Saving; the setting takes effect after the next Codex App launch.
- Render cache cleanup: `python scripts/maintain_codex_app_state.py --apply --cleanup-render-cache --json` sends Codex Electron `Cache`, `Code Cache`, and `GPUCache` directories to the Recycle Bin. Use it immediately before app restart; persistent app state is not removed.
- Low-power GPU relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode ForceLowPowerGpu -ClearRenderCache` restarts Codex with Electron's `--force_low_power_gpu` switch after render-cache cleanup.
- Capped rendering relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode CappedRendering -ClearRenderCache` keeps GPU enabled while adding `--renderer-process-limit=2` and `--num-raster-threads=1`; use it before `-Mode DisableGpu` when renderer/GPU CPU remains high.
- Reduced UI controls relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode ReducedUiControls -ClearRenderCache` preserves the default UI scale while adding `--num-raster-threads=2` and `--disable-smooth-scrolling`. The observed default raster thread count was `4`, so `2` is the 50% reduction path without shrinking the UI. Do not force reduced-motion in the default path because thinking/loading indicators must remain visibly animated.
- Full GPU disable relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode DisableGpu -ClearRenderCache` exists only as a last-resort reproduction path for Windows GPU-rendering incidents because disabling GPU can move rendering work onto CPU.
- Analytics opt-out: `C:\Users\anise\.codex\config.toml` may set `[analytics] enabled = false`; Codex `app-server --help` documents this as the user opt-out for the app-server analytics default.
- Install recurring task: `pwsh scripts/install_codex_app_maintenance_task.ps1`
- Defaults: keep only `1` day of live original logs, keep at most `60` live session JSONL files, keep at most `10000` live SQLite log rows.

## What It Changes

- Removes legacy remote auto-connect state from `.codex-global-state.json`.
- Removes legacy workspace SID mappings from `.codex/cap_sid`.
- Sends ambient suggestions whose project root points to legacy or missing workspaces to the Recycle Bin.
- Marks stale `state_5.sqlite` threads archived instead of deleting them.
- Compresses stale or over-limit session JSONL files.
- Compresses Codex desktop log files older than 1 day.
- Exports old `logs_2.sqlite` rows to gzip, deletes exported rows, and attempts SQLite compaction.
- Optionally recycles renderer cache directories that Chromium/Electron can regenerate on next launch.
- Sends original stale session/log/suggestion files to the Windows Recycle Bin after any required archive is written.
- Runs stale Serena/resource-health cleanup in the recurring maintenance cycle.
- Lowers live Codex App subprocess priority during the recurring cycle so renderer/GPU spikes yield to the rest of the workstation.
- Sets Codex App's Windows per-app GPU preference to Power Saving during the recurring cycle; this is safer than disabling GPU rendering because disabling GPU can move rendering work onto CPU.
- Provides a capped rendering relaunch mode for renderer/GPU CPU incidents where the app is still usable but Chromium raster/render parallelism needs a lower ceiling.
- Provides a reduced UI controls relaunch mode for high-DPI renderer/GPU incidents where scale and essential progress animation must remain visible, while smooth scrolling and raster parallelism can be reduced.
- Keeps resource-health `cpu_samples`, `warnings`, and `blockers` in the cycle summary so high Codex CPU cannot be hidden behind stale-cleanup `PASS`.

## Boundaries

- It does not leave backups in `C:\Users\anise\.codex`; the legacy `--keep-backups` flag is ignored for retention.
- It keeps compressed logs/session archives only as durable retention evidence; backup and temporary cleanup artifacts go to the Recycle Bin.
- It runs at logon and every `240` minutes when the scheduled task is installed.
- It does not modify Codex App binaries or repo source history.
- It keeps current Windows-native project roots active.
