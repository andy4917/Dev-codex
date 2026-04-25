from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from devmgmt_runtime import subprocess_safe


class SubprocessSafeTests(unittest.TestCase):
    def test_run_powershell_uses_hidden_noninteractive_flags(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        with patch("subprocess.run", return_value=completed) as mock_run:
            subprocess_safe.run_powershell('& "$env:WINDIR\\System32\\OpenSSH\\ssh.exe" -V', set_userprofile=False)

        args = mock_run.call_args.args[0]
        self.assertTrue(args[0].lower().endswith("pwsh.exe") or args[0] == "pwsh")
        self.assertEqual(
            args[1:8],
            [
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
            ],
        )
        self.assertEqual(args[8], "-Command")
        self.assertIn('OpenSSH\\ssh.exe', args[9])


if __name__ == "__main__":
    unittest.main()
