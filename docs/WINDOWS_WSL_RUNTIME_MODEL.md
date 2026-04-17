# Windows-WSL Runtime Model

## Roles

- Windows:
  - user environment
  - Codex App UI
  - installer surface
  - global `.codex`
- WSL Ubuntu:
  - canonical repo root
  - default implementation and verification surface

## Modes

- `wsl_native_canonical`
  - repo root is WSL-native under the canonical `Dev-Product` tree
  - Windows opens the same repo through `\\wsl$` or `\\wsl.localhost`
  - same-host Syncthing pair is unnecessary
- `mirror`
  - a separate twin path is intentionally maintained
  - only valid with an actual multi-device or Syncthing topology
- `legacy_windows_mount`
  - Windows-mounted checkout
  - evidence-only, not canonical
  - must not be used as the writer surface

## Current Machine Rule

- canonical path: authority-derived Linux repo root under `Dev-Product`
- Windows access path: authority-derived WSL UNC path for the active Linux repo
- recommended runtime surface: `wsl-ubuntu-native`

## Why This Matters

- Linux-native tooling lives in WSL and should be verified there.
- Windows remains the user/UI plane, but it no longer defines the canonical repo root.
- old Windows Desktop checkout assumptions are stale evidence and must not be treated as design truth.
