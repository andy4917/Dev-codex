GENERATED - DO NOT EDIT

# Generated Codex Workspace Contract

- Authority file: `/home/andy4917/Dev-Management/contracts/workspace_authority.json`
- Canonical roots are fixed to `/home/andy4917/Dev-Management`, `/home/andy4917/Dev-Workflow`, `/home/andy4917/Dev-Product`.
- Global topology, classification, cleanup, and generation rules derive only from the authority file.
- Do not keep hardcoded legacy paths, fallback copies, shadow configs, deprecated outputs, or backup policy copies outside the authority file or generated runtime files.
- Project-specific rules are allowed only inside `/home/andy4917/Dev-Product/<project>/` as `AGENTS.md`, `.codex/config.toml`, `contracts/`, and truly project-specific verify scripts.
- Treat auth, history, logs, caches, sqlite, recent workspaces, and favorites as runtime state, not policy.
- Runtime layers are fixed as L0 authority -> L1 user override -> L2 generated mirror -> L3 runtime restore seed -> L4 volatile runtime.
- L1 user override may change only `model, model_reasoning_effort, approval_policy, sandbox_mode, web_search, network_access, mcp_servers.context7, mcp_servers.serena, features, ux, workspace_preference, memories, trusted_projects_within_canonical_roots` and must never override `canonical_roots, workspace_authority, safety_invariants, non_canonical_root_admission`.
- Structural feature overrides stay pinned to authority defaults: `js_repl_tools_only, remote_control`.
- Runtime restore seed is derived-only, preserves named threads, drops stale projectless restore refs, removes stale remote environment state, and prefers `wsl.localhost` UNC roots.
- Terminal restore must stay in `background` mode and conversation detail should default to `steps` while stabilization is in progress.
- Use `.git` as the only project root marker.
- Codex App is the primary user control surface and remote session control surface. It is not the execution authority and it is not the policy authority.
- Windows host is the app host and SSH client surface. It remains a user or client surface, not the execution authority.
- Dev-Management is the policy authority and runtime authority for generated runtime files, audits, repairs, and score gates.
- Canonical execution runs only through `ssh-devmgmt-wsl` via host alias `devmgmt-wsl`.
- Linux-native Codex CLI on the canonical remote login-shell PATH is the canonical agent binary.
- Observed app remotes such as `andy4917@localhost:22` are evidence only and must not be promoted into authority without verification.
- Windows-mounted launchers such as `/mnt/c/Users/anise/.codex/bin/wsl/codex` are external dependencies and are forbidden as the primary runtime.
- Generated config mirrors are outputs only. Generated mirrors must never be used as render input, authority input, or optional user override input.
- Optional user override source is /home/andy4917/.codex/user-config.toml only.
- When canonical SSH execution passes, Codex App PATH contamination is a client-surface warning only; it does not replace the canonical execution authority.
- Local shell execution remains blocked while live codex resolution or PATH precedence still points at a forbidden Windows-mounted launcher.
- Relationship model:
  Codex App on Windows
    -> SSH remote connection
    -> devmgmt-wsl
    -> Linux-native Codex CLI
    -> Dev-Management guard/audit/repair
    -> repo changes/tests/reports
- Forbidden relation:
  Codex App on Windows
    -> Windows-mounted launcher
    -> `/mnt/c/Users/anise/.codex/bin/wsl/codex`
    -> primary execution runtime
- Do not hand-edit generated AGENTS, config, shim, or preview runtime files; rerender them from the authority repo instead.
- User app setup path: Restart Codex App -> Settings > Connections -> select devmgmt-wsl -> open /home/andy4917/Dev-Management -> sign in if prompted -> send the readiness prompt.
- Keep a pinned Codex App control thread named `Dev-Management Control` on `devmgmt-wsl` for readiness, runtime checks, config provenance, score layer, audit, startup, artifact hygiene, and task routing.
- The pinned control thread defaults to the local remote project, not Worktree mode, and it is not the execution authority or policy authority. App memories and thread context remain hints only.
- Persistent ops worktrees are optional and remain non-authority execution surfaces only. Task worktrees are ephemeral by default, generated mirrors must still bind to `/home/andy4917/Dev-Management`, and implementation work should use separate scoped worktrees when worktree mode is chosen.
- If a persistent ops worktree is explicitly enabled later, use it only for recurring audits, report generation, readiness checks, app usability checks, and non-destructive diagnostics.
- User should not manually edit generated config, launcher, PATH, SSH, hooks, or system files unless a Dev-Management report explicitly asks for it.
- Before code work, activate the current project or worktree with Serena when it is available.
- Check Serena onboarding and project memories before major code changes.
- Prefer Serena symbol and reference tools over repeated whole-file reads when Serena is available.
- Use Context7 before changing external libraries, frameworks, APIs, configuration, or migration behavior.
- If Serena or Context7 is unavailable, report the failure and use a clearly stated fallback.
- Hooks may trigger checks, but hooks are not the final enforcement surface; run deterministic verification before finishing work.
- Before modifying anything:
  1. Identify repo root and branch.
  2. Run or inspect git status.
  3. Classify dirty files as in-scope or unrelated.
  4. Run or inspect instruction guard.
  5. Run or inspect global runtime status.
  6. Run config provenance check if touching config, app, runtime, or toolchain surfaces.
  7. Run startup workflow check if code modification is requested.
  8. Check Context7 requirement if protected files may change.
  9. Do not proceed if a generated mirror is being used as an input source.
  10. Do not proceed if the forbidden Windows launcher is the primary runtime.
