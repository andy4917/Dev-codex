from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "remove_windows_codex_policy_mirror_removal.py"
if not MODULE_PATH.exists():
    MODULE_PATH = ROOT / "scripts" / "remove_windows_codex_policy_mirrors.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("remove_windows_codex_policy_mirrors", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load remove_windows_codex_policy_mirrors.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class WindowsCodexPolicyMirrorRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self, repo_root: Path, linux_home: Path, windows_home: Path, workflow_root: Path) -> dict[str, object]:
        return {
            "canonical_roots": {
                "management": str(repo_root),
                "workflow": str(workflow_root),
            },
            "windows_app_state": {"codex_home": str(windows_home)},
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "config": str(linux_home / "config.toml"),
                        "agents": str(linux_home / "AGENTS.md"),
                        "hooks_config": str(linux_home / "hooks.json"),
                    }
                }
            },
        }

    def test_unmarked_structural_skill_mirror_is_remove_now(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            workflow_root = tmp / "Dev-Workflow"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home, workflow_root)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            skill_text = "# custom\n"
            canonical_skill = workflow_root / "skills" / "custom" / "SKILL.md"
            mirrored_skill = windows_home / "skills" / "dev-workflow" / "custom" / "SKILL.md"
            canonical_skill.parent.mkdir(parents=True, exist_ok=True)
            mirrored_skill.parent.mkdir(parents=True, exist_ok=True)
            canonical_skill.write_text(skill_text, encoding="utf-8")
            mirrored_skill.write_text(skill_text, encoding="utf-8")

            report = self.module.build_report(repo_root, apply=False)

        by_path = {item["path"]: item for item in report["candidates"]}
        skill = by_path[str(windows_home / "skills" / "dev-workflow")]
        self.assertEqual(skill["operation"], "remove")
        self.assertEqual(skill["disposition"], "REMOVE_NOW")
        self.assertTrue(report["app_restart_required"])

    def test_non_structural_skill_state_stays_manual_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            workflow_root = tmp / "Dev-Workflow"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home, workflow_root)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            canonical_skill = workflow_root / "skills" / "custom" / "SKILL.md"
            mirrored_skill = windows_home / "skills" / "dev-workflow" / "custom" / "SKILL.md"
            helper = windows_home / "skills" / "dev-workflow" / "helper.py"
            canonical_skill.parent.mkdir(parents=True, exist_ok=True)
            mirrored_skill.parent.mkdir(parents=True, exist_ok=True)
            canonical_skill.write_text("# custom\n", encoding="utf-8")
            mirrored_skill.write_text("# custom\n", encoding="utf-8")
            helper.write_text("print('hello')\n", encoding="utf-8")

            report = self.module.build_report(repo_root, apply=False)

        by_path = {item["path"]: item for item in report["candidates"]}
        skill = by_path[str(windows_home / "skills" / "dev-workflow")]
        self.assertEqual(skill["operation"], "retain")
        self.assertEqual(skill["disposition"], "MANUAL_REMEDIATION")

    def test_structural_windows_config_without_generated_header_is_remove_now(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            workflow_root = tmp / "Dev-Workflow"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home, workflow_root)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            (windows_home / "config.toml").write_text(
                "\n".join(
                    [
                        'model = "gpt-5.4"',
                        'model_reasoning_effort = "high"',
                        "",
                        "[features]",
                        "chronicle = true",
                        "memories = true",
                        "remote_connections = true",
                        "remote_control = true",
                        "",
                        f'[projects."{repo_root}"]',
                        'trust_level = "trusted"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = self.module.build_report(repo_root, apply=False)

        by_path = {item["path"]: item for item in report["candidates"]}
        config = by_path[str(windows_home / "config.toml")]
        self.assertEqual(config["operation"], "remove")
        self.assertEqual(config["disposition"], "REMOVE_NOW")

    def test_apply_removes_generated_files_and_skill_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            workflow_root = tmp / "Dev-Workflow"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home, workflow_root)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            (linux_home / "hooks.json").write_text('{"hooks": {"UserPromptSubmit": []}}\n', encoding="utf-8")
            (windows_home / "config.toml").write_text("# GENERATED - DO NOT EDIT\n", encoding="utf-8")
            (windows_home / "AGENTS.md").write_text("GENERATED - DO NOT EDIT\n", encoding="utf-8")

            canonical_skill = workflow_root / "skills" / "custom" / "SKILL.md"
            mirrored_skill = windows_home / "skills" / "dev-workflow" / "custom" / "SKILL.md"
            canonical_skill.parent.mkdir(parents=True, exist_ok=True)
            mirrored_skill.parent.mkdir(parents=True, exist_ok=True)
            canonical_skill.write_text("# custom\n", encoding="utf-8")
            mirrored_skill.write_text("# custom\n", encoding="utf-8")

            first = self.module.build_report(repo_root, apply=True)
            second = self.module.build_report(repo_root, apply=True)
        self.assertFalse((windows_home / "config.toml").exists())
        self.assertFalse((windows_home / "AGENTS.md").exists())
        self.assertFalse((windows_home / "skills" / "dev-workflow").exists())
        self.assertEqual(len(first["applied_changes"]), 3)
        self.assertEqual({item["action"] for item in first["applied_changes"]}, {"removed"})
        self.assertEqual(second["summary"]["generated_candidates"], 0)
        self.assertEqual(second["summary"]["remove_now_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
