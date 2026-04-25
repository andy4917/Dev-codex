# Prerequisites

## Windows-Native Runtime

- Windows 11
- PowerShell 7.4 or newer
- Windows Terminal
- Git for Windows
- Python
- pipx
- uv
- 7-Zip or equivalent unzip utility
- Node/npm/corepack when a repo script requires them
- GitHub CLI when a repo or release workflow requires it
- Docker Desktop only for optional build, verification, packaging, integration checks, or release verification

## Optional Repo Tooling

- Visual Studio Build Tools for native Python/Node extensions
- .NET SDK when product repos require it
- pnpm/yarn only when package scripts require them
- Syncthing only if the user explicitly reintroduces multi-device sync

## Automatic Repair Policy

- Windows install priority:
  1. `winget`
  2. `choco`
  3. existing-path repair or official installer fallback

## Honest BLOCKED Conditions

- administrator privilege required
- reboot required
- GUI or license approval required
- network or package repository outage
- destructive overwrite required
