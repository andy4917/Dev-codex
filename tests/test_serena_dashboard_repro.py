from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_serena_dashboard_repro.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_serena_dashboard_repro", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_serena_dashboard_repro.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SerenaDashboardReproTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_open_dashboard_arg_value_accepts_split_false(self) -> None:
        args = ["start-mcp-server", "--project-from-cwd", "--open-web-dashboard", "False"]
        self.assertIs(self.module.open_dashboard_arg_value(args), False)

    def test_serena_config_parser_separates_server_from_opening(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "serena_config.yml"
            path.write_text(
                "web_dashboard: true\nweb_dashboard_open_on_launch: false\nweb_dashboard_listen_address: 127.0.0.1\n",
                encoding="utf-8",
            )
            values = self.module.read_serena_global_config(path)["values"]
        self.assertIs(values["web_dashboard"], True)
        self.assertIs(values["web_dashboard_open_on_launch"], False)

    def test_log_summary_extracts_dashboard_port_and_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mcp_20260426-120000_1234.txt"
            path.write_text(
                "\n".join(
                    [
                        "INFO serena.dashboard:run_in_thread - Starting dashboard (listen_address=127.0.0.1, port=24283)",
                        "INFO serena.agent - Serena web dashboard started at http://127.0.0.1:24283/dashboard/index.html",
                    ]
                ),
                encoding="utf-8",
            )
            summary = self.module.summarize_log(path)
        self.assertTrue(summary["dashboard_started"])
        self.assertEqual(summary["dashboard_ports"], [24283])
        self.assertEqual(summary["pid_from_filename"], 1234)

    def test_classifies_global_dashboard_server_when_local_opening_is_suppressed(self) -> None:
        report = {
            "codex_serena_config": {"open_web_dashboard_arg": False},
            "serena_global_config": {
                "values": {"web_dashboard": True, "web_dashboard_open_on_launch": False}
            },
            "recent_serena_logs": {"dashboard_start_count": 3},
            "launch_probe": {"enabled": False},
        }
        diagnosis = self.module.classify(report)
        self.assertEqual(diagnosis["status"], "WARN")
        self.assertEqual(
            diagnosis["root_cause"],
            "SERENA_CONFIG_ENABLES_DASHBOARD_SERVER_LOCAL_CONFIG_ONLY_SUPPRESSES_OPENING",
        )

    def test_classifies_probe_as_serena_side_when_false_flag_still_creates_dashboard(self) -> None:
        report = {
            "codex_serena_config": {"open_web_dashboard_arg": False},
            "serena_global_config": {
                "values": {"web_dashboard": True, "web_dashboard_open_on_launch": False}
            },
            "recent_serena_logs": {"dashboard_start_count": 1},
            "serena_process_snapshot": {"count": 1, "all_open_web_dashboard_args_false": True},
            "launch_probe": {"enabled": True, "dashboard_created": True},
        }
        diagnosis = self.module.classify(report)
        self.assertIn("serena_side_dashboard_server_creation_reproduced", diagnosis["findings"])
        self.assertEqual(
            diagnosis["root_cause"],
            "SERENA_DASHBOARD_SERVER_STARTS_DESPITE_LOCAL_OPEN_SUPPRESSION",
        )

    def test_serena_process_snapshot_finds_runtime_false_arg(self) -> None:
        snapshot = self.module.serena_process_snapshot(
            [
                {
                    "ProcessId": 10,
                    "ParentProcessId": 1,
                    "Name": "python3.13.exe",
                    "CommandLine": "python serena start-mcp-server --project-from-cwd --context=codex --open-web-dashboard False",
                }
            ]
        )
        self.assertEqual(snapshot["count"], 1)
        self.assertIs(snapshot["processes"][0]["open_web_dashboard_arg"], False)

    def test_repeated_mcp_roots_are_control_plane_surface(self) -> None:
        report = {
            "codex_serena_config": {"open_web_dashboard_arg": False},
            "serena_global_config": {
                "values": {"web_dashboard": True, "web_dashboard_open_on_launch": False}
            },
            "recent_serena_logs": {"dashboard_start_count": 2},
            "serena_process_snapshot": {"count": 2, "all_open_web_dashboard_args_false": True},
            "launch_probe": {"enabled": True, "dashboard_created": True},
        }
        diagnosis = self.module.classify(report)
        self.assertEqual(
            diagnosis["root_cause"],
            "LOCAL_CONTROL_PLANE_REPEATS_SERENA_MCP_STARTS_AND_SERENA_CREATES_ONE_DASHBOARD_SERVER_PER_ROOT",
        )
        self.assertIn("local_control_plane_repeated_serena_mcp_roots", diagnosis["findings"])


if __name__ == "__main__":
    unittest.main()
