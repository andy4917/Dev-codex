# Syncthing

## Decision Rule

- `wsl_native_canonical` + no existing Syncthing operation:
  - do not install Syncthing just to mirror the same host
  - `reports/syncthing.audit.json` should record `NOT_REQUIRED`
- `mirror` mode or existing multi-device Syncthing operation:
  - audit and repair are mandatory

## Audit Commands

- `python scripts/check_path_visibility.py`
- `python scripts/check_syncthing.py`
- `python scripts/check_sync_conflicts.py`

## Repair Command

- `python scripts/configure_syncthing.py --repair`

## Required Defaults When Syncthing Is In Use

- folder mode: `sendreceive`
- `fsWatcherEnabled = true`
- `ignorePerms = true`
- `autoNormalize = true`
- file versioning enabled
- conflict scan on `.sync-conflict-*`

Git remains the history truth source. Syncthing is only a transport/sync layer.
