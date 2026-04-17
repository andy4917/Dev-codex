# Prompt Blocks

## Quality-First Execution Contract

- runtime, benchmark, cost가 얽힌 작업은 먼저 surface inventory를 확인한다.
- 목표, 범위, 비목표, acceptance, unknowns가 닫히기 전에는 BUILD로 내려가지 않는다.
- 같은 작업이면 같은 thread를 유지하고, 진짜로 갈라질 때만 새 thread/worktree를 연다.
- 최적화 실험은 one-change-at-a-time으로만 비교한다.
- 각 milestone 종료 시 가장 작은 관련 검증을 즉시 실행한다.
- PASS는 evidence와 residual risk가 함께 있을 때만 선언한다.
- 같은 실수 피드백이 두 번 반복되면 다음 작업부터 AGENTS.md 또는 skill로 승격한다.

## Surface Inventory Contract

1. 현재 실행면: `windows-native` 또는 `wsl-ubuntu`
2. 필수 런타임: `git`, `python/python3`, `node`, `npm`
3. 선택 런타임: `uv`
4. 미설치 원인 분류: `not_installed | not_on_path | surface_mismatch | policy_intentional | unconfirmed`
5. `environment_blocked` run은 모델/프롬프트 실패로 계산하지 않는다.

## Understanding Contract

1. 내가 이해한 목표:
2. 이번 턴 범위 / 비목표:
3. 영향 표면(code/docs/ops):
4. 아직 정의되지 않은 변수(U0-U3) / 필요한 질문:
5. 완료 조건 / 검증 명령:
6. 지금 시작 가능 여부 / thread·worktree 분리 필요성:

## Quality-first Finalization Contract

- 변경 파일:
- 실행한 명령과 결과:
- acceptance 충족 여부:
- 남은 위험 / 미해결점:
- 최종 판정: PASS | FAIL | BLOCKED | WAIVED

설명은 증빙 뒤에 둡니다.

## Unknown/New Variable Frame

- U0: 이미 정의됨
- U1: 합리적 추정 가능
- U2: 외부 확인 필요
- U3: 사용자 승인 필요

U2/U3가 열려 있으면 REQ/ARCH/OPERATE를 먼저 열고 BUILD를 지연합니다.
