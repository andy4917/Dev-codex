# Windows-WSL Runtime Model

## Access

- Windows is the user/UI plane.
- WSL Ubuntu is the canonical implementation and verification plane.
- Preferred Windows access path is `\\wsl.localhost\Ubuntu\...`.
- `\\wsl$` remains acceptable for legacy evidence, but `\\wsl.localhost` is the default runtime path.

## L0-L4 Layers

- `L0`: authority, contracts, and generated policy baselines.
- `L1`: project defaults and canonical runtime inputs.
- `L2`: machine and environment overlays.
- `L3`: live session state and operational overrides.
- `L4`: restore material and temporarily uplifted experimental or underfeature surfaces.

Higher layers override lower layers. A stale restore can therefore mask corrected lower-layer state until the restore is rebuilt.

## Current Machine Rule

- canonical path: authority-derived Linux repo root under `Dev-Product`
- Windows access path: authority-derived `\\wsl.localhost` UNC path for the active Linux repo
- runtime restore is derived-only and must be regenerated from authoritative inputs, not hand-edited as source of truth
- experimental and underfeature behavior may be temporarily uplifted into the runtime model, but only until stability review decides whether to keep or remove it

## Why This Matters

- Linux-native tooling lives in WSL and should be verified there.
- Windows remains the user/UI plane, but it does not define the canonical repo root.
- restore artifacts are runtime inputs, not policy; when they drift, rebuild them from source instead of trusting the stale snapshot.
- old Windows Desktop checkout assumptions are stale evidence and must not be treated as design truth.
