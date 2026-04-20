from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "activate_canonical_runtime.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("activate_canonical_runtime", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load activate_canonical_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActivateCanonicalRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self, repo_root: Path) -> dict[str, object]:
        return {
            "canonical_execution_surface": {
                "id": "ssh-devmgmt-wsl",
                "host_alias": "devmgmt-wsl",
                "repo_root": str(repo_root),
            }
        }

    def _fake_run(self, home: Path):
        def runner(argv: list[str]) -> dict[str, object]:
            if argv[:2] == ["ssh-keygen", "-lf"]:
                return {"ok": True, "exit_code": 0, "stdout": "256 SHA256:test devmgmt_wsl_ed25519.pub (ED25519)\n", "stderr": "", "argv": argv}
            if argv and argv[0] == "ssh-keygen":
                private = Path(argv[-1])
                private.parent.mkdir(parents=True, exist_ok=True)
                private.write_text("PRIVATE-KEY-CONTENT\n", encoding="utf-8")
                private.with_suffix(".pub").write_text("ssh-ed25519 AAAATEST devmgmt-wsl@local\n", encoding="utf-8")
                return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "argv": argv}
            if argv and argv[0] == "ssh":
                command = argv[-1]
                if command == "hostname":
                    return {"ok": True, "exit_code": 0, "stdout": "localhost\n", "stderr": "", "argv": argv}
                if "git rev-parse --show-toplevel" in command:
                    return {"ok": True, "exit_code": 0, "stdout": f"{home / 'repo'}\n", "stderr": "", "argv": argv}
                if "command -v codex" in command:
                    return {"ok": True, "exit_code": 0, "stdout": "/usr/local/bin/codex\n", "stderr": "", "argv": argv}
                if "type -a codex" in command:
                    return {"ok": True, "exit_code": 0, "stdout": "codex is /usr/local/bin/codex\n", "stderr": "", "argv": argv}
                if "printf '%s\\n' \"$PATH\"" in command:
                    return {"ok": True, "exit_code": 0, "stdout": "/usr/local/bin\n/usr/bin\n", "stderr": "", "argv": argv}
            return {"ok": False, "exit_code": 1, "stdout": "", "stderr": "unexpected command", "argv": argv}

        return runner

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                report = self.module.activate_runtime(apply_user_level=False, allow_ssh_keygen=False)
            self.assertEqual(report["status"], "WARN")
            self.assertFalse((home / ".ssh" / "config.d" / "dev-management.conf").exists())

    def test_apply_creates_config_snippet_and_include_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                first = self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
                second = self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
            config = (home / ".ssh" / "config").read_text(encoding="utf-8")
            snippet = (home / ".ssh" / "config.d" / "dev-management.conf").read_text(encoding="utf-8")
            self.assertIn("Include ~/.ssh/config.d/*.conf", config)
            self.assertEqual(config.count("Include ~/.ssh/config.d/*.conf"), 1)
            self.assertIn("Host devmgmt-wsl", snippet)
            self.assertEqual(first["ssh_probe_result"]["status"], "PASS")
            self.assertEqual(second["ssh_probe_result"]["status"], "PASS")

    def test_key_generation_requires_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                report = self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=False)
            self.assertFalse((home / ".ssh" / "devmgmt_wsl_ed25519").exists())
            self.assertEqual(report["status"], "WARN")

    def test_authorized_keys_marker_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
                self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
            auth_keys = (home / ".ssh" / "authorized_keys").read_text(encoding="utf-8")
            self.assertEqual(auth_keys.count(self.module.AUTH_KEYS_MARKER_BEGIN), 1)

    def test_existing_config_is_backed_up_before_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            ssh_root = home / ".ssh"
            ssh_root.mkdir()
            (ssh_root / "config").write_text("Host example\n", encoding="utf-8")
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                report = self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
            backups = list(ssh_root.glob("config.bak.*"))
            self.assertTrue(backups)
            self.assertTrue(report["backups_created"])

    def test_private_key_contents_are_never_printed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            repo_root = home / "repo"
            repo_root.mkdir()
            with patch.object(self.module, "home_dir", return_value=home), patch.object(
                self.module, "load_authority", return_value=self._authority(repo_root)
            ), patch.object(self.module, "run", side_effect=self._fake_run(home)):
                report = self.module.activate_runtime(apply_user_level=True, allow_ssh_keygen=True)
            self.assertNotIn("PRIVATE-KEY-CONTENT", json.dumps(report, ensure_ascii=False))
            self.assertNotIn("/etc/", "\n".join(report["files_touched"]))


if __name__ == "__main__":
    unittest.main()
