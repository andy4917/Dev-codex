from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "iaw_closeout.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("iaw_closeout", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load iaw_closeout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True, text=True, encoding="utf-8")


def _git_output(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True, text=True, encoding="utf-8")
    return result.stdout.strip()


class IAWCloseoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_validate_manifest_blocks_changed_file_set_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir(parents=True)
            _git(workspace, "init")
            _git(workspace, "config", "user.email", "codex@example.com")
            _git(workspace, "config", "user.name", "Codex")
            _write_text(workspace / "tracked.txt", "one\n")
            _git(workspace, "add", "tracked.txt")
            _git(workspace, "commit", "-m", "init")
            _write_text(workspace / "tracked.txt", "two\n")

            run_id = "run-001"
            paths = self.module._artifact_paths(workspace, run_id)
            head = _git_output(workspace, "rev-parse", "HEAD")
            _write_json(
                paths["manifest"],
                {
                    "schema_version": 1,
                    "run_id": run_id,
                    "workspace_root_realpath": str(workspace.resolve()),
                    "git_root": str(workspace.resolve()),
                    "base_commit": head,
                    "head_commit": head,
                    "changed_files": ["tracked.txt"],
                    "changed_file_set_hash": "bad-hash",
                    "commands": [{"command_id": "cmd-1", "cmd": "pytest", "cwd": str(workspace), "exit_code": 0, "started_at": "2026-04-20T00:00:00Z", "ended_at": "2026-04-20T00:00:01Z"}],
                    "artifacts": [],
                    "waivers": [],
                    "policy_hashes": {"current": {}},
                    "script_hashes": {},
                    "state_history": [{"state": "SELF_VERIFIED", "entered_at": "2026-04-20T00:00:02Z"}],
                },
            )

            with patch.object(self.module, "_required_policy_hashes", return_value={}), patch.object(
                self.module, "_required_script_hashes", return_value={}
            ), patch.object(self.module, "_current_changed_files", return_value=["tracked.txt"]):
                reasons, _manifest, _meta = self.module._validate_manifest(
                    authority={},
                    workspace_root=workspace.resolve(),
                    run_id=run_id,
                    paths=paths,
                )

        self.assertIn("evidence manifest changed_file_set_hash mismatch", reasons)

    def test_main_writes_signed_receipt_for_successful_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            codex_home = temp / "codex-home"
            workspace = temp / "workspace"
            workspace.mkdir(parents=True)
            _git(workspace, "init")
            _git(workspace, "config", "user.email", "codex@example.com")
            _git(workspace, "config", "user.name", "Codex")
            _write_text(workspace / "README.md", "hello\n")
            _git(workspace, "add", "README.md")
            _git(workspace, "commit", "-m", "init")
            _write_text(workspace / "SUMMARY.md", "# Summary\n")

            run_id = "run-002"
            run_root = workspace / ".agent-runs" / run_id
            for name, payload in {
                "WORKORDER.json": {"schema_version": 1},
                "PLAN.json": {"plan": []},
                "TASK_TREE.json": {"tasks": []},
                "EVIDENCE_MANIFEST.json": {"schema_version": 1},
                "WAIVERS.json": {"waivers": []},
                "REPEATED_VERIFY.json": {"rounds": []},
                "CLAIM_LEDGER.json": {"claims": []},
                "SUMMARY_COVERAGE.json": {"summary_claims": [], "negative_findings_present": True, "zombie_sections": []},
            }.items():
                _write_json(run_root / name, payload)
            _write_text(run_root / "COMMAND_LOG.jsonl", "")
            _write_text(run_root / "REPLAY.md", "# Replay\n")

            authority_file = temp / "workspace_authority.json"
            _write_json(
                authority_file,
                {
                    "generation_targets": {
                        "scorecard": {
                            "accepted_profiles": ["L2"],
                            "gate_receipt_root": str(codex_home / "state" / "gate-receipts"),
                            "closeout": str(ROOT / "scripts" / "iaw_closeout.py"),
                            "delivery_gate": str(ROOT / "scripts" / "delivery_gate.py"),
                            "summary_export": str(ROOT / "scripts" / "export_user_score_summary.py"),
                        }
                    }
                },
            )

            review_file = temp / "user-scorecard.review.json"
            scorecard_file = temp / "user-scorecard.json"
            _write_json(scorecard_file, {"gate_status": "PASS", "final_decision": "PASS"})

            manifest = {
                "run_id": run_id,
                "base_commit": _git_output(workspace, "rev-parse", "HEAD"),
                "head_commit": _git_output(workspace, "rev-parse", "HEAD"),
            }
            manifest_meta = {
                "changed_file_set_hash": "empty",
                "policy_hashes": {"workspace_authority.json": "hash"},
                "script_hashes": {"iaw_closeout.py": "hash"},
                "evidence_manifest_hash": "manifest-hash",
            }

            audit_dir = temp / "audit"
            pre_gate = audit_dir / "audit.pre-gate.json"
            pre_export = audit_dir / "audit.pre-export.json"
            post_export = audit_dir / "audit.post-export.json"
            for report in (pre_gate, pre_export, post_export):
                _write_json(report, {"status": "PASS"})

            def fake_run_step(label: str, argv: list[str], cwd: Path) -> dict[str, object]:
                if label == "prepare":
                    self.assertIn("--run-id", argv)
                    self.assertIn(run_id, argv)
                if label == "delivery_gate":
                    self.assertIn("--run-id", argv)
                    self.assertIn(run_id, argv)
                return {"label": label, "argv": argv, "returncode": 0, "stdout": f"{label} ok\n", "stderr": ""}

            def fake_report_path(phase: str) -> Path:
                mapping = {
                    "pre-gate": pre_gate,
                    "pre-export": pre_export,
                    "post-export": post_export,
                }
                return mapping[phase]

            argv = sys.argv[:]
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            try:
                sys.argv = [
                    "iaw_closeout.py",
                    "--workspace-root",
                    str(workspace),
                    "--run-id",
                    run_id,
                    "--profile",
                    "L2",
                    "--mode",
                    "verify",
                    "--review-file",
                    str(review_file),
                    "--scorecard-file",
                    str(scorecard_file),
                    "--authority-file",
                    str(authority_file),
                ]
                with patch.dict(os.environ, env, clear=False), patch.object(
                    self.module, "validate_workspace_authority_lease", return_value={"ok": True, "reasons": [], "lease": {}, "path": ""}
                ), patch.object(self.module, "_validate_manifest", return_value=([], manifest, manifest_meta)), patch.object(
                    self.module, "_validate_waivers", return_value=[]
                ), patch.object(
                    self.module, "_run_step", side_effect=fake_run_step
                ), patch.object(
                    self.module, "_report_path", side_effect=fake_report_path
                ):
                    exit_code = self.module.main()
            finally:
                sys.argv = argv

            state_receipt = codex_home / "state" / "gate-receipts" / workspace.name / f"{run_id}.json"
            mirror_receipt = run_root / "gate_receipt.json"

            self.assertEqual(exit_code, 0)
            self.assertTrue(state_receipt.exists())
            self.assertTrue(mirror_receipt.exists())
            receipt = json.loads(state_receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt["gate_status"], "PASS")
            self.assertEqual(receipt["run_id"], run_id)


if __name__ == "__main__":
    unittest.main()