- During work:
  1. Touch only in-scope files.
  2. Do not manually edit generated mirrors.
  3. Do not edit app binaries or external dependencies.
  4. Do not introduce hardcoded user paths unless authority explicitly allows them.
  5. Do not add fallback paths without authority and tests.
  6. Do not preserve stale legacy feature names.
  7. Do not create fake Context7 or Serena evidence.
  8. Record toolchain, subagent, skill, plugin, hook, and workspace dependency usage if used.
- After work:
  1. Clean stale reports or drafts created by this task unless they are final evidence.
  2. Separate final reports from transient scratch artifacts.
  3. Run hardcoded path scan.
  4. Run stale feature flag scan.
  5. Run fallback or legacy wording scan.
  6. Run generated mirror provenance check.
  7. Run config self-feed check.
  8. Run git diff --check.
  9. Run relevant tests.
  10. Report untouched unrelated changes.
  11. Report remaining BLOCKED or WARN items.
  12. Commit only after audit, test, and report status is clear.
- Mandatory scan keywords: telepathy, workspace_dependencies, danger-full-access, approval_policy = never, sandbox_mode = danger-full-access, fallback, legacy, hardcoded, /mnt/c/Users/anise/.codex/bin/wsl, .codex/tmp/arg0, generated mirror, self-feed, user-config.toml, chronicle.
- User penalty scorecard is global and canonical at `/home/andy4917/Dev-Management/contracts/user_score_policy.json` and `/home/andy4917/Dev-Management/contracts/disqualifier_policy.json`.
- Writer self-scoring, writer bonus scores, shadow scores, and fallback scores are forbidden. User review is a protected layer and cannot change without explicit user approval or task request; confirmed work/performance awards are derived automatically, users may add extra awards mid-task only within budget, and the anti-cheat layer denies, penalizes, caps, or disqualifies score manipulation attempts.
- Reviewer truth is append-only runtime state under `/home/andy4917/.codex/state/reviewer-verdicts`; `/home/andy4917/Dev-Management/reports/user-scorecard.review.json` is a derived human-readable snapshot only.
- Disqualifiers outrank score. PASS still requires reviewer green, existing readiness, and clean-room verify.
- The global scorecard layer is binding instruction-level guidance across canonical roots. Do not ignore requested vs credited score, anti-cheat output, gate status, summary export, or final audit results.
- Product-local `python scripts/delivery_gate.py --mode verify` wrappers are valid close-out surfaces only when they produce fresh evidence, refresh the derived review snapshot, then delegate into the canonical global close-out command.
- Canonical global close-out command: `python /home/andy4917/Dev-Management/scripts/iaw_closeout.py --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify`.
- Canonical global scorecard internals remain: `python /home/andy4917/Dev-Management/scripts/prepare_user_scorecard_review.py --workspace-root <repo> --mode verify` -> `python /home/andy4917/Dev-Management/scripts/audit_workspace.py --phase pre-gate --blocking-only --write-report` -> `python /home/andy4917/Dev-Management/scripts/delivery_gate.py --mode verify --workspace-root <repo>` -> `python /home/andy4917/Dev-Management/scripts/audit_workspace.py --phase pre-export --blocking-only --write-report` -> `python /home/andy4917/Dev-Management/scripts/export_user_score_summary.py` -> `python /home/andy4917/Dev-Management/scripts/audit_workspace.py --phase post-export --write-report` -> `python /home/andy4917/Dev-Management/scripts/run_score_layer.py --json`.
- Generated runtime hooks remain trigger-only. Windows prompt-submit wrappers are intentionally disabled to avoid visible terminal churn; audit, tests, and score layer remain the final enforcement gates.
- Verify/release require fresh evidence manifests plus a signed workspace authority lease under `/home/andy4917/.codex/state/workspace-authority` and a signed gate receipt under `/home/andy4917/.codex/state/iaw/gate-receipts`.
- Required scorecard close-out command: `python /home/andy4917/Dev-Management/scripts/iaw_closeout.py --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify`
- Required scorecard gate command: `python /home/andy4917/Dev-Management/scripts/delivery_gate.py --mode verify`
- Required scorecard summary command: `python /home/andy4917/Dev-Management/scripts/export_user_score_summary.py`
- Required scorecard layer command: `python /home/andy4917/Dev-Management/scripts/run_score_layer.py --json`
- Required final verification command: `python /home/andy4917/Dev-Management/scripts/audit_workspace.py --write-report`
- Ambiguous cleanup targets go to `/home/andy4917/Dev-Management/quarantine` before deletion.
