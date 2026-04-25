from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from devmgmt_runtime.authority import authority_path_for
from devmgmt_runtime.paths import is_forbidden_runtime_value
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


if __name__ == "__main__":
    unittest.main()
