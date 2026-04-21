# Local Environments

## Required Wrapper Actions

- `Setup` -> `python scripts/project_setup.py --bootstrap`
- `Smoke` -> `python scripts/run_acceptance.py smoke`
- `Full Verify` -> `python scripts/run_acceptance.py full`
- `Delivery Gate` -> `python scripts/delivery_gate.py --mode verify`

`Delivery Gate` wrapper는 로컬 project delivery gate만 끝내고 종료하면 안 됩니다. canonical close-out에서는 이 wrapper가 global scorecard review sync, global delivery gate, summary export까지 이어서 실행해야 합니다.

`verify`/`release`에서는 `--reuse-existing-reports`를 기본 금지합니다. 재사용 예외는 authoritative provenance 검증이 모두 맞을 때만 허용됩니다.

## Policy Cross-Check

- `contracts/project_policy.json`
- `docs/LOCAL_ENVIRONMENTS.md`
- app-generated `.codex` Local Environments files
- signed workspace authority lease under `$CODEX_HOME/state/workspace-authority/`

`python scripts/check_local_environments.py` is authoritative. Any mismatch leaves `BLOCKED`. repo `.codex` files without authoritative app registration remain heuristic evidence only.

## Registration Rule

- register Local Environments from Codex App Settings against the canonical WSL-native repo
- prefer the authority-derived wsl.localhost path; keep wsl$ only as legacy evidence, not the default runtime path
- do not fake registration with docs alone
