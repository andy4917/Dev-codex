# Windows-Native Domain Knowledge

This is the global Windows-native knowledge list for Codex work on this workstation.

## PowerShell 7 Core API

- Treat aliases such as `ls`, `rm`, `cat`, `cp`, and `mv` as PowerShell command aliases, not Unix tools.
- Prefer explicit cmdlets in scripts and diagnostics: `Get-ChildItem`, `Remove-Item`, `Get-Content`, `Copy-Item`, `Move-Item`.
- Remember that PowerShell pipelines pass objects, not plain text. Use `Select-Object`, `Where-Object`, `ConvertTo-Json`, and explicit property access instead of assuming text streams.
- When command-line argument boundaries matter, test with the real native command. Use `--%` sparingly because it changes PowerShell parsing for the remaining command line.

## UNC Path And Long Path

- Preserve Windows path semantics: backslash is a path separator in Windows paths and an escape character in many string/file formats.
- Use `-LiteralPath` for filesystem operations when a path can contain brackets, wildcards, or unusual characters.
- For very long paths, prefer APIs and tools that support long paths and preserve `\\?\` prefixes when the source path already uses them.
- System long-path enablement is the registry value `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled=1`. Changing it requires administrator context and should be reported rather than silently attempted from a non-elevated session.
- UNC paths use `\\server\share\...`; extended UNC paths use `\\?\UNC\server\share\...`.

## Win32 API And Registry

- Do not hardcode opaque registry writes. Name the owning Windows feature, hive, key path, value name, type, and intended value.
- Prefer documented Windows APIs, PowerShell cmdlets, or vendor installers before direct registry edits.
- For user-level app graphics preference, the relevant key is `HKCU\Software\Microsoft\DirectX\UserGpuPreferences`.
- For system long-path policy, the relevant key is `HKLM\SYSTEM\CurrentControlSet\Control\FileSystem`.
- Registry writes that require elevation are user-action blockers unless the user explicitly runs an elevated installer or shell.

## Execution Policy

- Treat execution policy failures as environment-policy issues, not script bugs.
- Inspect scope before changing anything:

```powershell
Get-ExecutionPolicy -List
```

- Prefer process-scoped bypass for one-off local execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\script.ps1
```

- Do not permanently relax machine policy from a non-elevated Codex task. If policy blocks installation or script execution, report the exact blocked command and the direct official installer link.

## Required References

- Microsoft PowerShell aliases: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_aliases
- Microsoft PowerShell pipelines/objects: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_pipelines
- Microsoft maximum path length limitation: https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation
- Microsoft Registry API: https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry
- Microsoft PowerShell execution policies: https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies
