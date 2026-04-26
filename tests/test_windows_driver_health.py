from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_driver_health.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_driver_health", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_driver_health.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DISPLAY_OUTPUT = """
Instance ID:                PCI\\VEN_8086&DEV_64A0
Device Description:         Intel(R) Arc(TM) 130V GPU (16GB)
Class Name:                 Display
Driver Name:                oem213.inf
    Driver Name:            oem213.inf
    Provider Name:          Intel Corporation
    Class Name:             Display
    Driver Version:         09/19/2025 32.0.101.8132
    Driver Name:            oem143.inf
    Provider Name:          Intel Corporation
    Class Name:             Display
    Driver Version:         04/02/2026 32.0.101.8629
"""


STORE_OUTPUT = """
Published Name:     oem143.inf
Original Name:      iigd_dch.inf
Provider Name:      Intel Corporation
Class Name:         Display
Driver Version:     04/02/2026 32.0.101.8629

Published Name:     oem999.inf
Provider Name:      Intel Corporation
Class Name:         Display
Driver Version:     04/21/2026 32.0.101.8735
"""


class WindowsDriverHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_parse_display_device_active_driver_version(self) -> None:
        parsed = self.module.parse_display_device_drivers(DISPLAY_OUTPUT)
        devices = self.module.intel_display_devices(parsed)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["active_driver_name"], "oem213.inf")
        self.assertEqual(devices[0]["active_driver_version"], "32.0.101.8132")
        self.assertEqual(devices[0]["driver_entries"][1]["driver_version"], "32.0.101.8629")

    def test_driver_state_blocks_when_target_not_active_or_staged_and_not_admin(self) -> None:
        parsed = self.module.parse_display_device_drivers(DISPLAY_OUTPUT)
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = Path(temp_dir) / "gfx_win_101.8735.exe"
            installer.write_bytes(b"stub")
            report = self.module.evaluate_driver_state(
                display_devices=self.module.intel_display_devices(parsed),
                driver_store=self.module.parse_driver_store(STORE_OUTPUT.replace("32.0.101.8735", "32.0.101.8724")),
                target_version="32.0.101.8735",
                installer_path=installer,
                installer_processes=[],
                admin=False,
            )

        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["target_active"])
        self.assertFalse(report["target_staged"])
        self.assertIn("current shell is not elevated", " ".join(report["blockers"]))

    def test_driver_state_passes_when_target_active(self) -> None:
        device = {
            "device_description": "Intel(R) Arc(TM) 130V GPU",
            "active_driver_version": "32.0.101.8735",
            "driver_entries": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            installer = Path(temp_dir) / "gfx_win_101.8735.exe"
            installer.write_bytes(b"stub")
            report = self.module.evaluate_driver_state(
                display_devices=[device],
                driver_store=self.module.parse_driver_store(STORE_OUTPUT),
                target_version="32.0.101.8735",
                installer_path=installer,
                installer_processes=[{"Id": 1}],
                admin=True,
            )

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["target_active"])


if __name__ == "__main__":
    unittest.main()
