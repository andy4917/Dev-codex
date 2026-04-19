from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "export_user_score_summary.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("export_user_score_summary", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load export_user_score_summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExportUserScoreSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_missing_receipt_downgrades_gate_and_credit_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scorecard = root / "user-scorecard.json"
            scorecard.write_text(
                json.dumps(
                    {
                        "disqualifier_result": {"status": "PASS"},
                        "scores": {
                            "trust_score": {"applicable": True, "score": 30},
                            "completion_score": {"applicable": True, "score": 24},
                            "compliance_score": {"applicable": True, "score": 20},
                            "reliability_score": {"applicable": False, "score": 0},
                            "search_evidence_score": {"applicable": True, "score": 10},
                        },
                        "capped_total_score": 84,
                        "reviewer_penalties": {},
                        "requested_credit": [{"axis": "completion_score", "requested_points": 24, "source": "system_derived", "reason": "pass"}],
                        "credited_credit": [{"axis": "completion_score", "requested_points": 24, "credited_points": 24, "source": "system_derived", "capped": False, "blocked": False, "block_reason": ""}],
                        "anti_cheat_layer": {"status": "PASS", "signal_points": 0, "penalty_points": 0, "guarded_total_score": 84, "decision_summary": {"highest_decision": "warn", "counts": {"warn": 0, "penalty": 0, "cap": 0, "dq": 0}}},
                        "anti_cheat_signals": [],
                        "platform_cap": {"cap_applied": False, "active_caps": []},
                        "taste_gate": {"status": "PASS"},
                        "task_tree": {"status": "PASS"},
                        "evidence_manifest": {"status": "PASS"},
                        "repeated_verify": {"status": "PASS"},
                        "cross_verification": {"status": "PASS"},
                        "convention_lock": {"status": "PASS"},
                        "summary_coverage": {"status": "PASS", "negative_findings_present": True, "uncovered_claim_count": 0, "zombie_section_count": 0},
                        "gate_status": "PASS",
                        "final_decision": "PASS",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            argv = sys.argv[:]
            try:
                sys.argv = ["export_user_score_summary.py", "--scorecard-file", str(scorecard)]
                with redirect_stdout(stdout):
                    self.module.main()
            finally:
                sys.argv = argv

        output = stdout.getvalue()
        self.assertIn("0. authoritative receipt: MISSING", output)
        self.assertIn("- credited: UNVERIFIED pending gate_receipt", output)
        self.assertIn("19. gate 상태: UNVERIFIED", output)
        self.assertIn("22. 최종 판정: UNVERIFIED", output)


if __name__ == "__main__":
    unittest.main()
