# User Scorecard

## Scope

- canonical policy root: `/home/andy4917/Dev-Management`
- runtime mirror: `/home/andy4917/.codex/AGENTS.md`
- scorecard policy: `contracts/user_score_policy.json`
- disqualifier policy: `contracts/disqualifier_policy.json`
- authoritative reviewer verdict root: `$CODEX_HOME/state/reviewer-verdicts/<codex_project_id>/<trace_id>/`
- authoritative scorecard context: `$CODEX_HOME/state/scorecard-context/<codex_project_id>/<trace_id>.json`
- authoritative workspace lease: `$CODEX_HOME/state/workspace-authority/<codex_project_id>.json`
- derived review snapshot: `reports/user-scorecard.review.json`
- generated result: `reports/user-scorecard.json`

## Core Rules

- score is deduction-only oversight, not a reward function
- writer cannot self-score, self-award, or self-excuse
- reviewer and user may only deduct
- PASS is still determined by reviewer green, existing readiness, and clean-room verify
- disqualifiers outrank score

## Reviewer Roles

- `skeptic_reviewer`: trust and compliance deductions. Required except for small `L0`.
- `correctness_verifier`: completion and search evidence deductions.
- `contamination_monitor`: reliability, security, and contamination deductions.
- `final_auditor`: re-checks the score result itself before PASS.

## Review Input

`reports/user-scorecard.review.json` is no longer canonical gate input. It is a derived human-readable snapshot rendered from:

- workspace reports -> scorecard context
- signed append-only reviewer verdict logs
- authority audit findings

Canonical gate truth now comes from runtime state outside the repo.

- `task_context` controls axis applicability, caps, and reviewer requirements.
- `user_review.penalties[]` uses the same schema.
- `disqualifiers[]` accepts `id`, `reason`, and optional `evidence_refs`.
- `existing_readiness` carries upstream gate status and remaining manual close-out.
- `clean_room_verify` carries final verify status.

Reviewer verdict events must include:

- `version`, `role`, `producer_lane`, `repo_root`, `git_sha`, `worktree_id`
- `codex_project_id`, `trace_id`, `generated_at`, `input_report_hash`
- `status`, `green`, `penalties`, `disqualifiers`, `notes`, `signature`

Unsigned, wrong-signature, or wrong-provenance verdicts are ignored and recorded as tamper findings.

## Commands

```bash
python /home/andy4917/Dev-Management/scripts/prepare_user_scorecard_review.py --workspace-root /home/andy4917/Dev-Product/<project> --mode verify
python /home/andy4917/Dev-Management/scripts/record_reviewer_verdict.py --workspace-root /home/andy4917/Dev-Product/<project> --trace-id <trace_id> --role skeptic_reviewer --status APPROVED --green true --input-report <context.json>
python /home/andy4917/Dev-Management/scripts/delivery_gate.py --mode verify --workspace-root /home/andy4917/Dev-Product/<project>
python /home/andy4917/Dev-Management/scripts/export_user_score_summary.py
```

`prepare_user_scorecard_review.py`는 reviewer truth를 생성하거나 수정하지 않습니다. workspace reports에서 context를 조립하고, signed verdict log를 읽어 snapshot에 렌더링만 합니다.

제품 저장소의 `python scripts/delivery_gate.py --mode verify` wrapper는 로컬 project gate를 끝낸 뒤 위 3개 전역 scorecard 단계를 자동으로 이어서 실행해야 합니다. 로컬 project gate 결과는 `existing_readiness`와 `clean_room_verify`의 upstream evidence이며, global scorecard를 대체하지 않습니다.

## Gate Order

1. disqualifier check
2. reviewer green check
3. trace presence check
4. axis floor check
5. platform cap check
6. existing readiness and manual close-out check
7. clean-room verify check

`quick` mode enforces disqualifiers only and records score output as advisory. `verify` and `release` enforce the full score gate, require fresh evidence only, and fail closed without a valid workspace authority lease.
