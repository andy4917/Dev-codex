from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_app_ssh_readiness.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_app_ssh_readiness", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_app_ssh_readiness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsAppSshReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self, tmp: Path) -> dict[str, object]:
        return {"canonical_execution_surface": {"host_alias": "devmgmt-wsl"}}

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_windows_side_alias_missing_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority(tmp))
            config = tmp / "config"
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config):
                report = self.module.evaluate_windows_app_ssh_readiness(tmp / "repo")
        self.assertIn(report["status"], {"BLOCKED", "WARN"})

    def test_apply_adds_alias_and_preserves_existing_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            authority_path = tmp / "repo" / "contracts" / "workspace_authority.json"
            authority_path.parent.mkdir(parents=True)
            self._write_json(authority_path, self._authority(tmp))
            ssh_dir = tmp / "ssh"
            ssh_dir.mkdir()
            config = ssh_dir / "config"
            config.write_text("Host wsl-ubuntu\n  HostName localhost\n", encoding="utf-8")
            (ssh_dir / "codex_wsl_ed25519").write_text("dummy", encoding="utf-8")
            fake = SimpleNamespace(returncode=0, stdout="andy4917\n", stderr="")
            with patch.object(self.module, "AUTHORITY_PATH", authority_path), patch.object(self.module, "WINDOWS_SSH_CONFIG", config), patch.object(self.module.subprocess, "run", return_value=fake):
                report = self.module.evaluate_windows_app_ssh_readiness(tmp / "repo", apply_user_level=True)
                updated = config.read_text(encoding="utf-8")
        self.assertEqual(report["status"], "PASS")
        self.assertIn("Host wsl-ubuntu", updated)
        self.assertIn("Host devmgmt-wsl", updated)


if __name__ == "__main__":
    unittest.main()
