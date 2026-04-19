# WSL Hooks

## Scope

- Legacy hook assets는 quarantine 또는 runtime state로만 남기고, primary enforcement로 사용하지 않는다.
- Windows native에서는 hooks를 강제하지 않고 deterministic verify script를 우선한다.
- WSL/Linux에서도 hooks는 보조 수단일 뿐이며, canonical gate는 explicit verify 절차다.

## Current Handling

- generated global runtime may install `hooks.json` only to replay the binding global scorecard close-out reminder at `UserPromptSubmit`.
- the active generated Windows hook path should call a generated PowerShell wrapper instead of a raw `wsl.exe python3 ...` command so UNC cwd warnings do not surface as fake hook failures.
- the wrapper may translate `\\wsl.localhost\\...` cwd values into Linux form, but translation failure must stay quiet and exit `0`.
- the generated hook must stay advisory. It may re-inject the scorecard layer, but it must not replace `iaw_closeout.py` or its internal `prepare -> audit(pre-gate) -> delivery_gate -> audit(pre-export) -> export -> audit(post-export)` chain.
- generated `hooks.json` is derived state. If authority removes `runtime_hook` or clears its events, the generated file should be deleted so stale reminders do not continue running.
- legacy hook artifacts는 quarantine에 격리하고, 검토가 필요하면 `python scripts/check_hook_logs.py`로 evidence-only 로그를 읽는다.
- hook log는 정책 source of truth가 아니라 continuity evidence다.
