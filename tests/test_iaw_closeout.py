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


def _write_passing_mission_artifacts(run_root: Path, run_id: str) -> None:
    _write_json(
        run_root / "MISSION_FRAME.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "parent_domain": "governance_closeout",
            "workstream": "policy_and_evidence_enforcement",
            "parent_objective": "Keep closeout aligned with repo-owned authority.",
            "why_this_task_exists": "test fixture",
            "this_turn_goal": "test fixture",
            "target_state": "PASS or BLOCKED with evidence.",
            "done_when_evidence": ["checker evidence exists"],
            "closeout_authority": {
                "authority_kind": "tests_reports_receipt_checker",
                "evidence_refs": ["tests/test_iaw_closeout.py", ".agent-runs/" + run_id + "/EVIDENCE_MANIFEST.json"],
            },
            "refresh_policy": "Refresh only impacted authoritative artifacts.",
        },
    )
    _write_json(
        run_root / "ARTIFACT_REFRESH_MANIFEST.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "refresh_policy": "impacted_authoritative_artifacts_only",
            "impacted_artifacts": [],
        },
    )
    _write_json(
        run_root / "MISSION_CLOSEOUT.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "status": "PASS",
            "parent_objective_alignment": "Aligned",
            "updated_artifacts": [],
            "waived_items": [],
            "blocked_items": [],
            "residual_risk": [],
            "authoritative_evidence": ["tests/test_iaw_closeout.py"],
        },
    )


class IAWCloseoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_build_receipt_encodes_release_mode_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            workspace = temp / "workspace"
            workspace.mkdir(parents=True)
            authority = {
                "generation_targets": {
                    "scorecard": {
                        "receipt_state_root": str(temp / "codex-home" / "state" / "iaw"),
                    }
                }
            }

            receipt = self.module._build_receipt(
                authority=authority,
                workspace_root=workspace.resolve(),
                run_id="run-release",
                profile="L4",
                mode="release",
                manifest={"base_commit": "base", "head_commit": "head"},
                manifest_meta={
                    "changed_files": ["tracked.txt"],
                    "changed_file_set_hash": "set-hash",
                    "changed_file_content_hash": "content-hash",
                    "policy_hashes": {"workspace_authority.json": "policy-hash"},
                    "script_hashes": {"iaw_closeout.py": "script-hash"},
                    "evidence_manifest_hash": "manifest-hash",
                },
                gate_status="PASS",
                scorecard_ref=workspace / "reports" / "user-scorecard.json",
                score_layer_ref=workspace / "reports" / "score-layer.unified-phase.json",
                audit_refs={},
                summary_ref=workspace / "SUMMARY.md",
                preflight_reasons=[],
                step_failures=[],
            )

        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["signature_policy"]["policy_id"], "scorecard-gate-receipt-v1.3")
        self.assertEqual(receipt["authority_layer"]["kind"], "signed_gate_receipt")
        self.assertEqual(receipt["authority_layer"]["state_root"], str(temp / "codex-home" / "state" / "iaw" / "gate-receipts"))
        self.assertEqual(receipt["release_semantics"]["scope"], "release")
        self.assertTrue(receipt["release_semantics"]["release_mode"])
        self.assertTrue(receipt["release_semantics"]["release_scope_authoritative"])
        self.assertTrue(receipt["release_semantics"]["release_ready"])
        self.assertEqual(receipt["changed_file_content_hash"], "content-hash")
        self.assertEqual(receipt["evidence_binding"]["changed_file_count"], 1)
        self.assertEqual(receipt["workspace_identity"]["codex_project_id"], workspace.name)
        self.assertTrue(receipt.get("signature"))

    def test_run_step_replaces_non_utf8_output(self) -> None:
        class Completed:
            returncode = 0
            stdout = "ok"
            stderr = ""

        with patch.object(self.module.subprocess, "run", return_value=Completed()) as run:
            result = self.module._run_step("export_summary", [sys.executable, "-c", "print('ok')"], ROOT)

        self.assertEqual(result["stdout"], "ok")
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_configure_console_encoding_sets_replace_errors(self) -> None:
        class Stream:
            def __init__(self) -> None:
                self.kwargs: dict[str, object] = {}

            def reconfigure(self, **kwargs: object) -> None:
                self.kwargs.update(kwargs)

        stdout = Stream()
        stderr = Stream()
        with patch.object(self.module.sys, "stdout", stdout), patch.object(self.module.sys, "stderr", stderr):
            self.module._configure_console_encoding()

        self.assertEqual(stdout.kwargs["errors"], "replace")
        self.assertEqual(stderr.kwargs["errors"], "replace")

    def test_validate_profile_artifacts_requires_convention_lock_for_l2(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            run_root = workspace / ".agent-runs" / "run-l2"
            run_root.mkdir(parents=True)
            (workspace / "SUMMARY.md").write_text("# Summary\n", encoding="utf-8")
            for name in (
                "WORKORDER.json",
                "PLAN.json",
                "TASK_TREE.json",
                "EVIDENCE_MANIFEST.json",
                "COMMAND_LOG.jsonl",
                "WAIVERS.json",
                "REPEATED_VERIFY.json",
                "CLAIM_LEDGER.json",
                "SUMMARY_COVERAGE.json",
                "SLOP_LEDGER.json",
                "REPLAY.md",
            ):
                (run_root / name).write_text("{}\n", encoding="utf-8")

            reasons = self.module._validate_profile_artifacts(self.module._artifact_paths(workspace, "run-l2"), "L2")

        self.assertIn("required run artifact is missing for L2: CONVENTION_LOCK.json", reasons)

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
                "CONVENTION_LOCK.json": {"schema_version": 1, "locked_terms": []},
                "EVIDENCE_MANIFEST.json": {"schema_version": 1},
                "WAIVERS.json": {"waivers": []},
                "REPEATED_VERIFY.json": {"rounds": []},
                "CLAIM_LEDGER.json": {"claims": []},
                "SUMMARY_COVERAGE.json": {"summary_claims": [], "negative_findings_present": True, "zombie_sections": []},
                "SLOP_LEDGER.json": {"schema_version": 1, "run_id": run_id, "status": "PASS", "entries": [], "status_summary": {"blockers": 0, "warnings": 0, "fixed": 0}},
            }.items():
                _write_json(run_root / name, payload)
            _write_passing_mission_artifacts(run_root, run_id)
            _write_text(run_root / "COMMAND_LOG.jsonl", "")
            _write_text(run_root / "REPLAY.md", "# Replay\n")

            authority_file = temp / "workspace_authority.json"
            _write_json(
                authority_file,
                {
                    "generation_targets": {
                        "scorecard": {
                            "accepted_profiles": ["L2"],
                            "receipt_state_root": str(codex_home / "state" / "iaw"),
                            "closeout": str(ROOT / "scripts" / "iaw_closeout.py"),
                            "delivery_gate": str(ROOT / "scripts" / "delivery_gate.py"),
                            "summary_export": str(ROOT / "scripts" / "export_user_score_summary.py"),
                            "score_layer": str(ROOT / "scripts" / "run_score_layer.py"),
                            "score_layer_report": str(temp / "reports" / "score-layer.unified-phase.json"),
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
                "changed_files": ["README.md"],
                "changed_file_set_hash": "empty",
                "changed_file_content_hash": "content-hash",
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
                if label == "score_layer":
                    self.assertIn("run_score_layer.py", argv[1])
                    _write_json(temp / "reports" / "score-layer.unified-phase.json", {"status": "PASS"})
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

            state_receipt = codex_home / "state" / "iaw" / "gate-receipts" / workspace.name / f"{run_id}.json"
            mirror_receipt = run_root / "gate_receipt.json"

            self.assertEqual(exit_code, 0)
            self.assertTrue(state_receipt.exists())
            self.assertTrue(mirror_receipt.exists())
            receipt = json.loads(state_receipt.read_text(encoding="utf-8"))
            self.assertEqual(receipt["gate_status"], "PASS")
            self.assertTrue(str(receipt["score_layer_ref"]).endswith("score-layer.unified-phase.json"))
            self.assertEqual(receipt["run_id"], run_id)
            self.assertEqual(receipt["schema_version"], 2)
            self.assertEqual(receipt["signature_policy"]["policy_id"], "scorecard-gate-receipt-v1.3")
            self.assertEqual(receipt["authority_layer"]["state_root"], str(codex_home / "state" / "iaw" / "gate-receipts"))
            self.assertEqual(receipt["authority_layer"]["state_path"], str(state_receipt))
            self.assertEqual(receipt["authority_layer"]["mirror_path"], str(mirror_receipt))
            self.assertEqual(receipt["workspace_identity"]["workspace_root_realpath"], str(workspace.resolve()))

    def test_score_layer_warn_does_not_block_closeout(self) -> None:
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

            run_id = "run-warn"
            run_root = workspace / ".agent-runs" / run_id
            for name, payload in {
                "WORKORDER.json": {"schema_version": 1},
                "PLAN.json": {"plan": []},
                "TASK_TREE.json": {"tasks": []},
                "CONVENTION_LOCK.json": {"schema_version": 1, "locked_terms": []},
                "EVIDENCE_MANIFEST.json": {"schema_version": 1},
                "WAIVERS.json": {"waivers": []},
                "REPEATED_VERIFY.json": {"rounds": []},
                "CLAIM_LEDGER.json": {"claims": []},
                "SUMMARY_COVERAGE.json": {"summary_claims": [], "negative_findings_present": True, "zombie_sections": []},
                "SLOP_LEDGER.json": {"schema_version": 1, "run_id": run_id, "status": "PASS", "entries": [], "status_summary": {"blockers": 0, "warnings": 0, "fixed": 0}},
            }.items():
                _write_json(run_root / name, payload)
            _write_passing_mission_artifacts(run_root, run_id)
            _write_text(run_root / "COMMAND_LOG.jsonl", "")
            _write_text(run_root / "REPLAY.md", "# Replay\n")

            authority_file = temp / "workspace_authority.json"
            _write_json(
                authority_file,
                {
                    "generation_targets": {
                        "scorecard": {
                            "accepted_profiles": ["L2"],
                            "receipt_state_root": str(codex_home / "state" / "iaw"),
                            "closeout": str(ROOT / "scripts" / "iaw_closeout.py"),
                            "delivery_gate": str(ROOT / "scripts" / "delivery_gate.py"),
                            "summary_export": str(ROOT / "scripts" / "export_user_score_summary.py"),
                            "score_layer": str(ROOT / "scripts" / "run_score_layer.py"),
                            "score_layer_report": str(temp / "reports" / "score-layer.unified-phase.json"),
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
                "changed_files": ["README.md"],
                "changed_file_set_hash": "empty",
                "changed_file_content_hash": "content-hash",
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
                if label == "score_layer":
                    _write_json(temp / "reports" / "score-layer.unified-phase.json", {"status": "WARN"})
                    return {"label": label, "argv": argv, "returncode": 1, "stdout": "score_layer warn\n", "stderr": ""}
                return {"label": label, "argv": argv, "returncode": 0, "stdout": f"{label} ok\n", "stderr": ""}

            def fake_report_path(phase: str) -> Path:
                mapping = {"pre-gate": pre_gate, "pre-export": pre_export, "post-export": post_export}
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

            state_receipt = codex_home / "state" / "iaw" / "gate-receipts" / workspace.name / f"{run_id}.json"
            receipt = json.loads(state_receipt.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["gate_status"], "PASS")
        self.assertEqual(receipt["workspace_identity"]["codex_project_id"], workspace.name)
        self.assertEqual(receipt["evidence_binding"]["changed_file_content_hash"], "content-hash")
        self.assertEqual(receipt["release_semantics"]["scope"], "verification")
        self.assertFalse(receipt["release_semantics"]["release_mode"])
        self.assertFalse(receipt["release_semantics"]["release_scope_authoritative"])
        self.assertFalse(receipt["release_semantics"]["release_ready"])
        self.assertTrue(receipt.get("signature"))

    def test_save_receipt_uses_atomic_write_for_state_and_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            workspace = temp / "workspace"
            workspace.mkdir(parents=True)
            authority = {
                "generation_targets": {
                    "scorecard": {
                        "receipt_state_root": str(temp / "codex-home" / "state" / "iaw"),
                    }
                }
            }
            receipt = {"schema_version": 2, "run_id": "run-atomic"}

            with patch.object(self.module, "atomic_save_json") as atomic_save_json:
                state_path, mirror_path = self.module._save_receipt(authority, workspace.resolve(), "run-atomic", receipt)

        self.assertEqual(state_path, temp / "codex-home" / "state" / "iaw" / "gate-receipts" / workspace.name / "run-atomic.json")
        self.assertEqual(mirror_path, workspace / ".agent-runs" / "run-atomic" / "gate_receipt.json")
        self.assertEqual(atomic_save_json.call_count, 2)
        self.assertEqual(atomic_save_json.call_args_list[0].args[0], state_path)
        self.assertEqual(atomic_save_json.call_args_list[0].args[1], receipt)
        self.assertEqual(atomic_save_json.call_args_list[1].args[0], mirror_path)
        self.assertEqual(atomic_save_json.call_args_list[1].args[1], receipt)

    def test_gate_receipts_root_uses_receipt_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            authority = {
                "generation_targets": {
                    "scorecard": {
                        "receipt_state_root": str(temp / "iaw-home"),
                    }
                }
            }

            resolved = self.module.gate_receipts_root(authority)

        self.assertEqual(resolved, temp / "iaw-home" / "gate-receipts")

    def test_gate_receipts_root_falls_back_to_codex_home_state_iaw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            env = os.environ.copy()
            env["CODEX_HOME"] = str(temp / "codex-home")
            with patch.dict(os.environ, env, clear=False):
                resolved = self.module.gate_receipts_root({})

        self.assertEqual(resolved, temp / "codex-home" / "state" / "iaw" / "gate-receipts")

    def test_gate_receipts_root_falls_back_to_home_codex_state_iaw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            original_codex_home = self.module.gate_receipts_root.__globals__["codex_home"]
            try:
                self.module.gate_receipts_root.__globals__["codex_home"] = lambda: temp / "home" / ".codex"
                resolved = self.module.gate_receipts_root({})
            finally:
                self.module.gate_receipts_root.__globals__["codex_home"] = original_codex_home

        self.assertEqual(resolved, temp / "home" / ".codex" / "state" / "iaw" / "gate-receipts")

    def test_verify_mode_creates_hmac_key_and_writes_blocked_receipt_under_new_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            codex_home = temp / "codex-home"
            workspace = temp / "workspace"
            workspace.mkdir(parents=True)
            authority_file = temp / "workspace_authority.json"
            _write_json(
                authority_file,
                {
                    "generation_targets": {
                        "scorecard": {
                            "accepted_profiles": ["L2"],
                            "receipt_state_root": str(codex_home / "state" / "iaw"),
                            "closeout": str(ROOT / "scripts" / "iaw_closeout.py"),
                            "delivery_gate": str(ROOT / "scripts" / "delivery_gate.py"),
                            "summary_export": str(ROOT / "scripts" / "export_user_score_summary.py"),
                            "score_layer": str(ROOT / "scripts" / "run_score_layer.py"),
                            "score_layer_report": str(temp / "reports" / "score-layer.unified-phase.json"),
                        }
                    }
                },
            )
            env = os.environ.copy()
            env["CODEX_HOME"] = str(codex_home)
            argv = sys.argv[:]
            try:
                sys.argv = [
                    "iaw_closeout.py",
                    "--workspace-root",
                    str(workspace),
                    "--run-id",
                    "run-blocked",
                    "--profile",
                    "L2",
                    "--mode",
                    "verify",
                    "--authority-file",
                    str(authority_file),
                ]
                with patch.dict(os.environ, env, clear=False), patch.object(
                    self.module, "validate_workspace_authority_lease", return_value={"ok": True, "reasons": [], "lease": {}, "path": ""}
                ), patch.object(self.module, "_validate_profile_artifacts", return_value=["missing summary"]), patch.object(
                    self.module, "_validate_manifest", return_value=([], {"base_commit": "base", "head_commit": "head"}, {"changed_files": [], "changed_file_set_hash": "set-hash", "changed_file_content_hash": "content-hash", "policy_hashes": {}, "script_hashes": {}, "evidence_manifest_hash": "manifest-hash"})
                ), patch.object(
                    self.module, "_validate_waivers", return_value=[]
                ):
                    exit_code = self.module.main()
            finally:
                sys.argv = argv

            state_receipt = codex_home / "state" / "iaw" / "gate-receipts" / workspace.name / "run-blocked.json"
            receipt = json.loads(state_receipt.read_text(encoding="utf-8"))
            key_exists = (codex_home / "state" / "iaw" / "truth-hmac.key").exists()

        self.assertEqual(exit_code, 2)
        self.assertTrue(key_exists)
        self.assertEqual(receipt["gate_status"], "BLOCKED")

    def test_release_mode_blocks_when_hmac_key_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            codex_home = temp / "codex-home"
            workspace = temp / "workspace"
            workspace.mkdir(parents=True)
            authority_file = temp / "workspace_authority.json"
            _write_json(
                authority_file,
                {
                    "generation_targets": {
                        "scorecard": {
                            "accepted_profiles": ["L4"],
                            "receipt_state_root": str(codex_home / "state" / "iaw"),
                            "closeout": str(ROOT / "scripts" / "iaw_closeout.py"),
                            "delivery_gate": str(ROOT / "scripts" / "delivery_gate.py"),
                            "summary_export": str(ROOT / "scripts" / "export_user_score_summary.py"),
                            "score_layer": str(ROOT / "scripts" / "run_score_layer.py"),
                            "score_layer_report": str(temp / "reports" / "score-layer.unified-phase.json"),
                        }
                    }
                },
            )

            review_file = temp / "user-scorecard.review.json"
            scorecard_file = temp / "user-scorecard.json"
            _write_json(scorecard_file, {"gate_status": "PASS", "final_decision": "PASS"})
            audit_dir = temp / "audit"
            pre_gate = audit_dir / "audit.pre-gate.json"
            pre_export = audit_dir / "audit.pre-export.json"
            post_export = audit_dir / "audit.post-export.json"
            for report in (pre_gate, pre_export, post_export):
                _write_json(report, {"status": "PASS"})

            def fake_run_step(label: str, argv: list[str], cwd: Path) -> dict[str, object]:
                return {"label": label, "argv": argv, "returncode": 0, "stdout": f"{label} ok\n", "stderr": ""}

            def fake_report_path(phase: str) -> Path:
                mapping = {"pre-gate": pre_gate, "pre-export": pre_export, "post-export": post_export}
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
                    "run-release-missing-key",
                    "--profile",
                    "L4",
                    "--mode",
                    "release",
                    "--review-file",
                    str(review_file),
                    "--scorecard-file",
                    str(scorecard_file),
                    "--authority-file",
                    str(authority_file),
                ]
                with patch.dict(os.environ, env, clear=False), patch.object(
                    self.module, "validate_workspace_authority_lease", return_value={"ok": True, "reasons": [], "lease": {}, "path": ""}
                ), patch.object(
                    self.module, "_validate_profile_artifacts", return_value=[]
                ), patch.object(
                    self.module, "_validate_manifest", return_value=([], {"base_commit": "base", "head_commit": "head"}, {"changed_files": [], "changed_file_set_hash": "set-hash", "changed_file_content_hash": "content-hash", "policy_hashes": {}, "script_hashes": {}, "evidence_manifest_hash": "manifest-hash"})
                ), patch.object(
                    self.module, "_validate_waivers", return_value=[]
                ), patch.object(
                    self.module, "_run_step", side_effect=fake_run_step
                ), patch.object(
                    self.module, "_report_path", side_effect=fake_report_path
                ):
                    exit_code = self.module.main()
            finally:
                sys.argv = argv
            key_exists = (codex_home / "state" / "iaw" / "truth-hmac.key").exists()
            receipt_exists = (codex_home / "state" / "iaw" / "gate-receipts" / workspace.name / "run-release-missing-key.json").exists()

        self.assertEqual(exit_code, 2)
        self.assertFalse(key_exists)
        self.assertFalse(receipt_exists)


if __name__ == "__main__":
    unittest.main()
