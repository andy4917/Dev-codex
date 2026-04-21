from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_score_layer.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("run_score_layer", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load run_score_layer.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScoreLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_generated_mirror_self_feed_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.unified-phase.final.json", {"status": "BLOCKED"})
            self._write_json(reports / "active-config-smoke.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.unified-phase.final.json", {"remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "toolchain-surface.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "artifact-hygiene.unified-phase.final.json", {"status": "PASS", "transient_files": []})
            self._write_json(reports / "hook-readiness.unified-phase.final.json", {"hook_only_enforcement_claim": False})
            self._write_json(reports / "startup-workflow.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "git-surface.unified-phase.final.json", {"status": "PASS"})
            report = self.module.evaluate_score_layer(tmp)
        self.assertEqual(report["status"], "BLOCKED")

    def test_clean_state_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "active-config-smoke.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.unified-phase.final.json", {"remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "toolchain-surface.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "artifact-hygiene.unified-phase.final.json", {"status": "PASS", "transient_files": []})
            self._write_json(reports / "hook-readiness.unified-phase.final.json", {"hook_only_enforcement_claim": False})
            self._write_json(reports / "startup-workflow.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "git-surface.unified-phase.final.json", {"status": "PASS"})
            report = self.module.evaluate_score_layer(tmp)
        self.assertEqual(report["status"], "PASS")

    def test_audit_fail_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "active-config-smoke.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.unified-phase.final.json", {"overall_status": "PASS", "canonical_execution_status": "PASS", "remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "toolchain-surface.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "artifact-hygiene.unified-phase.final.json", {"status": "PASS", "transient_files": []})
            self._write_json(reports / "hook-readiness.unified-phase.final.json", {"status": "PASS", "hook_only_enforcement_claim": False})
            self._write_json(reports / "startup-workflow.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.unified-phase.final.json", {"status": "FAIL"})
            self._write_json(reports / "git-surface.unified-phase.final.json", {"status": "PASS"})
            report = self.module.evaluate_score_layer(tmp)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("workspace audit final gate blocked", report["disqualifiers"])

    def test_missing_required_reports_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report = self.module.evaluate_score_layer(tmp)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("missing required evidence report: config_provenance", report["disqualifiers"])

    def test_audit_post_export_fallback_is_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "active-config-smoke.unified-phase.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.unified-phase.final.json", {"overall_status": "PASS", "canonical_execution_status": "PASS", "remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "startup-workflow.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "toolchain-surface.unified-phase.final.json", {"status": "PASS"})
            self._write_json(reports / "hook-readiness.unified-phase.final.json", {"status": "PASS", "hook_only_enforcement_claim": False})
            self._write_json(reports / "artifact-hygiene.unified-phase.final.json", {"status": "PASS", "transient_files": []})
            self._write_json(reports / "audit.post-export.json", {"status": "PASS"})
            self._write_json(reports / "git-surface.unified-phase.final.json", {"status": "PASS"})
            report = self.module.evaluate_score_layer(tmp)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["report_sources"]["audit"].endswith("audit.post-export.json"))

    def test_app_usability_warns_when_startup_is_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "active-config-smoke.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.final.json", {"overall_status": "WARN", "canonical_execution_status": "PASS", "remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "WARN"})
            self._write_json(reports / "startup-workflow.final.json", {"status": "WARN"})
            self._write_json(reports / "toolchain-surface.final.json", {"status": "PASS"})
            self._write_json(reports / "hook-readiness.final.json", {"status": "PASS", "hook_only_enforcement_claim": False})
            self._write_json(reports / "artifact-hygiene.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.final.json", {"status": "WARN"})
            self._write_json(reports / "git-surface.final.json", {"status": "WARN"})
            report = self.module.evaluate_score_layer(tmp, purpose="app-usability")
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["purpose"], "app-usability")

    def test_branch_lock_conflict_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "active-config-smoke.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.final.json", {"overall_status": "PASS", "canonical_execution_status": "PASS", "remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "startup-workflow.final.json", {"status": "PASS"})
            self._write_json(reports / "toolchain-surface.final.json", {"status": "PASS"})
            self._write_json(reports / "hook-readiness.final.json", {"status": "PASS", "hook_only_enforcement_claim": False})
            self._write_json(reports / "artifact-hygiene.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.final.json", {"status": "PASS"})
            self._write_json(reports / "git-surface.final.json", {"status": "BLOCKED"})
            report = self.module.evaluate_score_layer(tmp, purpose="app-usability")
        self.assertEqual(report["status"], "BLOCKED")

    def test_code_modification_prefers_root_cause_reports_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            reports = tmp / "reports"
            self._write_json(reports / "config-provenance.root-cause-removal.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "active-config-smoke.root-cause-removal.final.json", {"status": "PASS", "gate_status": "PASS"})
            self._write_json(reports / "global-runtime.root-cause-removal.final.json", {"overall_status": "PASS", "canonical_execution_status": "PASS", "remote_codex_resolution_status": {"status": "PASS"}, "client_surface_status": "PASS"})
            self._write_json(reports / "toolchain-surface.root-cause-removal.final.json", {"status": "PASS"})
            self._write_json(reports / "hook-readiness.root-cause-removal.final.json", {"status": "PASS", "hook_only_enforcement_claim": False})
            self._write_json(reports / "artifact-hygiene.root-cause-removal.final.json", {"status": "PASS"})
            self._write_json(reports / "startup-workflow.root-cause-removal.final.json", {"status": "BLOCKED"})
            self._write_json(reports / "audit.root-cause-removal.final.json", {"status": "FAIL"})
            self._write_json(reports / "git-surface.final.json", {"status": "PASS"})
            self._write_json(reports / "startup-workflow.final.json", {"status": "PASS"})
            self._write_json(reports / "audit.final.json", {"status": "PASS"})
            report = self.module.evaluate_score_layer(tmp, purpose="code-modification")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(report["report_sources"]["startup_workflow"].endswith("startup-workflow.root-cause-removal.final.json"))
        self.assertTrue(report["report_sources"]["audit"].endswith("audit.root-cause-removal.final.json"))


if __name__ == "__main__":
    unittest.main()
