from __future__ import annotations

import json
import unittest
from pathlib import Path

from devmgmt_runtime.paths import runtime_paths


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class HostileBoundaryMetaTests(unittest.TestCase):
    def test_runtime_paths_do_not_export_legacy_windows_aliases(self) -> None:
        authority = _load_json(ROOT / "contracts" / "workspace_authority.json")
        paths = runtime_paths(authority)
        self.assertNotIn("windows_config", paths)
        self.assertNotIn("windows_agents", paths)
        self.assertNotIn("windows_hooks", paths)
        self.assertNotIn("windows_wsl_launcher", paths)
        self.assertIn("observed_windows_policy_config", paths)

    def test_toolchain_policy_does_not_define_windows_wsl_parity_groups(self) -> None:
        policy = _load_json(ROOT / "contracts" / "toolchain_policy.json")
        self.assertNotIn("parity_groups", policy)

    def test_execution_and_app_surface_contracts_use_windows_relative_policy_paths(self) -> None:
        execution = _load_json(ROOT / "contracts" / "execution_surfaces.json")
        app_surface = _load_json(ROOT / "contracts" / "app_surface_policy.json")

        execution_windows = execution.get("windows_policy_surface_rules", {})
        app_windows = app_surface.get("windows_bootstrap_boundary", {})

        self.assertNotIn("policy_bearing_paths", execution_windows)
        self.assertEqual(
            execution_windows.get("policy_bearing_relative_paths"),
            ["config.toml", "AGENTS.md", "hooks.json", "skills/dev-workflow"],
        )
        self.assertNotIn("policy_bearing_forbidden_paths", app_windows)
        self.assertEqual(
            app_windows.get("policy_bearing_relative_paths"),
            ["config.toml", "AGENTS.md", "hooks.json", "skills/dev-workflow"],
        )


if __name__ == "__main__":
    unittest.main()
