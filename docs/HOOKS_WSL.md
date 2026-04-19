# WSL Hooks

## Scope

- Legacy hook assets는 quarantine 또는 runtime state로만 남기고, primary enforcement로 사용하지 않는다.
- Windows native에서는 hooks를 강제하지 않고 deterministic verify script를 우선한다.
- WSL/Linux에서도 hooks는 보조 수단일 뿐이며, canonical gate는 explicit verify 절차다.

## Current Handling

- generated global runtime may install `hooks.json` only to replay the binding global scorecard close-out path at `SessionStart` and `UserPromptSubmit`.
- the generated hook must stay advisory. It may re-inject the scorecard layer, but it must not replace `prepare_user_scorecard_review.py`, `delivery_gate.py`, `export_user_score_summary.py`, or `audit_workspace.py --write-report`.
- legacy hook artifacts는 quarantine에 격리하고, 검토가 필요하면 `python scripts/check_hook_logs.py`로 evidence-only 로그를 읽는다.
- hook log는 정책 source of truth가 아니라 continuity evidence다.
