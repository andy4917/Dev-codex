from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_artifact_hygiene.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_artifact_hygiene", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_artifact_hygiene.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ArtifactHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_stale_draft_and_duplicate_remediation_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            (reports / "note.draft.md").write_text("draft\n", encoding="utf-8")
            (reports / "manual-system-remediation-1.md").write_text("one\n", encoding="utf-8")
            (reports / "manual-system-remediation-2.md").write_text("two\n", encoding="utf-8")
            report = self.module.evaluate_artifact_hygiene(tmp)
        self.assertEqual(report["status"], "WARN")

    def test_clean_state_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "reports").mkdir()
            report = self.module.evaluate_artifact_hygiene(tmp)
        self.assertEqual(report["status"], "PASS")

    def test_apply_cleanup_removes_stale_generated_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            reports.mkdir()
            draft = reports / "note.draft.md"
            old_remediation = reports / "manual-system-remediation-1.md"
            latest_remediation = reports / "manual-system-remediation-2.md"
            draft.write_text("draft\n", encoding="utf-8")
            old_remediation.write_text("one\n", encoding="utf-8")
            latest_remediation.write_text("two\n", encoding="utf-8")
            report = self.module.apply_cleanup(tmp)
            self.assertTrue(report["cleanup_applied"])
            removed_sources = {item["source"] for item in report["removed_files"]}
            self.assertIn(str(draft), removed_sources)
            self.assertIn(str(old_remediation), removed_sources)
            self.assertNotIn(str(latest_remediation), removed_sources)
            self.assertFalse(draft.exists())
            self.assertFalse(old_remediation.exists())
            self.assertTrue(latest_remediation.exists())

    def test_executable_quarantine_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            quarantine = tmp / "quarantine" / "sample"
            quarantine.mkdir(parents=True)
            offender = quarantine / "run.sh"
            offender.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            offender.chmod(0o755)
            (tmp / "reports").mkdir()
            report = self.module.evaluate_artifact_hygiene(tmp)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn(str(offender), report["quarantine_executable_files"])
        self.assertIn(str(offender), report["quarantine_cli_files"])

    def test_active_quarantine_reference_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "reports").mkdir()
            docs = tmp / "docs"
            docs.mkdir()
            (docs / "note.md").write_text("Use subprocess on quarantine/tool.py during setup.\n", encoding="utf-8")
            report = self.module.evaluate_artifact_hygiene(tmp)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["active_quarantine_reference_hits"])


if __name__ == "__main__":
    unittest.main()
