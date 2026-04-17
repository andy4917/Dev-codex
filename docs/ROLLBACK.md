# Rollback

## Rollback Strategy

- 이 저장소의 truth는 Git과 `docs/architecture/` authority docs다.
- 루트 delivery docs, contracts, `.codex`, `.agents`, scripts는 제품 코드와 분리해서 되돌린다.
- generated note, report, bundle drift는 script로 재생성한다.

## Rollback Triggers

- `delivery_gate.py`가 `FAIL`
- readiness가 `not_ready`
- open `P0/P1` risk 또는 open `U2/U3`가 release 전에 남음
- human review가 현재 변경을 승인하지 않음
- Local Environments 명령과 정책이 어긋남

## Recovery Path

1. `git status`로 제품 변경과 운영 baseline 변경을 분리해 본다.
2. 필요 시 `docs/PRODUCT_REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, `contracts/*.json`, `.codex/config.toml`, `AGENTS.md`를 기준선으로 되돌린다.
3. `python scripts/project_setup.py --bootstrap`로 mixed runtime 명령을 다시 채운다.
4. `python scripts/memory_checkpoint.py`와 `python scripts/export_obsidian_notes.py`로 evidence 면을 다시 생성한다.
5. `python scripts/delivery_gate.py --mode verify`를 다시 돌린다.
