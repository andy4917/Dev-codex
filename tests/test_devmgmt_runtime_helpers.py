from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from devmgmt_runtime.authority import authority_path_for
from devmgmt_runtime.paths import is_forbidden_runtime_value
from devmgmt_runtime.reports import save_json, write_json_and_markdown, write_markdown
from devmgmt_runtime.status import collapse_status, status_exit_code


class DevMgmtRuntimeHelpersTests(unittest.TestCase):
    def test_collapse_status_prefers_blocked(self) -> None:
        self.assertEqual(collapse_status(["PASS", "WARN", "BLOCKED"]), "BLOCKED")

    def test_status_exit_code_maps_warn(self) -> None:
        self.assertEqual(status_exit_code("WARN"), 1)

    def test_authority_path_prefers_repo_local_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority = tmp / "contracts" / "workspace_authority.json"
            authority.parent.mkdir(parents=True)
            authority.write_text("{}\\n", encoding="utf-8")
            self.assertEqual(authority_path_for(tmp), authority.resolve())

    def test_forbidden_runtime_detection_matches_legacy_marker(self) -> None:
        authority = {"forbidden_primary_runtime_paths": ["mounted-linux-launcher", "legacy-remote-route"]}
        self.assertTrue(is_forbidden_runtime_value("mounted-linux-launcher/codex", authority))
        self.assertFalse(is_forbidden_runtime_value("C:/Users/anise/code/Dev-Management", authority))

    def test_report_writers_use_lf_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            json_path = tmp / "report.json"
            md_path = tmp / "report.md"

            save_json(json_path, {"status": "PASS", "items": ["a", "b"]})
            write_markdown(md_path, "line one\nline two\n")

            self.assertNotIn(b"\r\n", json_path.read_bytes())
            self.assertNotIn(b"\r\n", md_path.read_bytes())

    def test_write_json_and_markdown_targets_sibling_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "nested" / "report.json"
            write_json_and_markdown(report_path, {"status": "PASS"}, "status: PASS\n")

            self.assertTrue(report_path.exists())
            self.assertEqual("status: PASS\n", report_path.with_suffix(".md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
