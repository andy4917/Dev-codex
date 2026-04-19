from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from merge_reviewer_penalties import merge_review_payload


def _base_payload() -> dict:
    return {
        "status": "READY",
        "reviewers": {},
        "user_review": {
            "status": "PENDING",
            "awards": [],
            "penalties": [],
            "notes": "",
        },
        "disqualifiers": [],
    }


class MergeReviewerPenaltiesTests(unittest.TestCase):
    def test_merge_ignores_unauthorized_user_review_updates(self) -> None:
        merged, warnings = merge_review_payload(
            _base_payload(),
            {
                "user_review": {
                    "status": "APPROVED",
                    "awards": [{"axis": "completion_score", "points": 5, "reason": "unauthorized"}],
                    "penalties": [],
                    "notes": "ignore me",
                }
            },
        )
        self.assertEqual(merged["user_review"]["status"], "PENDING")
        self.assertEqual(merged["user_review"]["awards"], [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("ignored user_review update", warnings[0])

    def test_merge_applies_authorized_user_review_updates(self) -> None:
        merged, warnings = merge_review_payload(
            _base_payload(),
            {
                "user_review_update_request": "user requested mid-task award",
                "user_review": {
                    "status": "APPROVED",
                    "awards": [{"axis": "completion_score", "points": 5, "reason": "authorized"}],
                    "penalties": [],
                    "notes": "apply me",
                },
            },
        )
        self.assertEqual(warnings, [])
        self.assertEqual(merged["user_review"]["status"], "APPROVED")
        self.assertEqual(len(merged["user_review"]["awards"]), 1)
        self.assertEqual(merged["user_review"]["awards"][0]["reason"], "authorized")


if __name__ == "__main__":
    unittest.main()
