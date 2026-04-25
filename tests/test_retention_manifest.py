from __future__ import annotations

import unittest

from devmgmt_runtime.retention import build_retention_manifest, classify_relative_path


class RetentionManifestTests(unittest.TestCase):
    def test_stale_closeout_script_is_deleted(self) -> None:
        classified = classify_relative_path("scripts/generate_closeout_v2_reports.py", is_dir=False)
        self.assertEqual(classified["classification"], "DELETE_NOW")

    def test_current_final_report_is_retained(self) -> None:
        classified = classify_relative_path("reports/global-agent-workflow.final.json", is_dir=False)
        self.assertEqual(classified["classification"], "RETAIN_CURRENT_REPORT")

    def test_windows_setup_doc_is_retained(self) -> None:
        classified = classify_relative_path("docs/CODEX_APP_USER_SETUP.md", is_dir=False)
        self.assertEqual(classified["classification"], "RETAIN_DOC")

    def test_removed_legacy_doc_is_deleted(self) -> None:
        classified = classify_relative_path("docs/LOCAL_ENVIRONMENTS.md", is_dir=False)
        self.assertEqual(classified["classification"], "DELETE_NOW")

    def test_unknown_doc_is_not_retained_by_default(self) -> None:
        classified = classify_relative_path("docs/FUTURE_NOTE.md", is_dir=False)
        self.assertEqual(classified["classification"], "DELETE_NOW")

    def test_manifest_has_no_unknowns(self) -> None:
        report = build_retention_manifest(".")
        self.assertEqual(report["unknown_count"], 0)


if __name__ == "__main__":
    unittest.main()
