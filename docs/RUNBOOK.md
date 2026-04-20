# Runbook

## Runtime Authority

- Codex App is a user surface only.
- Windows host is a client and UI surface only.
- Dev-Management is the source of truth.
- `ssh-devmgmt-wsl` is the canonical execution surface.
- `/mnt/c/Users/anise/.codex/bin/wsl/codex` is an external dependency and is forbidden as the primary runtime.
- Generated config and shim files must not be edited by hand.

## Prerequisites

- Python `>=3.10`
- node and npm
- optional: `uv`

현재 워크스테이션의 generated evidence는 `reports/inventory.summary.json`과 `reports/toolchain.*.json`이다. source-of-truth는 contracts, runtime docs, canonical repo root 자체이며 `reports/`는 generated proof일 뿐이다.

Runtime authority evidence now also includes:

- `reports/global-runtime.json`
- `reports/git-surface.json`
- `reports/startup-workflow.json`
- `reports/generated-runtime-preview/`
- `reports/manual-system-remediation-<timestamp>.md`

## Day 0 Bootstrap

1. `python scripts/project_setup.py --bootstrap`
2. `contracts/project_policy.json`의 `setup_commands`, `quality_hooks`, `verify_commands`, `release_rules`를 사람 기준으로 검토
3. `python scripts/session_router.py --task "<task>"`
4. `L2`/`L3`, API/schema, release/rollback, open `U2`/`U3`, mixed session이면 `/plan`으로 시작
5. Codex App Settings에서 Local Environments `Setup`, `Smoke`, `Full Verify`, `Delivery Gate`를 실제 등록

Before any repair apply:

1. `python scripts/check_global_runtime.py --json`
2. `python scripts/check_git_surface.py --json`
3. `python scripts/check_startup_workflow.py`
4. `python scripts/check_agent_instruction.py --instruction "<task>"`
5. `python scripts/audit_workspace.py`

If audit is not PASS, do not run live repair apply. Generate preview output and use the manual remediation report.

## Routing And Plan Entry

- `README 오타 수정` 같은 `L0` 작업은 같은 thread에서 처리 가능
- 공개 API, schema, release, rollback, 운영 경계 변경은 `L3` 또는 `L2`로 올리고 `/plan` 후 작업
- subagent는 명시적 요청이 있을 때만 explorer/verifier로 최대 2개까지 사용

## Verify Loop

항상 wrapper command로 시작:

- `python scripts/check_toolchain.py --surface all`
- `python scripts/check_path_visibility.py`
- `python scripts/check_global_runtime.py --json`
- `python scripts/check_git_surface.py --json`
- `python scripts/check_agent_instruction.py --instruction "<task>"`
- `python scripts/check_traceability.py`
- `python scripts/run_acceptance.py smoke`
- `python scripts/check_startup_workflow.py`
- `python scripts/check_context7.py --enforce-from-git`
- `python scripts/check_dip.py`
- `python scripts/check_unknowns.py`
- `python scripts/check_runaway.py`
- `python scripts/delivery_gate.py --mode verify`

실제 프로젝트 기준 smoke/full은 `contracts/project_policy.json`이 결정한다.

Guard expectations:

- Serena-first before code work that changes the repo
- Context7-first before protected dependency, API, config, or migration changes
- unrelated dirty files remain untouched
- Windows and WSL Git drift is reported, not auto-repaired
- auto mode is fail-closed when the authority declares canonical SSH execution
- canonical SSH PASS plus Codex App PATH contamination is a client-surface warning, not execution-authority failure
- local shell execution stays blocked until live codex resolution and wrapper safety are clean

Migration / authority close-out은 아래 single entrypoint로 묶어서 실행할 수 있다.

- `python scripts/verify_migration_evidence.py`
- 위 command는 `python scripts/delivery_gate.py --mode verify`, `python scripts/export_user_score_summary.py`, `python scripts/audit_workspace.py --write-report`를 순서대로 실행하고 `reports/migration-verification.json`에 migration evidence bundle을 기록한다.

## Close Loop

- `python scripts/memory_checkpoint.py --task-id TASK-001 --session BUILD --tier L1 --status active`
- `python scripts/export_obsidian_notes.py --task-id TASK-001 --session BUILD --tier L1 --status active`
- release 전 `python scripts/check_bundle_sync.py`

## Failure Handling

- runner가 없으면 `BLOCKED`
- canonical SSH runtime이 불가하면 authority-based execution은 `BLOCKED`
- live `command -v codex`가 Windows-mounted launcher로 해상되면 `BLOCKED`
- shim text가 맞아 보여도 live PATH precedence가 forbidden이면 `BLOCKED`
- 현재 surface에서 필수 런타임이 없으면 `environment_blocked`로 기록하고 benchmark scorer에서 제외
- dependency/config protected change인데 Context7 evidence가 없으면 `BLOCKED`
- Serena metadata schema가 deterministic하게 확인되지 않으면 auto-repair하지 않고 manual remediation으로 남김
- non-waived DIP violation이 있으면 `FAIL`
- traceability가 깨지면 `FAIL`
- open `U2/U3`가 남으면 `BLOCKED`
- open `P0/P1` risk가 남으면 `L2`/`L3` gate는 `FAIL`
- `human_review.status != approved`이면 release는 `BLOCKED`
- Local Environments 실파일이 `.codex`에 없으면 readiness는 `BLOCKED`
