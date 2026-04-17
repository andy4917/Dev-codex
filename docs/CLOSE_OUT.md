# Close-Out

## Baseline Close Condition

아래만 남아 있으면 첫 실프로젝트 close-out 직전 상태로 봅니다.

1. `contracts/project_policy.json`의 `human_review.status = approved`
2. Codex App이 canonical WSL repo에 대해 Local Environments를 실제 등록
3. `reports/local-environments-report.json = PASS`
4. `reports/context7-usage.json` evidence complete
5. `reports/dip-check.json` is `PASS` or `WAIVED`
6. reviewer lanes green
7. `reports/delivery-gate.json = PASS`
8. fresh evidence manifest is valid for the active `trace_id`
9. workspace authority lease is valid and unexpired

## Current Manual Close-Out Boundary

- human review approval
- app-generated Local Environments registration
- final clean-room verify
- reviewer verdict authority
- fresh evidence provenance

## Codex Desktop App Bug: Diagnostic-Only Lane

이 저장소에서는 Codex 데스크톱 앱 본체를 수정하지 않습니다.

- 재현
  - 일반 권한으로 Codex App 실행
  - 창 미표시 / ghost process 확인
- evidence
  - Windows global `.codex` state
  - Windows global `.codex` config
  - workspace root / open target preference
- workaround
  - stale workspace root/open target preference 정리
  - canonical `\\wsl$` workspace로 다시 열기
  - 필요 시 global `.codex` state 백업 후 reset
