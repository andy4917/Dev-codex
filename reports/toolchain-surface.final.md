# Toolchain Surface

- Status: WARN
- Workspace dependency tools: DISABLED_IN_APP_SETTINGS
- Plugins: github@openai-curated
- Features: apply_patch_freeform, artifact, child_agents_md, chronicle, code_mode, code_mode_only, codex_git_commit, codex_hooks, default_mode_request_user_input, enable_fanout, exec_permission_approvals, guardian_approval, image_generation, js_repl, memories, multi_agent_v2, prevent_idle_sleep, realtime_conversation, remote_connections, request_permissions_tool, runtime_metrics, shell_zsh_fork, skill_env_var_dependency_prompt, tool_search, undo
- MCP servers: context7, serena

## Warnings
- Multiple terminal PATH mismatch is present.
- Hook readiness is degraded or advisory-only.
- Windows hooks are intentionally disabled and remain non-authoritative trigger surfaces only.
