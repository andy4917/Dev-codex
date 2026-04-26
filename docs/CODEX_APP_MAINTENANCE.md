# Codex App Maintenance

Codex App state is a user control-plane surface, not repo authority. Dev-Management may sanitize it only for stale restore references, legacy runtime paths, and volatile log retention.

## Entry Points

- Dry run: `python scripts/maintain_codex_app_state.py --json`
- Apply: `python scripts/maintain_codex_app_state.py --apply`
- Full cycle: `python scripts/run_codex_app_maintenance_cycle.py --json`
- Resource-health CPU sample: the full cycle samples Codex App CPU for `3` seconds by default; set `--resource-cpu-sample-seconds 0` only when the machine is too sluggish to sample.
- Serena MCP root ceiling: the full cycle passes `--keep-serena-roots 1 --duplicate-serena-grace-minutes 10` to the resource-health check.
- Renderer/GPU/app-server evidence: `python scripts/check_windows_app_resource_health.py --cpu-sample-seconds 5 --json` records Codex CPU by subprocess role.
- System pressure evidence: add `--kernel-sample-count 5` when Task Manager shows `System`, Search, Defender, WMI, or DWM pressure. The checker uses `typeperf` for kernel counters so it can distinguish high privileged CPU from interrupt/DPC storms without adding more CIM/WMI load.
- Dev resource mitigations: `pwsh scripts/apply_windows_dev_resource_mitigations.ps1 -StopWindowsSearch -Json` marks high-churn dev/app-state paths as `NotContentIndexed`, adds measured Defender exclusions, and optionally stops Windows Search. Add `-SetWindowsSearchDemandStart` only during an active incident where Search restarts immediately. It does not close Codex App.
- Driver health evidence: `python scripts/check_windows_driver_health.py --json` records active/staged Intel Arc graphics driver versions and install blockers.
- Git worker loop evidence: the resource-health report flags dirty tracked files whose working-tree line endings are `CRLF` or mixed even though repo attributes require `eol=lf`; this catches `safecrlf` failures that can keep Codex App review/git workers busy.
- CPU sample unit: `codex_cpu_pct` is percent of one logical CPU; `codex_system_cpu_pct` is the system-normalized estimate using the current logical processor count.
- Priority/GPU changes are opt-in only: `python scripts/run_codex_app_maintenance_cycle.py --throttle-codex-priority --prefer-low-power-gpu --json` is the explicit path after measured evidence justifies it.
- Low-power GPU preference: `python scripts/check_windows_app_resource_health.py --prefer-low-power-gpu --json` sets Windows per-app graphics preference for Codex executables to Power Saving; the setting takes effect after the next Codex App launch.
- Render cache cleanup: `python scripts/maintain_codex_app_state.py --apply --cleanup-render-cache --json` sends Codex Electron `Cache`, `Code Cache`, and `GPUCache` directories to the Recycle Bin. Use it immediately before app restart; persistent app state is not removed.
- Low-power GPU relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode ForceLowPowerGpu -ClearRenderCache` restarts Codex with Electron's `--force_low_power_gpu` switch after render-cache cleanup.
- Capped rendering relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode CappedRendering -ClearRenderCache` keeps GPU enabled while adding `--renderer-process-limit=2` and `--num-raster-threads=1`; use it before `-Mode DisableGpu` when renderer/GPU CPU remains high.
- Reduced UI controls relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode ReducedUiControls -ClearRenderCache` preserves the default UI scale while adding `--num-raster-threads=2` and `--disable-smooth-scrolling`. The observed default raster thread count was `4`, so `2` is the 50% reduction path without shrinking the UI. Do not force reduced-motion in the default path because thinking/loading indicators must remain visibly animated.
- Full GPU disable relaunch: `pwsh scripts/restart_codex_app_graphics_mode.ps1 -Mode DisableGpu -ClearRenderCache` is the final app-restart step for repeated "paint only after mouse movement" incidents after Search/Defender/WMI pressure is handled. It disables GPU compositing/rasterization, Chromium background/occlusion throttles, and reduces raster threads. It can move some rendering work onto CPU, so run it after saving and closeout work.
- Analytics opt-out: `C:\Users\anise\.codex\config.toml` may set `[analytics] enabled = false`; Codex `app-server --help` documents this as the user opt-out for the app-server analytics default.
- Install recurring task: `pwsh scripts/install_codex_app_maintenance_task.ps1`
- Defaults: keep only `1` day of live original logs, keep at most `60` live session JSONL files, keep at most `10000` live SQLite log rows.

## What It Changes

- Removes legacy remote auto-connect state from `.codex-global-state.json`.
- Removes stale persisted cloud task state such as `electron-persisted-atom-state.environment` and `codexCloudAccess` when it points at old `/workspace` remote task metadata.
- Removes legacy workspace SID mappings from `.codex/cap_sid`.
- Sends ambient suggestions whose project root points to legacy or missing workspaces to the Recycle Bin.
- Marks stale `state_5.sqlite` threads archived instead of deleting them, including live threads whose recorded git origin still points at the deprecated `andy4917/Dev-codex` slug.
- Compresses stale or over-limit session JSONL files.
- Compresses Codex desktop log files older than 1 day.
- Exports old `logs_2.sqlite` rows to gzip, deletes exported rows, and attempts SQLite compaction.
- Optionally recycles renderer cache directories that Chromium/Electron can regenerate on next launch.
- Sends original stale session/log/suggestion files to the Windows Recycle Bin after any required archive is written.
- Runs stale Serena/resource-health cleanup in the recurring maintenance cycle.
- Keeps live Codex App priority and GPU preference unchanged during the recurring cycle unless the opt-in flags are passed.
- Provides a capped rendering relaunch mode for renderer/GPU CPU incidents where the app is still usable but Chromium raster/render parallelism needs a lower ceiling.
- Provides a reduced UI controls relaunch mode for high-DPI renderer/GPU incidents where scale and essential progress animation must remain visible, while smooth scrolling and raster parallelism can be reduced.
- Provides an admin-safe dev resource mitigation script for Windows Search and Defender pressure on `C:\Users\anise\code`, `C:\Users\anise\.codex`, and package-manager caches.
- Keeps resource-health `cpu_samples`, `warnings`, and `blockers` in the cycle summary so high Codex CPU cannot be hidden behind stale-cleanup `PASS`.
- Keeps resource-health `system_pressure` and `kernel_samples` in the report so `System` CPU, Search indexing, Defender scanning, WMI polling, DWM composition, and Codex renderer/GPU pressure are not collapsed into one guessed cause.
- Records driver-health evidence separately so Codex renderer/GPU spikes can be correlated with blocked Intel/OEM driver updates instead of hidden in process counts.

## Boundaries

- It does not leave backups in `C:\Users\anise\.codex`; the legacy `--keep-backups` flag is ignored for retention.
- It keeps compressed logs/session archives only as durable retention evidence; backup and temporary cleanup artifacts go to the Recycle Bin.
- It runs at logon and every `240` minutes when the scheduled task is installed.
- It does not modify Codex App binaries or repo source history.
- It cannot remove packaged Codex App features such as the internal remote task handler; it only removes stale user-state inputs that keep that handler matching against old metadata.
- It keeps current Windows-native project roots active.
- It does not force graphics driver installation; driver updates require an elevated Windows/OEM installer path.
