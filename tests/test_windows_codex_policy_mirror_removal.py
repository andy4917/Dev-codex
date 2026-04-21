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

    def _authority(self, repo_root: Path, linux_home: Path, windows_home: Path) -> dict[str, object]:
        return {
            "canonical_roots": {"management": str(repo_root)},
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

    def test_dry_run_classifies_generated_and_unknown_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            (linux_home / "hooks.json").write_text('{"hooks": {"UserPromptSubmit": []}}\n', encoding="utf-8")
            (windows_home / "config.toml").write_text('# GENERATED - DO NOT EDIT\n', encoding="utf-8")
            (windows_home / "AGENTS.md").write_text('GENERATED - DO NOT EDIT\n', encoding="utf-8")
            (windows_home / "skills" / "dev-workflow" / "custom" / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
            (windows_home / "skills" / "dev-workflow" / "custom" / "SKILL.md").write_text("# custom\n", encoding="utf-8")

            report = self.module.build_report(repo_root, apply=False)

        by_path = {item["path"]: item for item in report["candidates"]}
        self.assertEqual(by_path[str(windows_home / "config.toml")]["action"], "quarantine")
        self.assertEqual(by_path[str(windows_home / "AGENTS.md")]["action"], "quarantine")
        self.assertEqual(by_path[str(windows_home / "skills" / "dev-workflow")]["action"], "retain")
        self.assertTrue(report["app_restart_required"])

    def test_apply_quarantines_generated_policy_files_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            repo_root = tmp / "repo"
            linux_home = tmp / "linux-home" / ".codex"
            windows_home = tmp / "windows-home" / ".codex"
            authority = self._authority(repo_root, linux_home, windows_home)
            _write_json(repo_root / "contracts" / "workspace_authority.json", authority)
            linux_home.mkdir(parents=True, exist_ok=True)
            windows_home.mkdir(parents=True, exist_ok=True)
            (windows_home / "config.toml").write_text('# GENERATED - DO NOT EDIT\n', encoding="utf-8")
            (windows_home / "AGENTS.md").write_text('GENERATED - DO NOT EDIT\n', encoding="utf-8")
            generated_skills = windows_home / "skills" / "dev-workflow"
            generated_skills.mkdir(parents=True, exist_ok=True)
            (generated_skills / ".devmgmt-generated").write_text("1\n", encoding="utf-8")

            first = self.module.build_report(repo_root, apply=True)
            second = self.module.build_report(repo_root, apply=True)

        self.assertFalse((windows_home / "config.toml").exists())
        self.assertFalse((windows_home / "AGENTS.md").exists())
        self.assertFalse(generated_skills.exists())
        self.assertEqual(len(first["applied_changes"]), 3)
        self.assertEqual(second["summary"]["generated_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
