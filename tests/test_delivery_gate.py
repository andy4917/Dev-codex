from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "delivery_gate.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("delivery_gate_contract", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load delivery_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeliveryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_append_gate_order_signal_records_cap_decision(self) -> None:
        scorecard = {
            "gate_order": [
                "disqualifier_check",
                "reviewer_green_check",
            ],
            "anti_cheat_signals": [],
            "anti_cheat_layer": {
                "status": "PASS",
                "signals": [],
                "decision_summary": {
                    "highest_decision": "warn",
                    "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0},
                    "auto_dq_signals": [],
                },
            },
        }
        gate_checks = {
            "1_reviewer_green_check": {"status": "PASS", "reasons": []},
            "2_disqualifier_check": {"status": "PASS", "reasons": []},
        }

        self.module._append_gate_order_signal(scorecard, gate_checks)

        self.assertEqual(scorecard["anti_cheat_signals"][0]["code"], "gate_order_drift")
        self.assertEqual(scorecard["anti_cheat_signals"][0]["decision"], "cap")
        self.assertEqual(scorecard["anti_cheat_layer"]["decision_summary"]["highest_decision"], "cap")


if __name__ == "__main__":
    unittest.main()
