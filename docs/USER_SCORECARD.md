# User Scorecard

## Scope

- canonical policy root: `$DEVMGMT_ROOT`
- runtime mirror: `$CODEX_HOME/AGENTS.md`
- generated runtime hooks: `$CODEX_HOME/hooks.json`
- scorecard policy: `contracts/user_score_policy.json`
- disqualifier policy: `contracts/disqualifier_policy.json`
- authoritative reviewer verdict root: `$CODEX_HOME/state/reviewer-verdicts/<codex_project_id>/<trace_id>/`
- authoritative scorecard context: `$CODEX_HOME/state/scorecard-context/<codex_project_id>/<trace_id>.json`
- authoritative workspace lease: `$CODEX_HOME/state/workspace-authority/<codex_project_id>.json`
- authoritative gate receipt root: `$IAW_STATE_HOME/gate-receipts/<codex_project_id>/<run_id>.json`
- derived review snapshot: `reports/user-scorecard.review.json`
- generated result: `reports/user-scorecard.json`

## Core Rules

- score is a gated oversight model, not an automatic reward for shortest-path or minimal-action behavior
- writer cannot self-score, self-award, or self-excuse
- reviewer penalties still deduct, but confirmed work/performance may earn automatic completion credit after verify
- `user_review` is a protected user layer. It must not change unless there is an explicit user approval or task request.
- users may still add extra mid-stream awards for problems found and solved
- `requested_credit` records proposed additive credit before guardrails, while `credited_credit` records only the points that actually survive source checks and caps
- the anti-cheat layer treats score-surface manipulation as negative reward: suspicious points are denied, then penalized, then capped, and critical cases escalate to disqualifiers
- PASS is still determined by reviewer green, existing readiness, and clean-room verify
- disqualifiers outrank score
- generated global runtime elevates the scorecard layer into instruction-level guidance through `~/.codex/AGENTS.md`, and the single generated runtime hook replays an `iaw-closeout` reminder on prompt submit without replacing the explicit verify chain
- verify or release claims become authoritative only when a signed v1.3 `gate_receipt.json` exists in the authoritative state root and passes signature, identity, and changed-file binding checks

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
- `completion_score` now uses automatic verified-work awards plus optional user additions. Clean-room verify `PASS` or `WAIVED` grants the reserved baseline `24` points automatically only when authoritative clean-room evidence exists.
- `clean_room_verify:waived` must remain visible in `SUMMARY.md` Negative Findings even when the reserved completion credit is granted. `WAIVED` is creditable by runtime policy but is not equivalent to `PASS`.
- only `completion_score` has a user-award budget, currently `6` points. Other axes default to `0` user-award budget and are treated as score stuffing if a write is attempted.
- `prepare_user_scorecard_review.py` ignores snapshot/base `user_review` changes unless the payload carries an explicit `user_review_update_request` or `user_review_update_authorized: true`.
- official anti-cheat codes are `unauthorized_user_review_modification`, `reserved_derived_award_spoofing`, `non_user_source_award`, `excessive_bonus_request`, `reviewer_truth_tamper`, `writer_self_score_attempt`, `claimed_verification_without_evidence`, `test_deletion_or_weakening_without_rationale`, `score_policy_tamper_without_policy_update_workorder`, `evidence_backdating_or_stale_report_reuse`, `waiver_without_reason`, `gate_order_drift`, `protected_path_access_attempt`, `verification_command_substitution`, `evidence_manifest_mismatch`, `task_skip_or_merge_without_rationale`, `unsupported_transition_claim`, `verification_word_without_artifact`, `convention_drift`, `zombie_section_or_stale_claim`, `aesthetic_or_report_smoothing`, `cross_verification_disagreement_unresolved`, `result_fit_tweaking`, and `formula_or_code_simplification_without_case_check`.
- v1.2 additive scorecard summaries include `taste_gate`, `task_tree`, `repeated_verify`, `cross_verification`, `convention_lock`, `summary_coverage`, and `evidence_manifest`.
- Vibe Director L2+ close-out also requires `SLOP_LEDGER.json`; open blocking AI-slop entries, repo-discoverable questions, unsupported PASS language, and uncovered summary claims block until linked to evidence or downgraded.
- Active Subagent Delegation Layer modes (`read_only_scouts`, `bounded_workers`, `verification_pair`) require `DELEGATION_PLAN.json`, `SUBAGENT_TASKS.json`, `SUBAGENT_RESULTS.json`, `INTEGRATION_DECISION_LOG.json`, and `DELEGATION_LEDGER.json`; evidence-free subagent results, overlapping worker write scopes, unresolved conflicts, and partial verification marked PASS block L2+ close-out.
- Domain-Aware Mission Refresh L2+ close-out requires `MISSION_FRAME.json`, `ARTIFACT_REFRESH_MANIFEST.json`, and `MISSION_CLOSEOUT.json`; empty parent objectives, missing done-when evidence, open stale authoritative artifacts, blocked mission closeout, or final summary claims without mission/claim/coverage evidence block.
- `SUMMARY.md` should include a `## Negative Findings` section so fail, blocked, cap, penalty, waiver, and unresolved disagreement outcomes remain visible.
- score, PASS, credited, clean-room reflected, DQ clear, and release-ready language should downgrade to `UNKNOWN`, `UNVERIFIED`, `BLOCKED pending evidence`, or `WAIVED with reason` when a valid signed gate receipt is absent.
- test-change rationale should be recorded under the canonical heading `## Test Change Rationale:`. `Test Change Notes`, inline-after-colon forms, and legacy plain-label variants remain compatibility inputs only.
- placeholder-only entries such as `None`, `N/A`, `NA`, and `Not applicable` do not count as rationale, even when they include trailing punctuation.
- generated `hooks.json` is derived runtime state. If authority disables `runtime_hook` or clears its events, the generated hook file should disappear instead of leaving stale reminders behind.
- unauthorized `user_review` writes, reserved derived-award categories, non-user award sources, stale verification claims, and over-budget award requests are all recorded by the anti-cheat layer and can trigger warn, penalty, cap, or `DQ-011`.
- `user_review.awards[]` uses the schema `axis`, `points`, `reason`, and optional `category`, `evidence_refs`.
- `user_review.penalties[]` uses the same schema.
- `requested_credit[]` uses `axis`, `requested_points`, `source`, `reason`, `evidence_ref`.
- `credited_credit[]` uses `axis`, `requested_points`, `credited_points`, `source`, `capped`, `blocked`, `block_reason`.
- `anti_cheat_signals[]` uses `code`, `severity`, `confidence`, `decision`, `detected_by`, `provenance`, `points`, `reason`, `evidence_ref`.
- `disqualifiers[]` accepts `id`, `reason`, and optional `evidence_refs`.
- `anti_cheat_layer.decision_summary` records `highest_decision`, `counts`, and `auto_dq_signals`.
- published run evidence can come from `.agent-runs/<run_id>/EVIDENCE_MANIFEST.json`; legacy `reports/authority/fresh-evidence.json` remains a compatibility input.
- reward function:
  `raw_total_score = sum(axis_scores)`
  `guarded_total_score = max(raw_total_score - anti_cheat_penalty_points, 0)`
  `capped_total_score = min(guarded_total_score, all active caps)`
