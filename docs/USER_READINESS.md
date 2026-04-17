# User Readiness

## 판정 축

- `structure_sound`: elevated Windows sandbox, read-only verifier, prompt/readiness/obsidian docs, placeholder-free plugin metadata
- `day0_ready`: bootstrap이 setup/verify/quality commands를 실제로 채움
- `understanding_ready`: Understanding Contract, Quality-First Execution Contract, Quality-first Finalization Contract가 존재
- `local_environments_ready`: Codex App의 `Setup`, `Smoke`, `Full Verify`, `Delivery Gate` 액션이 실제 `.codex` 파일에서 확인됨
- `human_review_ready`: `contracts/project_policy.json`의 `human_review.status = approved`
- `plan_evidence_ready`: `L2`/`L3` 작업에 대해 router 또는 patch 보고서가 존재
- `production_ready`: open U2/U3 없이 human review, Local Environments, planning evidence까지 닫힘

## 최종 상태

- `ready`: 모든 축이 true
- `conditional`: 구조는 있으나 Day 0 또는 production close가 덜 됨
- `not_ready`: gate가 실패하거나 핵심 구조가 깨짐

## 출력

`reports/user-readiness.json`는 아래 키를 기록합니다.

- `structure_sound`
- `day0_ready`
- `understanding_ready`
- `local_environments_ready`
- `human_review_ready`
- `plan_evidence_ready`
- `production_ready`
- `overall`
- `baseline_stage`
