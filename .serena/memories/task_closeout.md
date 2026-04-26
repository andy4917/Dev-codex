# Task Closeout

Before closeout:

1. Re-check `git status --short --branch` and separate owned edits from unrelated dirt.
2. Run the exact touched code path directly where practical.
3. Run focused unit tests for the changed checker/script behavior.
4. Refresh impacted reports if the user asked for environment/global verification or if the touched script owns the report.
5. Run `git diff --check`.
6. For final score/gate/release claims, run `scripts/iaw_closeout.py` with the correct run id/profile.
7. If live system shutdown was requested, only power off after no blocker remains; do not shut down when driver install, live process health, commit/push, or verification is unresolved.

For Codex/Serena process incidents, inspect live process command lines and parent/child relationships. Duplicate Serena MCP roots above one are a blocked integrity condition unless explicitly waived.