- `existing_readiness` carries upstream gate status and remaining manual close-out.
- `clean_room_verify` carries final verify status.
- default anti-cheat decision rules are:
  - low confidence -> warn
  - high confidence + medium severity -> penalty
  - high confidence + high severity -> cap
  - high confidence + critical severity + allowed auto-DQ code -> dq
- DQ-011 stays narrow. writer self-score attempts are blocked and visible, but do not auto-disqualify by themselves in v1.1.

Reviewer verdict events must include:

- `version`, `role`, `producer_lane`, `repo_root`, `git_sha`, `worktree_id`
- `codex_project_id`, `trace_id`, `generated_at`, `input_report_hash`
- `status`, `green`, `penalties`, `disqualifiers`, `notes`, `signature`

Unsigned, wrong-signature, or wrong-provenance verdicts are ignored and recorded as tamper findings.

## Commands

```bash
python "$DEVMGMT_ROOT/scripts/iaw_closeout.py" --workspace-root "$DEV_PRODUCT_ROOT/<project>" --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify
python "$DEVMGMT_ROOT/scripts/record_reviewer_verdict.py" --workspace-root "$DEV_PRODUCT_ROOT/<project>" --trace-id <trace_id> --role skeptic_reviewer --status APPROVED --green true --input-report <context.json>
```

`iaw_closeout.py` is the only accepted verify or release close-out entrypoint. It canonicalizes the workspace root, verifies the authority lease and evidence manifest, runs the global `prepare -> audit(pre-gate) -> delivery_gate -> audit(pre-export) -> export -> audit(post-export) -> score-layer` sequence, then issues the signed gate receipt.

The v1.3R gate receipt authority layer binds:

- signature policy: HMAC-SHA256 under the canonical truth-signature policy
- authority root: `$IAW_STATE_HOME/gate-receipts/<codex_project_id>/<run_id>.json`
- workspace identity: `workspace_root_realpath`, `git_root`, `codex_project_id`, `worktree_id`
- evidence identity: `changed_file_set_hash`, `changed_file_content_hash`, `evidence_manifest_hash`, policy hashes, and script hashes
- release semantics: only `mode=release` with `profile=L4` can carry authoritative release-scope claims; verify-mode receipts remain verification-scope only

The repo-local `.agent-runs/<run_id>/gate_receipt.json` file is a derived mirror only. The state-root receipt under `IAW_STATE_HOME` is the authority source and should be written atomically before any mirror copy is trusted.

`prepare_user_scorecard_review.py`는 reviewer truth를 생성하거나 수정하지 않습니다. workspace reports에서 context를 조립하고, signed verdict log를 읽어 snapshot에 렌더링만 합니다.

제품 저장소의 `python scripts/delivery_gate.py --mode verify` wrapper는 로컬 project gate를 끝낸 뒤 `iaw_closeout.py`를 호출해야 합니다. 로컬 project gate 결과는 `existing_readiness`와 `clean_room_verify`의 upstream evidence이며, global scorecard를 대체하지 않습니다.

## Gate Order

1. disqualifier check
2. reviewer green check
3. trace presence check
4. taste gate check
5. task tree check
6. evidence manifest check
7. repeated verify check
8. cross verification check
9. convention lock check
10. summary coverage check
11. axis floor check
12. anti-cheat guard check
13. platform cap check
14. existing readiness and manual close-out check
15. clean-room verify check

`quick` mode enforces disqualifiers only and records score output as advisory. `verify` and `release` enforce the full score gate, require fresh evidence only, and fail closed without a valid workspace authority lease.
