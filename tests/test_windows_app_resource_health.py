from __future__ import annotations

import importlib.util
import sys
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_windows_app_resource_health.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_windows_app_resource_health", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_windows_app_resource_health.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def proc(pid: int, ppid: int, name: str, command: str, minutes_old: int, mb: int) -> dict[str, object]:
    now = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    return {
        "ProcessId": pid,
        "ParentProcessId": ppid,
        "Name": name,
        "CommandLine": command,
        "CreationDate": now.replace(minute=0).isoformat(),
        "WorkingSetSize": mb * 1024 * 1024,
        "_minutes_old": minutes_old,
    }


class WindowsAppResourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.now = datetime(2026, 4, 26, 2, 0, tzinfo=timezone.utc)

    def _proc(self, pid: int, ppid: int, name: str, command: str, minutes_old: int, mb: int) -> dict[str, object]:
        created = datetime(2026, 4, 26, 2, 0, tzinfo=timezone.utc)
        created = created.replace(minute=0)
        created = created.fromtimestamp(created.timestamp() - minutes_old * 60, tz=timezone.utc)
        return {
            "ProcessId": pid,
            "ParentProcessId": ppid,
            "Name": name,
            "CommandLine": command,
            "CreationDate": created.isoformat(),
            "WorkingSetSize": mb * 1024 * 1024,
        }

    def test_duplicate_old_serena_roots_are_cleanup_candidates_with_descendants(self) -> None:
        active = self._proc(10, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 1, 5)
        stale = self._proc(20, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 30, 5)
        child = self._proc(21, 20, "python.exe", "python.exe serena.exe start-mcp-server --project-from-cwd --context=codex", 30, 10)
        node = self._proc(22, 21, "node.exe", "node.exe TypeScriptLanguageServer tsserver", 30, 60)
        report = self.module.evaluate_processes(
            [active, stale, child, node, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            stale_minutes=10,
            cleanup_duplicate_serena_roots=True,
        )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["process_counts"]["serena_roots"], 2)
        self.assertEqual({item["pid"] for item in report["cleanup_candidates"]}, {20, 21, 22})

    def test_duplicate_serena_roots_are_protected_by_default(self) -> None:
        active = self._proc(10, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 1, 5)
        duplicate = self._proc(20, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 2, 5)
        child = self._proc(21, 20, "python.exe", "python.exe serena.exe start-mcp-server --project-from-cwd --context=codex", 2, 10)
        report = self.module.evaluate_processes(
            [active, duplicate, child, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            stale_minutes=10,
            duplicate_serena_grace_minutes=1,
        )
        self.assertEqual(report["cleanup_candidate_summary"]["count"], 0)
        self.assertEqual(
            report["cleanup_candidate_summary"]["protected_duplicate_serena_roots"][0]["pid"],
            20,
        )
        self.assertIn("duplicate Serena MCP roots observed but protected", " ".join(report["warnings"]))

    def test_duplicate_serena_roots_can_be_explicit_cleanup_candidates_after_grace(self) -> None:
        active = self._proc(10, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 1, 5)
        duplicate = self._proc(20, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 2, 5)
        child = self._proc(21, 20, "python.exe", "python.exe serena.exe start-mcp-server --project-from-cwd --context=codex", 2, 10)
        report = self.module.evaluate_processes(
            [active, duplicate, child, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            stale_minutes=10,
            duplicate_serena_grace_minutes=1,
            cleanup_duplicate_serena_roots=True,
        )
        self.assertEqual({item["pid"] for item in report["cleanup_candidates"]}, {20, 21})

    def test_duplicate_serena_grace_prevents_immediate_startup_cleanup(self) -> None:
        active = self._proc(10, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 0, 5)
        duplicate = self._proc(20, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 0, 5)
        report = self.module.evaluate_processes(
            [active, duplicate, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            stale_minutes=10,
            duplicate_serena_grace_minutes=1,
        )
        self.assertEqual(report["cleanup_candidate_summary"]["count"], 0)

    def test_single_fresh_serena_root_passes_when_codex_is_running(self) -> None:
        report = self.module.evaluate_processes(
            [
                self._proc(10, 1, "serena.exe", "serena.exe start-mcp-server --project-from-cwd --context=codex", 1, 5),
                self._proc(11, 10, "python.exe", "python.exe serena.exe start-mcp-server --project-from-cwd --context=codex", 1, 10),
                self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200),
            ],
            now=self.now,
            stale_minutes=10,
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["cleanup_candidate_summary"]["count"], 0)

    def test_codex_renderer_and_gpu_cpu_are_reported_separately(self) -> None:
        renderer = self._proc(
            30,
            1,
            "Codex.exe",
            "Codex.exe --type=renderer --user-data-dir=C:/Users/anise/AppData/Roaming/Codex",
            1,
            400,
        )
        gpu = self._proc(
            31,
            1,
            "Codex.exe",
            "Codex.exe --type=gpu-process --user-data-dir=C:/Users/anise/AppData/Roaming/Codex",
            1,
            280,
        )
        app_server = self._proc(
            32,
            1,
            "codex.exe",
            "C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe app-server",
            1,
            160,
        )

        report = self.module.evaluate_processes(
            [renderer, gpu, app_server],
            now=self.now,
            cpu_samples={"codex": 34.0},
            process_cpu_samples=[
                {"pid": 30, "instance": "codex", "avg_cpu_pct": 21.5},
                {"pid": 31, "instance": "codex", "avg_cpu_pct": 12.0},
                {"pid": 32, "instance": "codex", "avg_cpu_pct": 0.5},
            ],
        )

        self.assertEqual(report["cpu_samples"]["codex_by_role"]["renderer"], 21.5)
        self.assertEqual(report["cpu_samples"]["codex_by_role"]["gpu_process"], 12.0)
        self.assertEqual(report["cpu_samples"]["codex_by_role"]["app_server"], 0.5)
        self.assertIn("Codex App renderer sampled CPU is high: 21.5%", report["warnings"])
        self.assertIn("Codex App gpu_process sampled CPU is high: 12.0%", report["warnings"])

    def test_codex_cpu_report_includes_system_normalized_percent(self) -> None:
        report = self.module.evaluate_processes(
            [self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            cpu_samples={"codex": 64.0},
            logical_processors=32,
        )

        self.assertEqual(report["cpu_samples"]["codex_cpu_pct"], 64.0)
        self.assertEqual(report["cpu_samples"]["codex_cpu_unit"], "pct_of_one_logical_cpu")
        self.assertEqual(report["cpu_samples"]["logical_processors"], 32)
        self.assertEqual(report["cpu_samples"]["codex_system_cpu_pct"], 2.0)
        self.assertIn("Codex App sampled CPU is high: 64.0% of one logical CPU", report["warnings"])

    def test_codex_priority_throttle_reports_changed_processes(self) -> None:
        codex = self._proc(30, 1, "Codex.exe", "Codex.exe --type=renderer", 1, 400)

        completed = type(
            "Completed",
            (),
            {
                "stdout": (
                    '[{"pid":30,"old_priority":"AboveNormal","new_priority":"BelowNormal",'
                    '"priority_boost_enabled":false,"status":"changed"}]'
                ),
            },
        )()
        with mock.patch.object(self.module.subprocess, "run", return_value=completed):
            result = self.module.throttle_codex_priority([codex])

        self.assertEqual(result["attempted"], [30])
        self.assertEqual(result["changed"][0]["new_priority"], "BelowNormal")

    def test_codex_gpu_preference_targets_live_codex_executables(self) -> None:
        main = self._proc(
            30,
            1,
            "Codex.exe",
            '"C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe"',
            1,
            400,
        )
        renderer = self._proc(
            31,
            30,
            "Codex.exe",
            '"C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe" --type=renderer',
            1,
            300,
        )
        app_server = self._proc(
            32,
            30,
            "codex.exe",
            '"C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe" app-server',
            1,
            120,
        )
        main["ExecutablePath"] = "C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe"
        app_server["ExecutablePath"] = "C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe"

        completed = type(
            "Completed",
            (),
            {
                "stdout": (
                    "["
                    '{"path":"C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe",'
                    '"value":"GpuPreference=1;","status":"changed"},'
                    '{"path":"C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe",'
                    '"value":"GpuPreference=1;","status":"changed"}'
                    "]"
                ),
            },
        )()
        with mock.patch.object(self.module.subprocess, "run", return_value=completed) as run:
            result = self.module.set_codex_gpu_preference([main, renderer, app_server])

        self.assertEqual(
            result["attempted"],
            [
                "C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe",
                "C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe",
            ],
        )
        self.assertEqual(result["value"], "GpuPreference=1;")
        self.assertTrue(result["requires_restart"])
        self.assertEqual(len(result["changed"]), 2)
        self.assertIn("UserGpuPreferences", run.call_args.args[0][-1])

    def test_codex_gpu_preference_reports_registry_failures_without_crashing(self) -> None:
        codex = self._proc(30, 1, "Codex.exe", '"C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe"', 1, 400)
        codex["ExecutablePath"] = "C:/Program Files/WindowsApps/OpenAI.Codex/Codex.exe"
        error = self.module.subprocess.CalledProcessError(
            1,
            ["powershell"],
            output="",
            stderr="registry denied",
        )

        with mock.patch.object(self.module.subprocess, "run", side_effect=error):
            result = self.module.set_codex_gpu_preference([codex])

        self.assertTrue(result["blocked"])
        self.assertFalse(result["requires_restart"])
        self.assertEqual(result["failed"][0]["error"], "registry denied")

    def test_blocked_gpu_preference_promotes_report_to_blocked(self) -> None:
        report = {
            "warnings": [],
            "blockers": [],
            "codex_gpu_preference": {
                "blocked": True,
                "failed": [{"path": "Codex.exe", "error": "registry denied"}],
            },
        }

        self.module.append_requested_action_issues(
            report,
            "codex_gpu_preference",
            "Codex App low-power GPU preference",
        )
        self.module.refresh_report_status(report)

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("Codex App low-power GPU preference blocked: registry denied", report["blockers"])

    def test_failed_priority_throttle_promotes_report_to_warn(self) -> None:
        report = {
            "warnings": [],
            "blockers": [],
            "codex_priority_throttle": {
                "attempted": [30],
                "changed": [],
                "failed": [{"pid": 30, "error": "access denied"}],
            },
        }

        self.module.append_requested_action_issues(
            report,
            "codex_priority_throttle",
            "Codex App priority throttle",
        )
        self.module.refresh_report_status(report)

        self.assertEqual(report["status"], "WARN")
        self.assertIn("Codex App priority throttle had failed target(s): 1", report["warnings"])

    def test_dirty_git_eol_hazards_include_only_dirty_lf_policy_mismatches(self) -> None:
        diff = type("Completed", (), {"stdout": "contracts/app_surface_policy.json\ndocs/ok.md\n"})()
        eol = type(
            "Completed",
            (),
            {
                "stdout": (
                    "i/lf    w/mixed attr/text=auto eol=lf \tcontracts/app_surface_policy.json\n"
                    "i/lf    w/lf    attr/text=auto eol=lf \tdocs/ok.md\n"
                )
            },
        )()

        def fake_run(args, **_kwargs):
            if args[:4] == ["git", "diff", "--name-only", "--"]:
                return diff
            if args[:4] == ["git", "ls-files", "--eol", "--"]:
                return eol
            raise AssertionError(args)

        with mock.patch.object(self.module.subprocess, "run", side_effect=fake_run):
            result = self.module.get_dirty_git_eol_hazards()

        self.assertFalse(result["failed"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["files"][0]["path"], "contracts/app_surface_policy.json")

    def test_stale_al_language_server_is_cleanup_candidate(self) -> None:
        al = self._proc(
            40,
            1,
            "Microsoft.Dynamics.Nav.EditorServices.Host.exe",
            "C:/Users/anise/.serena/language_servers/static/ALLanguageServer/al-extension/extension/bin/win32/Microsoft.Dynamics.Nav.EditorServices.Host.exe",
            120,
            52,
        )
        report = self.module.evaluate_processes(
            [al, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=self.now,
            stale_minutes=10,
        )
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["cleanup_candidates"][0]["pid"], 40)

    def test_duplicate_serena_cleanup_risk_report_blocks_transport_kill(self) -> None:
        report = {"cleanup_candidate_summary": {"count": 3}}
        risk = self.module.duplicate_serena_cleanup_risk_report(report)

        self.assertTrue(risk["blocked"])
        self.assertEqual(risk["candidate_count"], 3)
        self.assertEqual(risk["attempted"], [])
        self.assertIn("active Codex MCP transport", risk["reason"])

    def test_powershell_json_dotnet_dates_are_parsed_for_live_cleanup(self) -> None:
        parsed = self.module._parse_time("/Date(1777195973119)/")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.isoformat(), "2026-04-26T09:32:53.119000+00:00")

        stale = {
            "ProcessId": 20,
            "ParentProcessId": 1,
            "Name": "serena.exe",
            "CommandLine": "serena.exe start-mcp-server --project-from-cwd --context=codex",
            "CreationDate": "/Date(1777195973119)/",
            "WorkingSetSize": 5 * 1024 * 1024,
        }
        active = {
            "ProcessId": 10,
            "ParentProcessId": 1,
            "Name": "serena.exe",
            "CommandLine": "serena.exe start-mcp-server --project-from-cwd --context=codex",
            "CreationDate": "/Date(1777196272882)/",
            "WorkingSetSize": 5 * 1024 * 1024,
        }
        report = self.module.evaluate_processes(
            [stale, active, self._proc(30, 1, "Codex.exe", "Codex.exe", 1, 200)],
            now=datetime(2026, 4, 26, 9, 44, tzinfo=timezone.utc),
            duplicate_serena_grace_minutes=1,
            cleanup_duplicate_serena_roots=True,
        )
        self.assertEqual(report["cleanup_candidates"][0]["pid"], 20)
        self.assertEqual(report["cleanup_candidate_summary"]["kept_serena_roots"], [10])


if __name__ == "__main__":
    unittest.main()
