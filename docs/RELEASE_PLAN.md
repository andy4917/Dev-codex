# Release Plan

## Release Scope

- `app_v2/`, `src/`, `extension/`, `tests/`의 제품 변경
- `docs/architecture/` authority docs와 루트 delivery docs
- `contracts/`, `.codex/`, `.agents/`, `scripts/`의 운영 baseline

## Release Sequence

1. `L2` 또는 `L3` 작업이면 `/plan`과 router evidence를 먼저 남긴다.
2. `python scripts/check_traceability.py`
3. `python scripts/run_acceptance.py full`
4. `python scripts/check_unknowns.py`
5. `python scripts/check_runaway.py`
6. `python scripts/check_local_environments.py`
7. clean staging folder 준비
8. `python scripts/check_bundle_sync.py`
9. `python scripts/delivery_gate.py --mode release`
10. `python scripts/export_obsidian_notes.py --task-id RELEASE --session VERIFY --tier L3 --status ready`

실제 프로젝트 full verify contract:

1. `npm run app:check`
2. `python tests/run_regressions.py`
3. `npm run app:verify:artifacts`
4. `npm run app:verify:electron-smoke`

## Approval

- actor는 release 승인권이 없다.
- release는 maintainer 또는 사용자 승인 후에만 닫는다.
- `contracts/project_policy.json`의 `human_review.status`가 `approved`가 아니면 release는 닫히지 않는다.
- 현재 워크스테이션에서 Windows native의 `node`/`npm`이 PATH에 없고 WSL Ubuntu에도 `node`/`npm`이 없으므로, mixed runtime release는 `BLOCKED`가 정상이다.
