from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_workspace.py"
RENDER_MODULE_PATH = ROOT / "scripts" / "render_codex_runtime.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_workspace_contract", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load audit_workspace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_render_module():
    spec = importlib.util.spec_from_file_location("render_codex_runtime_contract", RENDER_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load render_codex_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditWorkspaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_dated_quarantine_root_is_invalid_policy(self) -> None:
        self.assertFalse(self.module.quarantine_root_policy_ok(Path("/home/andy4917/Dev-Management/quarantine/2026-04-16")))
        self.assertTrue(self.module.quarantine_root_policy_ok(Path("/home/andy4917/Dev-Management/quarantine")))

    def test_linux_source_of_truth_proof_uses_dedicated_user_override_input_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_agents = tmp / "linux" / "AGENTS.md"
            linux_config = tmp / "linux" / "config.toml"
            linux_user_override = tmp / "linux" / "user-config.toml"

            linux_agents.parent.mkdir(parents=True)
            linux_agents.write_text("# Generated Codex Workspace Contract\n", encoding="utf-8")
            linux_config.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "on-request"\n', encoding="utf-8")
            linux_user_override.write_text('model_reasoning_effort = "high"\n', encoding="utf-8")

            authority = {
                "_authority_path": str(tmp / "repo" / "contracts" / "workspace_authority.json"),
                "generation_targets": {
                    "global_runtime": {
                        "linux": {
                            "agents": str(linux_agents),
                            "config": str(linux_config),
                            "user_override_config": str(linux_user_override),
                        },
                    }
                }
            }
            runtime = {
                "linux_agents": linux_agents,
                "linux_config": linux_config,
                "linux_user_override_config": linux_user_override,
            }

            proof = self.module.build_linux_source_of_truth_proof(authority, runtime)

            self.assertEqual(proof["status"], "PASS")
            self.assertTrue(proof["linux_targets_are_distinct"])
            self.assertFalse(proof["config_override_probe"]["linux_config_used_as_override_source"])
            self.assertTrue(proof["config_override_probe"]["linux_user_override_used_as_override_source"])
            self.assertEqual(proof["linux_runtime_targets"]["user_override_config"], str(linux_user_override))

    def test_windows_policy_surface_check_reports_violation_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            windows_agents = tmp / "windows" / "AGENTS.md"
            windows_config = tmp / "windows" / "config.toml"
            windows_hooks = tmp / "windows" / "hooks.json"
            windows_skills = tmp / "windows" / "skills" / "dev-workflow"

            windows_agents.parent.mkdir(parents=True)
            windows_agents.write_text("GENERATED - DO NOT EDIT\n\n# Generated Codex Workspace Contract\n", encoding="utf-8")
            windows_config.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "never"\n', encoding="utf-8")
            windows_hooks.write_text("{}\n", encoding="utf-8")
            windows_skills.mkdir(parents=True)

            runtime = {
                "observed_windows_codex_home": windows_agents.parent,
                "observed_windows_policy_agents": windows_agents,
                "observed_windows_policy_config": windows_config,
                "observed_windows_policy_hooks": windows_hooks,
                "observed_windows_policy_skills": windows_skills,
            }
            linux_source_of_truth_proof = {
                "status": "PASS",
                "reasons": [],
            }
            config_provenance = {
                "windows_policy_surface_status": "BLOCKED",
                "windows_policy_surface_findings": [
                    {
                        "path": str(windows_agents),
                        "classification": "generated_policy_surface",
                        "disposition": "INERT_QUARANTINE",
                        "reason": "known generated Windows policy file remains present and should be removed because Codex App can actively read Windows ~/.codex config and instructions.",
                    },
                    {
                        "path": str(windows_config),
                        "classification": "generated_policy_surface",
                        "disposition": "INERT_QUARANTINE",
                        "reason": "known generated Windows policy file remains present and should be removed because Codex App can actively read Windows ~/.codex config and instructions.",
                    },
                    {
                        "path": str(windows_hooks),
                        "classification": "external_app_or_user_state",
                        "disposition": "MANUAL_REMEDIATION",
                        "reason": "unknown Windows policy-bearing file remains present on an app-readable active surface and requires manual review.",
                    },
                ],
            }
            active_config_smoke = {
                "windows_app_evidence_status": "PASS",
            }

            check = self.module.build_windows_policy_surface_check(
                runtime=runtime,
                config_provenance=config_provenance,
                active_config_smoke=active_config_smoke,
                linux_source_of_truth_proof=linux_source_of_truth_proof,
            )

            self.assertEqual(check["status"], "BLOCKED")
            self.assertEqual(check["policy_role"], "windows_policy_surface_violation")
            self.assertTrue(check["files"]["agents"]["exists"])
            self.assertTrue(check["files"]["config"]["has_generated_header"])
            self.assertEqual(check["known_generated_cleanup_candidates"], [str(windows_agents), str(windows_config)])
            self.assertEqual(check["unknown_windows_policy_files_blocking"], [])
            self.assertEqual(check["unknown_windows_policy_files_observed"], [str(windows_hooks)])
            self.assertEqual(check["linux_source_of_truth_proof"]["status"], "PASS")

    def test_workspace_dependency_surface_warns_only_when_feature_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir(parents=True)
            linux_config = tmp / ".codex" / "config.toml"
            linux_config.parent.mkdir(parents=True)
            linux_config.write_text("[features]\nworkspace_dependencies = true\n", encoding="utf-8")
            (reports / "workspace-dependency-surface.json").write_text(
                json.dumps(
                    {
                        "tool_status": "DISABLED_IN_APP_SETTINGS",
                        "available": False,
                    }
                ),
                encoding="utf-8",
            )
            runtime = {
                "linux_config": linux_config,
            }

            result = self.module.build_workspace_dependency_surface_check(tmp, runtime)
            self.assertEqual(result["status"], "WARN")
            self.assertTrue(result["feature_enabled"])

            linux_config.write_text("[features]\njs_repl = true\n", encoding="utf-8")
            result = self.module.build_workspace_dependency_surface_check(tmp, runtime)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["feature_enabled"])

    def test_rendered_global_config_includes_model_reasoning_and_features(self) -> None:
        render = _load_render_module()
        original_template_loader = render.load_context7_template
        original_serena_loader = render.load_serena_template
        render.load_context7_template = lambda: {}
        render.load_serena_template = lambda: {}
        self.addCleanup(setattr, render, "load_context7_template", original_template_loader)
        self.addCleanup(setattr, render, "load_serena_template", original_serena_loader)

        authority = {
            "generation_targets": {
                "global_config": {
                    "approval_policy": "on-request",
                    "sandbox_mode": "workspace-write",
                    "web_search": "cached",
                    "network_access": True,
                    "model": "gpt-5.4",
                    "model_reasoning_effort": "high",
                    "enabled_features": ["context7", "workspace-alignment"],
                    "trusted_projects": [
                        "/home/andy4917/Dev-Management",
                        "/home/andy4917/Dev-Workflow",
                    ],
                    "enabled_plugins": ["github@openai-curated"],
                },
            }
        }

        linux_config = render.render_config(authority)

        self.assertIn('model = "gpt-5.4"', linux_config)
        self.assertIn('model_reasoning_effort = "high"', linux_config)
        self.assertIn("[features]", linux_config)
        self.assertIn("context7 = true", linux_config)
        self.assertIn("workspace-alignment = true", linux_config)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            windows_agents = tmp / "windows" / "AGENTS.md"
            windows_config_path = tmp / "windows" / "config.toml"
            self.assertTrue(self.module.windows_policy_surface_absent(windows_agents, windows_config_path))

    def test_manual_overrides_are_merged_but_structural_features_stay_locked(self) -> None:
        render = _load_render_module()
        original_template_loader = render.load_context7_template
        original_serena_loader = render.load_serena_template
        render.load_context7_template = lambda: {
            "url": "https://example.com/mcp",
            "enabled": True,
            "required": False,
            "tool_timeout_sec": 30,
            "env_http_headers": {"CONTEXT7_API_KEY": "CONTEXT7_API_KEY"},
        }
        render.load_serena_template = lambda: {
            "enabled": True,
            "required": False,
            "startup_timeout_sec": 15,
            "tool_timeout_sec": 120,
            "command": "serena",
            "args": ["start-mcp-server", "--project-from-cwd", "--context=codex"],
            "disabled_tools": ["execute_shell_command", "remove_project"],
        }
        self.addCleanup(setattr, render, "load_context7_template", original_template_loader)
        self.addCleanup(setattr, render, "load_serena_template", original_serena_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            management = tmp / "Dev-Management"
            workflow = tmp / "Dev-Workflow"
            product = tmp / "Dev-Product"
            extra_project = product / "project-a"
            external_project = tmp / "Outside"
            linux_config_path = tmp / "linux" / "config.toml"
            linux_user_override_path = tmp / "linux" / "user-config.toml"
            windows_config_path = tmp / "windows" / "config.toml"

            extra_project.mkdir(parents=True)
            external_project.mkdir(parents=True)
            linux_config_path.parent.mkdir(parents=True)
            windows_config_path.parent.mkdir(parents=True)

            linux_user_override_path.write_text(
                """model_reasoning_effort = "high"

[mcp_servers.context7]
enabled = false
bearer_token_env_var = "CTX7_TOKEN"
command = "npx"
tool_timeout_sec = 45

[mcp_servers.context7.env_http_headers]
CONTEXT7_API_KEY = "CTX7_OVERRIDE"

[mcp_servers.serena]
command = "custom-serena"
startup_timeout_sec = 20
url = "https://invalid.example/mcp"

[features]
js_repl = false
js_repl_tools_only = true
remote_control = true

[projects."/tmp/Outside"]
trust_level = "trusted"

[memories]
no_memories_if_mcp_or_web_search = false
""",
                encoding="utf-8",
            )
            linux_config_path.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "on-request"\n', encoding="utf-8")
            windows_config_path.write_text(
                f"""approval_policy = "never"
sandbox_mode = "danger-full-access"

[projects."{extra_project}"]
trust_level = "trusted"

[projects."{external_project}"]
trust_level = "trusted"
""",
                encoding="utf-8",
            )

            authority = {
                "canonical_roots": {
                    "management": str(management),
                    "workflow": str(workflow),
                    "product": str(product),
                },
                "runtime_layering": {
                    "user_override_policy": {
                        "allowed_fields": ["model", "model_reasoning_effort", "features", "mcp_servers.context7", "mcp_servers.serena"],
                        "blocked_feature_overrides": ["js_repl_tools_only", "remote_control"],
                        "mcp_server_key_policies": {
                            "context7": {
                                "transport": "remote_http",
                                "allowed_override_keys": [
                                    "enabled",
                                    "required",
                                    "tool_timeout_sec",
                                    "startup_timeout_sec",
                                    "enabled_tools",
                                    "disabled_tools",
                                    "url",
                                    "env_http_headers",
                                ],
                                "forbidden_keys": [
                                    "bearer_token_env_var",
                                    "command",
                                    "args",
                                    "env",
                                    "env_vars",
                                    "cwd",
                                ],
                            },
                            "serena": {
                                "transport": "stdio",
                                "allowed_override_keys": [
                                    "enabled",
                                    "required",
                                    "tool_timeout_sec",
                                    "startup_timeout_sec",
                                    "enabled_tools",
                                    "disabled_tools",
                                    "command",
                                    "args",
                                    "env",
                                    "env_vars",
                                    "cwd",
                                ],
                                "forbidden_keys": [
                                    "url",
                                    "bearer_token_env_var",
                                    "http_headers",
                                    "env_http_headers",
                                ],
                            },
                        },
                        "protected_fields": ["canonical_roots"],
                    }
                },
                "generation_targets": {
                    "global_runtime": {
                        "linux": {"config": str(linux_config_path), "user_override_config": str(linux_user_override_path)},
                    },
                    "global_config": {
                        "approval_policy": "on-request",
                        "sandbox_mode": "workspace-write",
                        "web_search": "cached",
                        "network_access": True,
                        "model": "gpt-5.4",
                        "model_reasoning_effort": "medium",
                        "enabled_features": ["js_repl", "js_repl_tools_only", "tool_search"],
                        "trusted_projects": [
                            str(management),
                            str(workflow),
                            str(product),
                        ],
                        "enabled_plugins": ["github@openai-curated"],
                    },
                },
            }

            effective = render.build_effective_global_config(authority)
            linux_config = render.render_config(authority, effective_cfg=effective)

            self.assertEqual(effective["model_reasoning_effort"], "high")
            self.assertEqual(effective["approval_policy"], "on-request")
            self.assertEqual(effective["sandbox_mode"], "workspace-write")
            self.assertFalse(effective["features"]["js_repl"])
            self.assertNotIn("js_repl_tools_only", effective["features"])
            self.assertNotIn("remote_control", effective["features"])
            self.assertNotIn(str(extra_project), effective["trusted_projects"])
            self.assertNotIn(str(external_project), effective["trusted_projects"])
            self.assertFalse(effective["context7"]["enabled"])
            self.assertEqual(effective["context7"]["tool_timeout_sec"], 45)
            self.assertEqual(effective["context7"]["env_http_headers"]["CONTEXT7_API_KEY"], "CTX7_OVERRIDE")
            self.assertNotIn("bearer_token_env_var", effective["context7"])
            self.assertNotIn("command", effective["context7"])
            self.assertEqual(effective["serena"]["command"], "custom-serena")
            self.assertEqual(effective["serena"]["startup_timeout_sec"], 20)
            self.assertEqual(effective["serena"]["disabled_tools"], ["execute_shell_command", "remove_project"])
            self.assertNotIn("url", effective["serena"])
            self.assertEqual(effective["memories"]["no_memories_if_mcp_or_web_search"], False)

            self.assertIn('approval_policy = "on-request"', linux_config)
            self.assertIn('sandbox_mode = "workspace-write"', linux_config)
            self.assertIn('js_repl = false', linux_config)
            self.assertNotIn("js_repl_tools_only", linux_config)
            self.assertNotIn("remote_control", linux_config)
            self.assertNotIn(f'[projects."{extra_project}"]', linux_config)
            self.assertNotIn(f'[projects."{external_project}"]', linux_config)
            self.assertNotIn('bearer_token_env_var = "CTX7_TOKEN"', linux_config)
            self.assertNotIn('command = "npx"', linux_config)
            self.assertIn('[mcp_servers.serena]', linux_config)
            self.assertIn('command = "custom-serena"', linux_config)
            self.assertIn('disabled_tools = ["execute_shell_command", "remove_project"]', linux_config)
            self.assertNotIn('url = "https://invalid.example/mcp"', linux_config)
            self.assertIn("[memories]", linux_config)

    def test_rendered_hooks_include_scorecard_runtime_hook_commands(self) -> None:
        render = _load_render_module()
        authority = {
            "canonical_roots": {
                "management": "/home/andy4917/Dev-Management",
                "workflow": "/home/andy4917/Dev-Workflow",
                "product": "/home/andy4917/Dev-Product",
            },
            "canonical_execution_surface": {
                "id": "ssh-devmgmt-wsl",
                "host_alias": "devmgmt-wsl",
                "repo_root": "/home/andy4917/Dev-Management",
                "forbidden_primary_resolution": "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            },
            "forbidden_primary_runtime_paths": [
                "/mnt/c/Users/anise/.codex/bin/wsl",
                "/mnt/c/Users/anise/.codex/tmp/arg0",
                ".codex/bin/wsl/codex",
            ],
            "cleanup_policy": {
                "quarantine_root": "/home/andy4917/Dev-Management/quarantine",
            },
            "runtime_layering": {
                "restore_seed_policy": {
                    "preferred_windows_access_host": "wsl.localhost",
                    "terminal_restore_policy": "background",
                    "conversation_detail_mode": "steps",
                },
                "user_override_policy": {
                    "allowed_fields": ["model"],
                    "protected_fields": ["canonical_roots"],
                },
            },
                "generation_targets": {
                    "global_runtime": {
                        "linux": {
                            "launcher": "/home/andy4917/.local/bin/codex",
                        },
                    },
                "scorecard": {
                    "policy": "/home/andy4917/Dev-Management/contracts/user_score_policy.json",
                    "disqualifiers": "/home/andy4917/Dev-Management/contracts/disqualifier_policy.json",
                    "reviewer_verdict_root": "/home/andy4917/.codex/state/reviewer-verdicts",
                    "review_snapshot": "/home/andy4917/Dev-Management/reports/user-scorecard.review.json",
                    "closeout": "/home/andy4917/Dev-Management/scripts/iaw_closeout.py",
                    "delivery_gate": "/home/andy4917/Dev-Management/scripts/delivery_gate.py",
                    "summary_export": "/home/andy4917/Dev-Management/scripts/export_user_score_summary.py",
                    "workspace_authority_root": "/home/andy4917/.codex/state/workspace-authority",
                    "receipt_state_root": "/home/andy4917/.codex/state/iaw",
                    "gate_receipt_root": "/home/andy4917/.codex/state/gate-receipts",
                    "runtime_hook": {
                        "script": "/home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py",
                        "linux_command_prefix": "python3",
                        "windows_generation_enabled": False,
                        "events": {
                            "UserPromptSubmit": {"matcher": ".*"},
                        },
                    }
                }
            }
        }
        authority["control_thread_policy"] = {"name": "Dev-Management Control", "remote_host": "devmgmt-wsl"}
        authority["worktree_policy_summary"] = {"persistent_ops_worktree_allowed": False, "task_worktrees_are_ephemeral": True}

        rendered_agents = render.render_agents(authority, windows=False)
        linux_hooks = json.loads(render.render_hooks(authority, windows=False))
        windows_hooks = render.render_hooks(authority, windows=True)
        wrapper = render.render_windows_hook_wrapper(authority)
        launcher_script = render.render_linux_launcher(authority)

        self.assertIn("binding instruction-level guidance", rendered_agents)
        self.assertIn("Canonical global close-out command", rendered_agents)
        self.assertIn("iaw_closeout.py --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify", rendered_agents)
        self.assertIn("Required scorecard layer command", rendered_agents)
        self.assertIn("run_score_layer.py --json", rendered_agents)
        self.assertIn("Codex App is the primary user control surface and remote session control surface", rendered_agents)
        self.assertIn("Linux generated runtime files are outputs only", rendered_agents)
        self.assertIn("must not generate policy-bearing Windows ~/.codex", rendered_agents)
        self.assertIn("Optional user override source is /home/andy4917/.codex/user-config.toml only", rendered_agents)
        self.assertIn("Linux-native Codex CLI on the canonical remote login-shell PATH is the canonical agent binary", rendered_agents)
        self.assertIn("PATH contamination is a client-surface warning only", rendered_agents)
        self.assertIn("Windows-mounted launchers such as `/mnt/c/Users/anise/.codex/bin/wsl/codex` are external dependencies", rendered_agents)
        self.assertIn("Before modifying anything", rendered_agents)
        self.assertIn("After work", rendered_agents)
        self.assertIn("telepathy, workspace_dependencies, danger-full-access", rendered_agents)
        self.assertIn("activate the current project or worktree with Serena", rendered_agents)
        self.assertIn("Use Context7 before changing external libraries", rendered_agents)
        self.assertIn("Dev-Management Control", rendered_agents)
        self.assertIn("Persistent ops worktrees are optional", rendered_agents)
        self.assertIn("/home/andy4917/.codex/state/iaw/gate-receipts", rendered_agents)
        self.assertEqual(set(linux_hooks["hooks"]), {"UserPromptSubmit"})
        self.assertEqual(
            linux_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            "python3 /home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py --event UserPromptSubmit",
        )
        self.assertIsNone(windows_hooks)
        self.assertIsNone(wrapper)
        self.assertIsNotNone(launcher_script)
        self.assertIn('host_alias="devmgmt-wsl"', launcher_script)
        self.assertIn("canonical agent binary: Linux-native Codex CLI", launcher_script)
        self.assertIn("forbidden primary runtime: /mnt/c/Users/anise/.codex/bin/wsl/codex", launcher_script)

    def test_sync_generated_text_removes_stale_hooks_file(self) -> None:
        render = _load_render_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            hook_path = Path(tmpdir) / "hooks.json"
            hook_path.write_text('{"hooks": {"UserPromptSubmit": []}}\n', encoding="utf-8")

            render.sync_generated_text(hook_path, None)

            self.assertFalse(hook_path.exists())

    def test_wsl_launcher_check_detects_stale_linux_shim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_launcher = tmp / "linux-home" / ".local" / "bin" / "codex"
            linux_config = tmp / "linux-home" / ".codex" / "config.toml"
            windows_config = tmp / "windows-home" / ".codex" / "config.toml"
            windows_launcher = tmp / "windows-home" / ".codex" / "bin" / "wsl" / "codex"

            linux_launcher.parent.mkdir(parents=True)
            linux_config.parent.mkdir(parents=True)
            windows_config.parent.mkdir(parents=True)
            windows_launcher.parent.mkdir(parents=True)

            linux_launcher.write_text(
                "#!/usr/bin/env bash\n"
                "# GENERATED - DO NOT EDIT\n"
                'target="/mnt/c/Users/anise/.codex/bin/wsl/old-codex"\n'
                'exec "$target" "$@"\n',
                encoding="utf-8",
            )
            linux_config.write_text('approval_policy = "on-request"\n', encoding="utf-8")
            windows_config.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "on-request"\n', encoding="utf-8")
            windows_launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            authority = {
                "forbidden_primary_runtime_paths": [
                    "/mnt/c/Users/anise/.codex/bin/wsl",
                    "/mnt/c/Users/anise/.codex/tmp/arg0",
                    ".codex/bin/wsl/codex",
                ],
                "windows_app_state": {
                    "codex_home": str(windows_config.parent),
                },
                "generation_targets": {
                    "global_runtime": {
                        "linux": {
                            "launcher": str(linux_launcher),
                            "config": str(linux_config),
                        },
                    }
                }
            }
            runtime = {
                "linux_launcher": linux_launcher,
                "linux_config": linux_config,
                "windows_config": windows_config,
                "windows_wsl_launcher": windows_launcher,
            }

            check = self.module.build_wsl_launcher_check(authority, runtime=runtime)

        self.assertEqual(check["status"], "BLOCKED")
        self.assertEqual(check["configured_target"], "/mnt/c/Users/anise/.codex/bin/wsl/old-codex")
        self.assertIn("forbidden Windows-mounted launcher", " ".join(check["reasons"]))

    def test_audit_detects_forbidden_feature_flags_and_active_runtime_restore_seed(self) -> None:
        authority = {
            "hardcoding_definition": {
                "feature_rules": {
                    "forbidden_feature_flags": ["use_agent_identity"],
                },
                "path_rules": {
                    "legacy_repo_paths_to_remove": [
                        "/legacy/runtime-root",
                    ],
                },
            },
            "runtime_layering": {
                "restore_seed_policy": {
                    "preferred_windows_access_host": "wsl.localhost",
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            config_path = tmp / "config.toml"
            config_path.write_text(
                """[features]
use_agent_identity = true
remote_connections = true
""",
                encoding="utf-8",
            )
            state_path = tmp / ".codex-global-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "projectless-thread-ids": ["thread-1"],
                        "thread-workspace-root-hints": {"thread-1": "/mnt/c/Users/anise/Documents/Codex"},
                        "active-workspace-roots": ["\\\\wsl$\\Ubuntu\\home\\andy4917\\Dev-Management"],
                        "electron-saved-workspace-roots": ["/mnt/c/Users/anise/Documents/Codex"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            forbidden = self.module.detect_forbidden_feature_flags([config_path], authority)
            runtime = self.module.detect_runtime_restore_seed_violations(state_path, authority)
            tamper_events = self.module.build_tamper_events(
                old_path_refs=[],
                forbidden_features=forbidden,
                runtime_restore_seed_violations=runtime,
                score_policy_tamper_events=[],
            )

            self.assertEqual([item["feature"] for item in forbidden], ["use_agent_identity"])
            self.assertEqual(
                {item["category"] for item in runtime},
                {"projectless_restore_refs", "thread_workspace_root_hints", "active_workspace_roots", "electron_saved_workspace_roots"},
            )
            self.assertIn("DQ-010", tamper_events[0]["disqualifier_ids"])

    def test_audit_accepts_allowed_wsl_hosts_from_authority(self) -> None:
        authority = {
            "hardcoding_definition": {
                "feature_rules": {
                    "forbidden_feature_flags": [],
                },
                "path_rules": {
                    "legacy_repo_paths_to_remove": [],
                },
            },
            "runtime_layering": {
                "restore_seed_policy": {
                    "preferred_windows_access_host": "wsl.localhost",
                    "allowed_windows_access_hosts": ["wsl.localhost", "wsl$"],
                }
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / ".codex-global-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "projectless-thread-ids": [],
                        "thread-workspace-root-hints": {},
                        "active-workspace-roots": ["\\\\wsl$\\Ubuntu\\home\\andy4917\\Dev-Workflow"],
                        "electron-saved-workspace-roots": [
                            "\\\\wsl.localhost\\Ubuntu\\home\\andy4917\\Dev-Management",
                            "\\\\wsl$\\Ubuntu\\home\\andy4917\\Dev-Workflow",
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            runtime = self.module.detect_runtime_restore_seed_violations(state_path, authority)

        self.assertEqual(runtime, [])

    def test_partition_runtime_restore_seed_violations_marks_projectless_and_hints_as_warning_only(self) -> None:
        violations = [
            {"category": "projectless_restore_refs", "reason": "stale thread refs"},
            {"category": "thread_workspace_root_hints", "reason": "stale hints"},
            {"category": "active_workspace_roots", "reason": "stale active roots"},
        ]

        blocking, warning_only = self.module.partition_runtime_restore_seed_violations(violations)

        self.assertEqual([item["category"] for item in blocking], ["active_workspace_roots"])
        self.assertEqual(
            [item["category"] for item in warning_only],
            ["projectless_restore_refs", "thread_workspace_root_hints"],
        )

    def test_detect_score_policy_tamper_requires_structured_policy_update_workorder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            management = tmp / "Dev-Management"
            workflow = tmp / "Dev-Workflow"
            management.mkdir()
            workflow.mkdir()
            (management / ".git").mkdir()
            (workflow / ".git").mkdir()
            (management / "contracts").mkdir()
            (management / "contracts" / "user_score_policy.json").write_text('{"version": 2}\n', encoding="utf-8")
            (workflow / ".agent-runs" / "2026-04-19-run").mkdir(parents=True)

            original_git_lines = self.module.git_lines
            def fake_git_lines(_repo_root, *args):
                if args[:4] == ("diff", "--name-only", "HEAD", "--"):
                    return ["contracts/user_score_policy.json"]
                if args[:3] == ("diff", "--name-only", "HEAD"):
                    return ["contracts/user_score_policy.json", "tests/test_prepare_user_scorecard_review.py", "reports/user-scorecard.json"]
                return []

            self.module.git_lines = fake_git_lines
            self.addCleanup(setattr, self.module, "git_lines", original_git_lines)

            events = self.module.detect_score_policy_tamper_events(management, workflow)
            self.assertEqual(events[0]["category"], "score_policy_tamper_without_policy_update_workorder")
            self.assertEqual(events[0]["disqualifier_ids"], ["DQ-011"])

            (workflow / "DESIGN_REVIEW.md").write_text("Policy Update Workorder:\nallowed\n", encoding="utf-8")
            (workflow / ".agent-runs" / "2026-04-19-run" / "WORKORDER.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "2026-04-19-run",
                        "canonical_repo": str(management),
                        "support_repo": str(workflow),
                        "objective": "policy update",
                        "allowed_change_zones": [str(management)],
                        "protected_paths": ["user_score_policy.json"],
                        "acceptance_criteria": ["policy update path"],
                        "verification_commands": ["pytest"],
                        "rollback_plan_required": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (workflow / ".agent-runs" / "2026-04-19-run" / "EVIDENCE_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": "2026-04-19-run",
                        "base_commit": "abc",
                        "head_commit": "def",
                        "changed_files": ["contracts/user_score_policy.json"],
                        "commands": [],
                        "artifacts": [],
                        "waivers": [],
                        "policy_hashes": {
                            "current": {},
                            "before": {"user_score_policy.json": "old"},
                            "after": {"user_score_policy.json": "new"},
                        },
                        "state_history": [{"state": "SCORING", "entered_at": "2026-04-19T00:00:00Z"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(self.module.detect_score_policy_tamper_events(management, workflow), [])


if __name__ == "__main__":
    unittest.main()
