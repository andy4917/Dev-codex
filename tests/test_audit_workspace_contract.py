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

    def test_rendered_global_config_includes_model_reasoning_and_features_and_mirrors_match(self) -> None:
        render = _load_render_module()
        original_template_loader = render.load_context7_template
        render.load_context7_template = lambda: {}
        self.addCleanup(setattr, render, "load_context7_template", original_template_loader)

        authority = {
            "generation_targets": {
                "global_runtime": {
                    "windows_mirror": {
                        "generated_header": "GENERATED - DO NOT EDIT",
                    }
                },
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

        linux_config = render.render_config(authority, windows=False)
        windows_config = render.render_config(authority, windows=True)

        self.assertIn('model = "gpt-5.4"', linux_config)
        self.assertIn('model_reasoning_effort = "high"', linux_config)
        self.assertIn("[features]", linux_config)
        self.assertIn("context7 = true", linux_config)
        self.assertIn("workspace-alignment = true", linux_config)
        self.assertEqual(self.module.strip_generated_header(linux_config), self.module.strip_generated_header(windows_config))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_agents = tmp / "linux" / "AGENTS.md"
            linux_config_path = tmp / "linux" / "config.toml"
            windows_agents = tmp / "windows" / "AGENTS.md"
            windows_config_path = tmp / "windows" / "config.toml"

            linux_agents.parent.mkdir(parents=True)
            windows_agents.parent.mkdir(parents=True)

            linux_agents.write_text("# Generated Codex Workspace Contract\n", encoding="utf-8")
            linux_config_path.write_text(linux_config, encoding="utf-8")
            windows_agents.write_text("GENERATED - DO NOT EDIT\n\n# Generated Codex Workspace Contract\n", encoding="utf-8")
            windows_config_path.write_text(windows_config, encoding="utf-8")

            self.assertTrue(
                self.module.generated_runtime_mirror_matches_linux(
                    linux_agents=linux_agents,
                    linux_config=linux_config_path,
                    windows_agents=windows_agents,
                    windows_config=windows_config_path,
                )
            )

    def test_manual_overrides_are_merged_but_structural_features_stay_locked(self) -> None:
        render = _load_render_module()
        original_template_loader = render.load_context7_template
        render.load_context7_template = lambda: {"url": "https://example.com/mcp", "enabled": True}
        self.addCleanup(setattr, render, "load_context7_template", original_template_loader)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            management = tmp / "Dev-Management"
            workflow = tmp / "Dev-Workflow"
            product = tmp / "Dev-Product"
            extra_project = product / "project-a"
            external_project = tmp / "Outside"
            linux_config_path = tmp / "linux" / "config.toml"
            windows_config_path = tmp / "windows" / "config.toml"

            extra_project.mkdir(parents=True)
            external_project.mkdir(parents=True)
            linux_config_path.parent.mkdir(parents=True)
            windows_config_path.parent.mkdir(parents=True)

            linux_config_path.write_text(
                """model_reasoning_effort = "high"

[mcp_servers.context7]
enabled = false
bearer_token_env_var = "CTX7_TOKEN"

[features]
js_repl = false
js_repl_tools_only = true
remote_control = true
workspace_dependencies = true

[projects."/tmp/Outside"]
trust_level = "trusted"

[memories]
no_memories_if_mcp_or_web_search = false
""",
                encoding="utf-8",
            )
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
                        "allowed_fields": ["model", "model_reasoning_effort", "features"],
                        "blocked_feature_overrides": ["js_repl_tools_only", "remote_control"],
                        "protected_fields": ["canonical_roots"],
                    }
                },
                "generation_targets": {
                    "global_runtime": {
                        "linux": {"config": str(linux_config_path)},
                        "windows_mirror": {
                            "config": str(windows_config_path),
                            "generated_header": "GENERATED - DO NOT EDIT",
                        },
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
            linux_config = render.render_config(authority, windows=False, effective_cfg=effective)
            windows_config = render.render_config(authority, windows=True, effective_cfg=effective)

            self.assertEqual(effective["model_reasoning_effort"], "high")
            self.assertEqual(effective["approval_policy"], "on-request")
            self.assertEqual(effective["sandbox_mode"], "workspace-write")
            self.assertFalse(effective["features"]["js_repl"])
            self.assertTrue(effective["features"]["workspace_dependencies"])
            self.assertNotIn("js_repl_tools_only", effective["features"])
            self.assertNotIn("remote_control", effective["features"])
            self.assertNotIn(str(extra_project), effective["trusted_projects"])
            self.assertNotIn(str(external_project), effective["trusted_projects"])
            self.assertFalse(effective["context7"]["enabled"])
            self.assertEqual(effective["context7"]["bearer_token_env_var"], "CTX7_TOKEN")
            self.assertEqual(effective["memories"]["no_memories_if_mcp_or_web_search"], False)

            self.assertIn('approval_policy = "on-request"', linux_config)
            self.assertIn('sandbox_mode = "workspace-write"', linux_config)
            self.assertIn('js_repl = false', linux_config)
            self.assertIn('workspace_dependencies = true', linux_config)
            self.assertNotIn("js_repl_tools_only", linux_config)
            self.assertNotIn("remote_control", linux_config)
            self.assertNotIn(f'[projects."{extra_project}"]', linux_config)
            self.assertNotIn(f'[projects."{external_project}"]', linux_config)
            self.assertIn('bearer_token_env_var = "CTX7_TOKEN"', linux_config)
            self.assertIn("[memories]", linux_config)
            self.assertEqual(self.module.strip_generated_header(linux_config), self.module.strip_generated_header(windows_config))

    def test_rendered_hooks_include_scorecard_runtime_hook_commands(self) -> None:
        render = _load_render_module()
        authority = {
            "canonical_roots": {
                "management": "/home/andy4917/Dev-Management",
                "workflow": "/home/andy4917/Dev-Workflow",
                "product": "/home/andy4917/Dev-Product",
            },
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
                    "windows_mirror": {
                        "generated_header": "GENERATED - DO NOT EDIT",
                    }
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
                    "gate_receipt_root": "/home/andy4917/.codex/state/gate-receipts",
                    "runtime_hook": {
                        "script": "/home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py",
                        "linux_command_prefix": "python3",
                        "windows_command_prefix": "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File",
                        "windows_wrapper_path": "/mnt/c/Users/anise/.codex/bin/scorecard-hook-wrapper.ps1",
                        "windows_wrapper_generated_header": "GENERATED - DO NOT EDIT",
                        "events": {
                            "UserPromptSubmit": {"matcher": ".*"},
                        },
                    }
                }
            }
        }

        rendered_agents = render.render_agents(authority, windows=False)
        linux_hooks = json.loads(render.render_hooks(authority, windows=False))
        windows_hooks = json.loads(render.render_hooks(authority, windows=True))
        wrapper = render.render_windows_hook_wrapper(authority)

        self.assertIn("binding instruction-level guidance", rendered_agents)
        self.assertIn("Canonical global close-out command", rendered_agents)
        self.assertIn("iaw_closeout.py --workspace-root <repo> --run-id <run_id> --profile <L1|L2|L3|L4> --mode verify", rendered_agents)
        self.assertEqual(set(linux_hooks["hooks"]), {"UserPromptSubmit"})
        self.assertEqual(
            linux_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            "python3 /home/andy4917/Dev-Management/scripts/scorecard_runtime_hook.py --event UserPromptSubmit",
        )
        self.assertEqual(
            windows_hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"],
            "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:/Users/anise/.codex/bin/scorecard-hook-wrapper.ps1 -Event UserPromptSubmit -AuthorityPath /home/andy4917/Dev-Management/contracts/workspace_authority.json",
        )
        self.assertIsNotNone(wrapper)
        self.assertIn("Convert-ToLinuxPath", wrapper)
        self.assertIn("wsl.exe python3 $HookScript", wrapper)

    def test_sync_generated_text_removes_stale_hooks_file(self) -> None:
        render = _load_render_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            hook_path = Path(tmpdir) / "hooks.json"
            hook_path.write_text('{"hooks": {"UserPromptSubmit": []}}\n', encoding="utf-8")

            render.sync_generated_text(hook_path, None)

            self.assertFalse(hook_path.exists())

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
