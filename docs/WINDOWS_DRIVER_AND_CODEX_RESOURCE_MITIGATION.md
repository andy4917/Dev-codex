# Windows Driver And Codex Resource Mitigation

This note records the current mitigation path for the Intel Arc graphics driver issue and the Codex App renderer/GPU resource spike on the Windows-native workstation.

## Current Driver Finding

The Intel graphics installer for `32.0.101.8735` can be downloaded, but the live system may still report an older active display driver. Treat a failed installer or a missing staged target driver as a Windows/OEM driver delivery issue, not as proof that the device cannot use the driver.

Run:

```powershell
python scripts\check_windows_driver_health.py --json
```

The checker records:

- active Intel Arc display driver version from `pnputil /enum-devices /class Display /drivers`
- staged Intel driver versions from `pnputil /enum-drivers`
- whether the target installer is present or running
- whether the current shell is elevated
- direct recommended actions

## Mitigation Order

1. Prefer Lenovo's model-specific graphics driver when the Intel generic installer refuses the platform.
2. If using Intel generic graphics, run the installer from an elevated Windows session.
3. If Windows Update rolls the driver back, retry Intel's custom install path without enabling clean installation.
4. Use Device Manager or extracted-driver manual install only from an elevated session and only after the installer path is verified.
5. Avoid DDU or driver-store deletion unless downtime, restore point, and manual recovery are acceptable.

## Codex App Resource Mitigation

The live incident must be separated before blaming one root cause:

- `Windows Search` indexing high-churn code/app-state paths
- `Microsoft Defender` scanning code, session logs, caches, and package-manager tools
- `System` privileged CPU from file-system, WMI, graphics, or antivirus pressure
- Codex `gpu_process`/`renderer` CPU and DWM compositor pressure
- duplicate Serena MCP roots and descendants

First apply the non-app-closing mitigations:

```powershell
pwsh scripts\apply_windows_dev_resource_mitigations.ps1 -StopWindowsSearch -Json
```

If Windows Search restarts immediately during an incident, run the same script with `-SetWindowsSearchDemandStart`. That keeps the service on manual start while leaving Windows Search installed:

```powershell
pwsh scripts\apply_windows_dev_resource_mitigations.ps1 -StopWindowsSearch -SetWindowsSearchDemandStart -Json
```

Then sample with both process and kernel counters:

```powershell
python scripts\check_windows_app_resource_health.py --cpu-sample-seconds 5 --kernel-sample-count 5 --json
```

When GPU/renderer CPU remains high and driver update is blocked, prefer reversible app-level mitigation:

```powershell
pwsh scripts\restart_codex_app_graphics_mode.ps1 -Mode ReducedUiControls -ClearRenderCache
```

Then re-check resource health. Use `CappedRendering` next. Use `DisableGpu` only as a reproduction or last-resort path because it can move rendering work to CPU.

For the repeated symptom where the app visually updates only after mouse movement, use `DisableGpu` as the final app-restart step after the non-app-closing mitigations and commit-safe work are done:

```powershell
pwsh scripts\restart_codex_app_graphics_mode.ps1 -Mode DisableGpu -ClearRenderCache
```

## Serena MCP Duplicate Cleanup

Default checks protect duplicate Serena MCP roots because killing the wrong transport can close the current Codex session. After work is committed and pushed, an explicitly authorized cleanup can run:

```powershell
python scripts\check_windows_app_resource_health.py --cleanup-stale-serena --cleanup-duplicate-serena-roots --force-kill-duplicate-serena-roots --json
```

The command keeps the newest root and stops older duplicate roots plus descendants.

## Sources

- Intel OEM lock error guidance: https://www.intel.com/content/www/us/en/support/articles/000056629/graphics.html
- Intel Windows Update rollback guidance: https://www.intel.com/content/www/us/en/support/articles/000087834/graphics.html
- Lenovo Yoga 7 2-in-1 14ILL10 Type 83JQ driver support: https://pcsupport.lenovo.com/us/en/products/laptops-and-netbooks/yoga-series/yoga-7-2-in-1-14ill10/83jq/downloads
- Microsoft device installation policy reference: https://learn.microsoft.com/en-us/windows/client-management/manage-device-installation-with-group-policy
- Electron performance guidance: https://www.electronjs.org/docs/latest/tutorial/performance
