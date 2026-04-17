# Toolchain

## Inventory Commands

- `python scripts/check_toolchain.py --surface windows`
- `python scripts/check_toolchain.py --surface wsl`
- `python scripts/check_toolchain.py --surface all`
- `python scripts/check_wsl_status.py`
- `python scripts/update_wsl_and_ubuntu.py --repair`

## Repair Commands

- `python scripts/install_or_repair_toolchain.py --surface windows --repair`
- `python scripts/install_or_repair_toolchain.py --surface wsl --repair`

`--dry-run` is supported on repair scripts and should be used before risky machine changes.

## Current Operating Rule

- Windows tooling supports the user/UI plane and Codex App.
- WSL must carry the native Node/Python/build toolchain for normal implementation and verification work.
- Windows interop binaries visible from WSL do not count as native Ubuntu dependencies.
- inventory truth is generated from the canonical WSL repo, never reused from an old Windows-mounted checkout.
