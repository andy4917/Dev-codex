from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_global_runtime.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_global_runtime", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_global_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckGlobalRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _authority(self) -> dict[str, object]:
        return {
            "forbidden_primary_runtime_paths": [
                "/mnt/c/Users/anise/.codex/bin/wsl",
                "/mnt/c/Users/anise/.codex/tmp/arg0",
                ".codex/bin/wsl/codex",
            ],
            "canonical_execution_surface": {
                "id": "ssh-devmgmt-wsl",
                "host_alias": "devmgmt-wsl",
                "repo_root": "/home/andy4917/Dev-Management",
                "forbidden_primary_resolution": "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            },
            "observed_remote_evidence": {
                "codex_app_remote_record": {
                    "value": "andy4917@localhost:22",
                    "authoritative": False,
                }
            },
            "generation_targets": {
                "global_runtime": {
                    "linux": {
                        "config": str(Path.home() / ".codex" / "config.toml"),
                        "launcher": str(Path.home() / ".local" / "bin" / "codex"),
                    },
                    "windows_mirror": {
                        "config": "/mnt/c/Users/anise/.codex/config.toml",
                    },
                }
            },
        }

    def _local_probe(
        self,
        *,
        command_v: str,
        precedence: str,
        client_status: str = "PASS",
        local_shell_status: str | None = None,
        contaminated: list[str] | None = None,
    ) -> dict[str, object]:
        live_status = "BLOCKED" if "/mnt/c/Users/anise/.codex/bin/wsl/codex" in command_v else "PASS"
        return {
            "command_v": command_v,
            "type_a": [f"codex is {command_v}"] if command_v else [],
            "type_a_paths": [command_v] if command_v else [],
            "path_entries": [],
            "contaminated_entries": contaminated or [],
            "local_live_codex_resolution_status": {
                "status": live_status,
                "reason": "",
            },
            "local_path_precedence_status": {
                "status": precedence,
                "reason": "",
            },
            "config_surfaces": {},
            "local_wrapper_probe": {"status": "BLOCKED" if live_status == "BLOCKED" else "PASS", "target": command_v},
            "client_surface_status": {"status": client_status, "reason": ""},
            "local_shell_status": {
                "status": local_shell_status or ("BLOCKED" if live_status == "BLOCKED" or precedence == "BLOCKED" else "PASS"),
                "reason": "",
            },
            "command_v_candidate": {},
            "type_a_candidates": [],
            "path_normalizer": {"repo_owned": False},
        }

    def _remote_probe(
        self,
        *,
        canonical_status: str,
        repo_root_status: str | None = None,
        codex_status: str = "PASS",
        native_status: str = "PASS",
        path_status: str | None = None,
        command_v: str = "/usr/local/bin/codex",
        native_path: str = "/usr/local/bin/codex",
    ) -> dict[str, object]:
        repo_status = repo_root_status or canonical_status
        path_state = path_status or canonical_status
        return {
            "ssh_available": canonical_status == "PASS",
            "stderr": "" if canonical_status == "PASS" else "ssh unresolved",
            "hostname": "localhost" if canonical_status == "PASS" else "",
            "type_a": [f"codex is {command_v}"] if command_v else [],
            "type_a_paths": [command_v] if command_v else [],
            "type_a_candidates": [],
            "path_entries": [],
            "ssh_runtime_status": {"status": canonical_status, "reason": ""},
            "canonical_ssh_runtime_status": {"status": canonical_status, "reason": ""},
            "remote_repo_root_status": {"status": repo_status, "reason": "", "observed_repo_root": "/home/andy4917/Dev-Management"},
            "remote_codex_resolution_status": {"status": codex_status, "reason": "", "command_v": command_v, "command_v_candidate": {}},
            "remote_native_codex_status": {"status": native_status, "reason": "", "selected_path": native_path, "candidates": [{"path": native_path}] if native_status == "PASS" else []},
            "remote_path_contamination_status": {"status": path_state, "reason": "", "contaminated_entries": []},
        }

    def _evaluate(self, local_probe: dict[str, object], remote_probe: dict[str, object], *, mode: str = "auto") -> dict[str, object]:
        authority = self._authority()
        with patch.object(self.module, "load_authority", return_value=authority), patch.object(
            self.module, "local_runtime_probe", return_value=local_probe
        ), patch.object(
            self.module, "remote_runtime_probe", return_value=remote_probe
        ), patch.object(
            self.module, "render_wrapper_target_safety", return_value={"status": "PASS"}
        ), patch.object(
            self.module, "write_preview_wrapper", return_value="/tmp/codex-ssh-wrapper.sh"
        ), patch.object(
            self.module, "git_diff_check_status", return_value={"status": "PASS", "reason": ""}
        ):
            return self.module.evaluate_global_runtime(ROOT, mode=mode)

    def test_forbidden_windows_launcher_path_is_detected(self) -> None:
        authority = self._authority()
        self.assertTrue(self.module.is_forbidden_runtime_value("/mnt/c/Users/anise/.codex/bin/wsl", authority))
        self.assertTrue(self.module.is_forbidden_runtime_value("/mnt/c/Users/anise/.codex/bin/wsl/codex", authority))

    def test_arg0_path_is_detected(self) -> None:
        authority = self._authority()
        self.assertTrue(
            self.module.is_forbidden_runtime_value("/mnt/c/Users/anise/.codex/tmp/arg0/codex-arg0ABCDE", authority)
        )

    def test_auto_mode_is_fail_closed_when_canonical_ssh_is_unavailable(self) -> None:
        report = self._evaluate(
            self._local_probe(command_v="/usr/local/bin/codex", precedence="PASS"),
            self._remote_probe(canonical_status="BLOCKED"),
        )
        self.assertEqual(report["mode_selected"], "ssh-managed")
        self.assertTrue(report["fail_closed"])
        self.assertEqual(report["overall_status"], "BLOCKED")

    def test_canonical_pass_with_client_contamination_is_warn_not_blocked(self) -> None:
        report = self._evaluate(
            self._local_probe(
                command_v="/mnt/c/Users/anise/.codex/bin/wsl/codex",
                precedence="BLOCKED",
                client_status="WARN",
                contaminated=["/mnt/c/Users/anise/.codex/bin/wsl"],
            ),
            self._remote_probe(canonical_status="PASS"),
        )
        self.assertEqual(report["canonical_execution_status"], "PASS")
        self.assertEqual(report["client_surface_status"], "WARN")
        self.assertEqual(report["local_shell_status"], "BLOCKED")
        self.assertEqual(report["overall_status"], "WARN")

    def test_canonical_fail_with_clean_local_path_remains_blocked(self) -> None:
        report = self._evaluate(
            self._local_probe(command_v="/usr/local/bin/codex", precedence="PASS"),
            self._remote_probe(canonical_status="BLOCKED"),
        )
        self.assertEqual(report["overall_status"], "BLOCKED")
        self.assertEqual(report["canonical_execution_status"], "BLOCKED")

    def test_local_execution_request_with_forbidden_path_is_blocked(self) -> None:
        report = self._evaluate(
            self._local_probe(
                command_v="/mnt/c/Users/anise/.codex/bin/wsl/codex",
                precedence="BLOCKED",
                client_status="WARN",
                contaminated=["/mnt/c/Users/anise/.codex/bin/wsl"],
            ),
            self._remote_probe(canonical_status="PASS"),
            mode="local",
        )
        self.assertEqual(report["mode_selected"], "local")
        self.assertEqual(report["overall_status"], "BLOCKED")

    def test_generated_config_vs_user_override_classification(self) -> None:
        authority = self._authority()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            linux_config = tmp / "linux-config.toml"
            linux_user_override = tmp / "linux-user-config.toml"
            windows_config = tmp / "windows-config.toml"
            linux_config.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "on-request"\n', encoding="utf-8")
            linux_user_override.write_text('approval_policy = "never"\n', encoding="utf-8")
            windows_config.write_text('# GENERATED - DO NOT EDIT\napproval_policy = "on-request"\n', encoding="utf-8")
            authority["generation_targets"]["global_runtime"]["linux"]["config"] = str(linux_config)
            authority["generation_targets"]["global_runtime"]["linux"]["user_override_config"] = str(linux_user_override)
            authority["generation_targets"]["global_runtime"]["windows_mirror"]["config"] = str(windows_config)

            linux_result = self.module.config_surface_classification(linux_config, authority)
            linux_override_result = self.module.config_surface_classification(linux_user_override, authority)
            windows_result = self.module.config_surface_classification(windows_config, authority)

        self.assertEqual(linux_result["classification"], "generated")
        self.assertTrue(linux_result["repairable"])
        self.assertEqual(linux_override_result["classification"], "user_override")
        self.assertFalse(linux_override_result["repairable"])
        self.assertEqual(windows_result["classification"], "generated")
        self.assertTrue(windows_result["repairable"])

    def test_path_normalizer_defaults_to_non_repo_owned_without_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir) / "wsl-runtime-paths.sh"
            tmp.write_text("#!/bin/sh\nPATH=/usr/bin\n", encoding="utf-8")
            with patch.object(self.module, "PATH_NORMALIZER", tmp):
                result = self.module.detect_path_normalizer_surface(self._authority())
        self.assertFalse(result["repo_owned"])

    def test_linux_native_candidate_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmpdir:
            candidate = Path(tmpdir) / "codex"
            candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            result = self.module.classify_codex_candidate(
                str(candidate),
                self._authority(),
                local_launcher=Path(tmpdir) / "local-codex",
                preview_launcher=Path(tmpdir) / "preview-codex",
            )
        self.assertEqual(result["classification"], "linux_native_candidate")
        self.assertTrue(result["native_candidate"])

    def test_windows_launcher_candidate_is_rejected(self) -> None:
        result = self.module.classify_codex_candidate(
            "/mnt/c/Users/anise/.codex/bin/wsl/codex",
            self._authority(),
            local_launcher=Path("/tmp/local-codex"),
            preview_launcher=Path("/tmp/preview-codex"),
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_repo_generated_ssh_wrapper_is_not_native_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            preview = tmp / "preview-codex"
            preview.write_text(
                "#!/usr/bin/env bash\n"
                "# generated by Dev-Management\n"
                'exec ssh -o BatchMode=yes "$host_alias" "$remote_cmd"\n',
                encoding="utf-8",
            )
            result = self.module.classify_codex_candidate(
                str(preview),
                self._authority(),
                local_launcher=tmp / "local-codex",
                preview_launcher=preview,
            )
        self.assertEqual(result["classification"], "repo_generated_ssh_wrapper")
        self.assertFalse(result["native_candidate"])


if __name__ == "__main__":
    unittest.main()
