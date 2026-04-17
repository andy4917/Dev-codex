# Dependency Inversion

## Non-Negotiable Rule

Dependency inversion is mandatory in this repo. It is not guidance.

## Allowed Direction

- inner/domain -> abstractions only
- application/use-case -> abstractions only
- outer/adapter/infra -> may depend on inner and application contracts

## Forbidden Direction

- `src/domain/**` importing `src/io/**`, `src/core_bridge/**`, `src/channel_executors/**`, `src/ota/adapters/**`, `app_v2/**`, or `extension/**`
- `src/report/**`, `src/reconcile/**`, `src/scan/**` importing the same concrete outer layers directly
- domain/application importing framework, UI toolkit, DB client, transport client, or external SDK concrete modules directly
- domain/application constructing concrete `*Adapter`, `*Client`, `*Gateway`, `*Provider`, or `*Repository` implementations directly

## Waivers

- `scripts/**`
- `tests/**`
- migrations
- generated code

Waivers must be explicit in `contracts/dip_policy.json` and carry a reason.

## Enforcement

- `python scripts/check_dip.py`
- `python scripts/delivery_gate.py --mode verify`

Gate behavior:

- non-waived violations -> `FAIL`
- waived-only findings -> `WAIVED`
- no findings -> `PASS`
