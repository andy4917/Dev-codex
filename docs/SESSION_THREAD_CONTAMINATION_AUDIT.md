# Session And Thread Contamination Audit

## Scope

- audited repo root: current delivery repo root
- audit date: `2026-04-15`
- audit mode: hostile reread with cross-verification
- cross-check method:
  - local reread of reports, contracts, scripts, docs, and `.codex` runtime files
  - 3 independent explorer passes on runtime-surface drift, toolchain or runtime defects, and gate anti-patterns

## Counting Rules

- fixed defect instance:
  - count one concrete defective behavior once, even if multiple reports repeated it
- active blocker instance:
  - count one unresolved prerequisite or missing app action once
- analytical warning instance:
  - count one open anti-pattern that can distort interpretation without directly blocking the current gate
- legacy marker hit:
  - count one explicit stale-looking text marker in selected runtime-surface files, even if it appears as a deny-list or historical reject

## Executive Stats

| Metric | Count |
| --- | ---: |
| working-set dirty paths observed during audit | 77 |
| fixed defect instances | 27 |
| active blocker instances | 23 |
| open analytical warning instances | 5 |
| remaining legacy or stale textual marker hits | 21 |
| unresolved stale refs in generated path visibility report | 0 |

## Working-Set Scope

| Top-level area | Paths in current dirty set |
| --- | ---: |
| `scripts` | 32 |
| `docs` | 25 |
| `.codex` | 6 |
| all other top-level entries combined | 14 |

This dirty-set count is the observed current workspace scope, not a claim that every path was created in this thread.

## Fixed Defect Families

| Family | Fixed instances | What was wrong |
| --- | ---: | --- |
| unsafe probe and surface mix | 2 | `wt` probing triggered Windows Terminal Help popups, and execution-surface audit mixed WSL PATH into Windows inventory |
| shell and runtime wrapper defects | 5 | WSL runtime env bootstrapping was incomplete or inconsistent, timeout was dropped, and Windows `python` availability was hardcoded |
| repair orchestration defects | 4 | install or repair logic had missing imports, wrong Windows-package-manager driving, unstable PATH repair, and pipx inconsistencies |
| report truth and residue corruption | 6 | dry-run overwrote live truth, preview residue survived, stale Context7 evidence could persist, and stale Syncthing residue was misclassified |
| gate and check integrity defects | 4 | Local Environments proof was spoofable, delivery gate masked later blockers, bootstrap report truth drifted, and bootstrap dry-run still triggered downstream work |
| legacy guardrail and runtime-model drift | 5 | obsolete roots, old policy paths, stale rotating-slot assumptions, permissive mirror detection, and runtime-doc model drift survived in environment code |
| artifact hygiene residue | 1 | a preview report remained in `reports/` and had to be deleted |

## Active Blockers

| Family | Active instances | Detail |
| --- | ---: | --- |
| WSL required toolchain gaps | 15 | `zip`, `unzip`, `jq`, `tree`, `bubblewrap`, `build_essential`, `make`, `gcc`, `gxx`, `cmake`, `pkg_config`, `python3_pip`, `python3_venv`, `dos2unix`, `sqlite3` |
| WSL non-interactive privilege boundary | 1 | `sudo` passwordless access is unavailable for apt repair |
| Local Environments app registration gap | 5 | no app-generated `.codex` file plus 4 missing actions: `Setup`, `Smoke`, `Full Verify`, `Delivery Gate` |
| release close-out and verify gap | 2 | `human_review` is still pending, and `inventory_cpp_core` is still not built on the WSL verification surface |

Total active blocker instances: `23`.

## Open Analytical Warnings

| Warning | Count | Why it matters |
| --- | ---: | --- |
| execution-surface optimism | 2 | `execution-surfaces.json` can show both surfaces `PASS` because it checks repo runtime minima, while full WSL baseline remains `BLOCKED` |
| spoofable or replayable checks | 2 | one check remains file-pattern based, and Context7 can replay matching evidence snapshots when the protected-change set does not move |
| hidden readiness compression | 1 | gate top-level reasons stay summarized while detailed failures stay nested under readiness |

Total open analytical warning instances: `5`.

## Remaining Legacy Marker Hits

| File | Hits | Meaning |
| --- | ---: | --- |
| `docs/runtime/HANDOFF.md` | 5 | mostly explicit rejects of old checkout or mirror assumptions plus fixed external-root references |
| `docs/runtime/ACTIVE_MEMORY.md` | 2 | fixed external-root references that still look legacy-like |
| `docs/runtime/WORKSPACE_ALIGNMENT.md` | 5 | deny-list labels and old-root rejection text |
| `.codex/bin/check-delivery-env` | 1 | stale default-surface sentinel text still exists as a banned marker |
| `scripts/check_path_visibility.py` | 4 | stale-path and mirror detector strings |
| `scripts/guardrails/check_contract_surfaces.py` | 4 | banned stale phrases and stale default-surface sentinel |

Total remaining marker hits: `21`.

Important:

- `reports/path-visibility.json` is clean.
- the remaining hits are mostly deny-lists, historical rejects, or fixed external-root anchors.
- they are legacy-looking text, but they are not the same as unresolved stale refs in active reports.

## Why Legacy And Pollution Kept Reappearing

1. one operational truth was duplicated across multiple scripts instead of reusing one probe path
2. preview and authoritative reports originally shared filenames
3. some gate layers compressed detail, which hid blocker shape until hostile rereads expanded it
4. app-generated Codex state lives outside repo control, so policy can be correct while proof stays blocked
5. old slot language survived inside deny-lists, guardrails, and historical guidance after the operating model changed

## Prevention Patches Applied

1. execution-surface auditing now reuses the same Windows and WSL probe logic as the main toolchain audit
2. dry-run outputs are separated from live truth reports
3. delivery gate now keeps later blockers visible after an earlier failure
4. Local Environments evidence is constrained to app-generated file globs plus structured parsing
5. Context7 evidence now tracks the current protected-change set instead of trusting stale report state
6. preview report residue was removed from `reports/`

## Current Conclusion

- environment truth is substantially cleaner than before this hostile audit
- report and gate truth are now closer to the real machine state
- the remaining problems are no longer mostly hidden corruption; they are mostly real external or manual blockers
- full close-out is still blocked until WSL apt prerequisites, Codex App Local Environments registration, `inventory_cpp_core` build on WSL verify surface, and human review are closed
