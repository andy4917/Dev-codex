from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_workspace_structure.py"
POLICY_PATH = ROOT / "contracts" / "workspace_structure_policy.json"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_workspace_structure", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_workspace_structure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkspaceStructurePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_policy_declares_expected_taxonomy_and_windows_codex_role(self) -> None:
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["taxonomy"],
            [
                "CLI_SHELL",
                "CORE_RUNTIME",
                "CONTRACT_AUTHORITY",
                "DOCS",
                "SDK",
                "SCRIPTS",
                "TOOLS",
                "PATCHES",
                "THIRD_PARTY",
                "CONFIG_ENV",
                "GENERATED_EVIDENCE",
                "TESTS",
                "SKILLS",
                "PRODUCT_SOURCE",
                "USER_CONTROL_PLANE",
                "APP_STATE",
                "EXTERNAL_DEPENDENCY",
                "DECOMMISSIONED",
                "STALE_OR_MISPLACED",
            ],
        )
        self.assertEqual(payload["windows_codex_surface"]["role"], "USER_CONTROL_PLANE")
        self.assertTrue(payload["windows_codex_surface"]["app_state"])
        self.assertFalse(payload["windows_codex_surface"]["repo_authority"])
        self.assertTrue(payload["windows_codex_surface"]["authoritative"])
        self.assertFalse(payload["windows_codex_surface"]["workspace_structure_authority"])

    def test_workspace_structure_passes_with_required_roots_and_optional_dirs_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home" / "andy4917"
            management = home / "Dev-Management"
            workflow = home / "Dev-Workflow"
            product = home / "Dev-Product"
            for path in (
                management / "contracts",
                management / "devmgmt_runtime",
                management / "docs",
                management / "scripts",
                management / "tests",
                management / "reports",
                workflow,
                product,
                home / ".codex",
                home / ".local" / "share",
            ):
                path.mkdir(parents=True, exist_ok=True)
            authority = {
                "canonical_roots": {
                    "management": str(management),
                    "workflow": str(workflow),
                    "product": str(product),
                }
            }
            policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            policy["root_roles"][".codex"]["path"] = ".codex"
            policy["root_roles"][".ssh"]["path"] = ".ssh"
            policy["root_roles"]["Documents/PowerShell"]["required"] = False
            report = self.module.evaluate_workspace_structure(
                repo_root=management,
                policy_override=policy,
                authority_override=authority,
                home_override=home,
            )
        self.assertEqual(report["status"], "PASS")
        tree_items = report["checks"]["workspace_tree"]["items"]
        by_label = {item["label"]: item for item in tree_items}
        self.assertEqual(by_label["Dev-Management"]["listing_mode"], "detailed")
        self.assertEqual(by_label[".codex"]["listing_mode"], "control_plane")
        self.assertEqual(by_label[".ssh"]["listing_mode"], "decommissioned")
        self.assertFalse(by_label[".ssh"]["exists"])
        self.assertIn("tree", by_label["Dev-Management"])

    def test_decommissioned_ssh_blocks_without_leaking_file_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home" / "andy4917"
            management = home / "Dev-Management"
            workflow = home / "Dev-Workflow"
            product = home / "Dev-Product"
            for path in (
                management / "contracts",
                management / "devmgmt_runtime",
                management / "docs",
                management / "scripts",
                management / "tests",
                management / "reports",
                workflow,
                product,
                home / ".codex" / "sessions",
                home / ".ssh",
            ):
                path.mkdir(parents=True, exist_ok=True)
            (home / ".ssh" / "id_ed25519").write_text("secret", encoding="utf-8")
            authority = {
                "canonical_roots": {
                    "management": str(management),
                    "workflow": str(workflow),
                    "product": str(product),
                }
            }
            policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
            policy["root_roles"][".codex"]["path"] = ".codex"
            policy["root_roles"][".ssh"]["path"] = ".ssh"
            policy["root_roles"]["Documents/PowerShell"]["required"] = False
            report = self.module.evaluate_workspace_structure(
                repo_root=management,
                policy_override=policy,
                authority_override=authority,
                home_override=home,
            )
        self.assertEqual(report["status"], "BLOCKED")
        ssh_item = {item["label"]: item for item in report["checks"]["workspace_tree"]["items"]}[".ssh"]
        ssh_tree = ssh_item["tree"]
        self.assertEqual(ssh_item["listing_mode"], "decommissioned")
        self.assertEqual(ssh_tree["child_summary"]["files"], 1)
        self.assertNotIn("id_ed25519", json.dumps(ssh_tree))

    def test_optional_documentation_dir_without_manifest_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home" / "andy4917"
            management = home / "Dev-Management"
            workflow = home / "Dev-Workflow"
            product = home / "Dev-Product"
            for path in (
                management / "contracts",
                management / "devmgmt_runtime",
                management / "docs",
                management / "scripts",
                management / "tests",
                management / "reports",
                management / "third_party",
                workflow,
                product,
                home / ".codex",
                home / ".local" / "share",
            ):
                path.mkdir(parents=True, exist_ok=True)
            authority = {
                "canonical_roots": {
                    "management": str(management),
                    "workflow": str(workflow),
                    "product": str(product),
                }
            }
            report = self.module.evaluate_workspace_structure(
                repo_root=management,
                policy_override=json.loads(POLICY_PATH.read_text(encoding="utf-8")),
                authority_override=authority,
                home_override=home,
            )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["checks"]["dev_management_layout"]["status"], "WARN")

    def test_missing_required_management_dir_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home" / "andy4917"
            management = home / "Dev-Management"
            workflow = home / "Dev-Workflow"
            product = home / "Dev-Product"
            for path in (
                management / "contracts",
                management / "devmgmt_runtime",
                management / "docs",
                management / "scripts",
                management / "reports",
                workflow,
                product,
                home / ".codex",
                home / ".local" / "share",
            ):
                path.mkdir(parents=True, exist_ok=True)
            authority = {
                "canonical_roots": {
                    "management": str(management),
                    "workflow": str(workflow),
                    "product": str(product),
                }
            }
            report = self.module.evaluate_workspace_structure(
                repo_root=management,
                policy_override=json.loads(POLICY_PATH.read_text(encoding="utf-8")),
                authority_override=authority,
                home_override=home,
            )
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"]["dev_management_layout"]["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
