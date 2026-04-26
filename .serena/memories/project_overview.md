# Dev-Management Overview

Dev-Management is the Windows-native policy, verification, and environment-management authority for the user's development workstation. The canonical workspace root is `C:\Users\anise\code`, and this repo owns contracts, checkers, reports, and maintenance scripts for Codex App, Serena/Context7 evidence roles, app-state maintenance, score hooks, and toolchain baseline verification.

Primary stack: Python scripts and `devmgmt_runtime` helpers, JSON contracts under `contracts/`, Markdown docs under `docs/`, generated verification reports under `reports/`, and Python unittest suites under `tests/`.

Key authority files: `docs/GLOBAL_AGENT_WORKFLOW.md`, `contracts/workspace_authority.json`, `contracts/global_agent_workflow_policy.json`, `contracts/toolchain_policy.json`, `contracts/user_dev_environment_policy.json`, and `contracts/path_authority_policy.json`.
