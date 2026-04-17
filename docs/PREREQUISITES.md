# Prerequisites

## Windows User/UI Plane

- Windows 11
- PowerShell 7
- Windows Terminal
- WSL2
- Ubuntu LTS
- Git for Windows
- Python
- pipx
- uv
- 7-Zip or equivalent unzip utility
- Node/npm/corepack only when a Windows-native workflow actually needs them
- Syncthing only when mirror mode or existing multi-device operation requires it

## WSL Ubuntu Canonical Runtime Surface

- `git`
- `curl`
- `wget`
- `zip`
- `unzip`
- `jq`
- `rsync`
- `file`
- `tree`
- `ca-certificates`
- `openssh-client`
- `bubblewrap`
- `build-essential`
- `make`
- `gcc`
- `g++`
- `cmake`
- `pkg-config`
- `python3`
- `python3-pip`
- `python3-venv`
- `pipx`
- `uv`
- `nvm`
- `node`
- `npm`
- `corepack`
- `pnpm`
- `dos2unix`
- `sqlite3`

## Automatic Repair Policy

- Windows install priority:
  1. `winget`
  2. `choco`
  3. existing-path repair or official installer fallback
- WSL install priority:
  1. `apt`
  2. official install scripts for `uv` and `nvm`
  3. language-specific managers only after the above

## Honest BLOCKED Conditions

- administrator privilege required
- reboot required
- GUI or license approval required
- WSL first-boot initialization pending
- network or package repository outage
- destructive overwrite required
