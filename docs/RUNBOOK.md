# Runbook

## Windows-Native Baseline

Workflow authority: [GLOBAL_AGENT_WORKFLOW.md](./GLOBAL_AGENT_WORKFLOW.md).

Run all Dev-Management environment checks from:

```powershell
cd C:\Users\anise\code\Dev-Management
python scripts\check_user_dev_environment.py --json
```

The passing verdict is `PASS` with production readiness `READY`.

## App Readiness

```powershell
python scripts\check_windows_app_local_readiness.py --json
```

The passing verdict is `APP_READY`. This check validates local Windows-native Codex App readiness and does not probe remote hosts.

## Migration Evidence

Migration evidence lives at:

```text
C:\Users\anise\code\Dev-Management\reports\migration-evidence\20260425-windows-native-transition
```

The manifest hash is recorded in `MANIFEST.sha256`. Legacy Linux runtime decommissioning has been explicitly authorized after Windows-native checks and migration evidence capture. Keep this evidence directory until the user explicitly asks to remove migration records too.
