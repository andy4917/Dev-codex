from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_toolchain_surface.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_toolchain_surface", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_toolchain_surface.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckToolchainSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_workspace_dependency_disabled_but_unused_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (tmp / ".codex").mkdir()
            (tmp / ".codex" / "config.toml").write_text('[features]\nchronicle = true\n[mcp_servers.context7]\nenabled = true\n[plugins."github@openai-curated"]\nenabled = true\n', encoding="utf-8")
            (reports / "workspace-dependency-surface.json").write_text(json.dumps({"tool_status": "DISABLED_IN_APP_SETTINGS", "required_by_workflow": False}), encoding="utf-8")
            (reports / "toolchain-usage.session.json").write_text(json.dumps({"skills": ["env-audit"], "subagents": ["tests_gap_scan"]}), encoding="utf-8")
            (reports / "codex-app-installed-release-impact.unified-phase.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(tmp)}), patch.object(self.module, "evaluate_global_runtime", return_value={"remote_codex_resolution_status": {"status": "PASS"}, "overall_status": "PASS"}):
                report = self.module.evaluate_toolchain_surface(tmp)
        self.assertEqual(report["status"], "PASS")

    def test_missing_session_usage_provenance_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (tmp / ".codex").mkdir()
            (tmp / ".codex" / "config.toml").write_text('[features]\nchronicle = true\n', encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(tmp)}), patch.object(self.module, "evaluate_global_runtime", return_value={"remote_codex_resolution_status": {"status": "PASS"}, "overall_status": "PASS"}):
                report = self.module.evaluate_toolchain_surface(tmp)
        self.assertEqual(report["status"], "WARN")

    def test_remote_windows_launcher_target_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (tmp / ".codex").mkdir()
            (tmp / ".codex" / "config.toml").write_text('[features]\nchronicle = true\n', encoding="utf-8")
            (reports / "toolchain-usage.session.json").write_text(json.dumps({"skills": [], "subagents": []}), encoding="utf-8")
            (reports / "codex-app-installed-release-impact.unified-phase.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(tmp)}), patch.object(self.module, "evaluate_global_runtime", return_value={"remote_codex_resolution_status": {"status": "BLOCKED"}, "overall_status": "WARN"}):
                report = self.module.evaluate_toolchain_surface(tmp)
        self.assertEqual(report["status"], "BLOCKED")

    def test_projectless_code_modification_without_repo_root_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (tmp / ".codex").mkdir()
            (tmp / ".codex" / "config.toml").write_text('[features]\nchronicle = true\n', encoding="utf-8")
            (reports / "toolchain-usage.session.json").write_text(
                json.dumps(
                    {
                        "skills": ["env-audit"],
                        "subagents": ["contracts_docs_review"],
                        "projectless_chat": {
                            "active": True,
                            "code_modification_requested": True,
                            "repo_root_resolved": False,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (reports / "codex-app-installed-release-impact.unified-phase.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(tmp)}), patch.object(self.module, "evaluate_global_runtime", return_value={"remote_codex_resolution_status": {"status": "PASS"}, "overall_status": "PASS"}):
                report = self.module.evaluate_toolchain_surface(tmp)
        self.assertEqual(report["status"], "BLOCKED")

    def test_windows_hooks_disabled_warns_but_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (tmp / ".codex").mkdir()
            (tmp / ".codex" / "config.toml").write_text('[features]\nchronicle = true\n', encoding="utf-8")
            (reports / "toolchain-usage.session.json").write_text(json.dumps({"skills": ["env-audit"], "subagents": ["contracts_docs_review"]}), encoding="utf-8")
            (reports / "codex-app-installed-release-impact.unified-phase.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            (reports / "hook-readiness.final.json").write_text(json.dumps({"status": "WARN", "hook_only_enforcement_claim": False, "windows_generation_enabled": False}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": str(tmp)}), patch.object(self.module, "evaluate_global_runtime", return_value={"remote_codex_resolution_status": {"status": "PASS"}, "overall_status": "PASS"}):
                report = self.module.evaluate_toolchain_surface(tmp)
        self.assertEqual(report["status"], "WARN")


if __name__ == "__main__":
    unittest.main()
