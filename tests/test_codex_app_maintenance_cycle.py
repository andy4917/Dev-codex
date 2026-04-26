from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "run_codex_app_maintenance_cycle.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_codex_app_maintenance_cycle", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load run_codex_app_maintenance_cycle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Completed:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class CodexAppMaintenanceCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_resource_health_summary_preserves_cpu_warning_evidence(self) -> None:
        payload = {
            "status": "WARN",
            "process_counts": {"codex": 6},
            "working_sets": {"codex_mb": 1224.0},
            "cpu_samples": {"codex_cpu_pct": 64.2},
            "warnings": ["Codex App sampled CPU is high: 64.2%"],
            "blockers": [],
            "cleanup_candidate_summary": {"count": 0},
        }

        with patch.object(self.module.subprocess, "run", return_value=Completed(json.dumps(payload), returncode=1)):
            step = self.module.run_step("windows_app_resource_health", ["python", "resource-check"])

        self.assertEqual(step["status"], "WARN")
        self.assertEqual(step["summary"]["cpu_samples"]["codex_cpu_pct"], 64.2)
        self.assertIn("Codex App sampled CPU is high: 64.2%", step["summary"]["warnings"])

    def test_cycle_passes_cpu_sample_seconds_to_resource_health(self) -> None:
        calls: list[list[str]] = []

        def fake_run_step(label: str, args: list[str]) -> dict[str, object]:
            calls.append(args)
            return {"label": label, "status": "PASS"}

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "cycle.json"
            with patch.object(self.module, "run_step", side_effect=fake_run_step):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_codex_app_maintenance_cycle.py",
                        "--output-file",
                        str(output),
                        "--resource-cpu-sample-seconds",
                        "5",
                    ],
                ):
                    self.assertEqual(self.module.main(), 0)

        health_command = calls[1]
        maintenance_command = calls[0]
        self.assertIn("--max-live-threads", maintenance_command)
        self.assertEqual(maintenance_command[maintenance_command.index("--max-live-threads") + 1], "12")
        self.assertIn("--keep-serena-roots", health_command)
        self.assertEqual(health_command[health_command.index("--keep-serena-roots") + 1], "1")
        self.assertIn("--duplicate-serena-grace-minutes", health_command)
        self.assertEqual(health_command[health_command.index("--duplicate-serena-grace-minutes") + 1], "10")
        self.assertNotIn("--throttle-codex-priority", health_command)
        self.assertNotIn("--prefer-low-power-gpu", health_command)
        self.assertIn("--cpu-sample-seconds", health_command)
        self.assertEqual(health_command[health_command.index("--cpu-sample-seconds") + 1], "5")

    def test_cycle_keeps_priority_and_gpu_changes_opt_in(self) -> None:
        calls: list[list[str]] = []

        def fake_run_step(label: str, args: list[str]) -> dict[str, object]:
            calls.append(args)
            return {"label": label, "status": "PASS"}

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "cycle.json"
            with patch.object(self.module, "run_step", side_effect=fake_run_step):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_codex_app_maintenance_cycle.py",
                        "--output-file",
                        str(output),
                        "--throttle-codex-priority",
                        "--prefer-low-power-gpu",
                    ],
                ):
                    self.assertEqual(self.module.main(), 0)

        health_command = calls[1]
        self.assertIn("--throttle-codex-priority", health_command)
        self.assertIn("--prefer-low-power-gpu", health_command)


if __name__ == "__main__":
    unittest.main()
