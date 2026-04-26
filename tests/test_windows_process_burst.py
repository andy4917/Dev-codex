from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_process_burst.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_process_burst", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_process_burst.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proc(pid: int, ppid: int, name: str, command: str) -> dict[str, object]:
    return {
        "ProcessId": pid,
        "ParentProcessId": ppid,
        "Name": name,
        "CommandLine": command,
        "CreationDate": "2026-04-26T00:00:00+00:00",
        "WorkingSetSize": 10 * 1024 * 1024,
    }


class WindowsProcessBurstTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_groups_python_node_and_ssh_children_by_parent_command_line(self) -> None:
        parent = proc(100, 1, "powershell.exe", "powershell.exe -File process-burst-harness.ps1")
        samples = [
            {
                "sampled_at": "2026-04-26T00:00:00+00:00",
                "processes": [
                    parent,
                    proc(101, 100, "python.exe", "python.exe -c import time; time.sleep(5)"),
                    proc(102, 100, "node.exe", "node.exe -e setTimeout(() => {}, 5000)"),
                    proc(103, 100, "ssh.exe", "ssh.exe -V"),
                ],
            }
        ]
        report = self.module.evaluate_samples(samples, min_fanout=3)
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["burst_group_count"], 1)
        top = report["top_responsible_parent"]
        self.assertEqual(top["parent_pid"], 100)
        self.assertEqual(top["parent_command_line"], "powershell.exe -File process-burst-harness.ps1")
        self.assertEqual(top["observed_child_names"], ["node.exe", "python.exe", "ssh.exe"])

    def test_no_fanout_passes_but_keeps_observed_groups(self) -> None:
        parent = proc(100, 1, "powershell.exe", "powershell.exe")
        samples = [
            {
                "sampled_at": "2026-04-26T00:00:00+00:00",
                "processes": [parent, proc(101, 100, "python.exe", "python.exe -V")],
            }
        ]
        report = self.module.evaluate_samples(samples, min_fanout=2)
        self.assertEqual(report["status"], "PASS")
        self.assertIsNone(report["top_responsible_parent"])
        self.assertEqual(report["burst_groups"][0]["observed_child_count"], 1)


if __name__ == "__main__":
    unittest.main()
