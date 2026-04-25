from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_global_agent_workflow.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_global_agent_workflow", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_global_agent_workflow.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GlobalAgentWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _write_json(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _policy(self) -> dict[str, object]:
        return json.loads((ROOT / "contracts" / "global_agent_workflow_policy.json").read_text(encoding="utf-8"))

    def _workflow_doc(self) -> str:
        return (ROOT / "docs" / "GLOBAL_AGENT_WORKFLOW.md").read_text(encoding="utf-8")

    def _setup_doc(self) -> str:
        return (ROOT / "docs" / "CODEX_APP_USER_SETUP.md").read_text(encoding="utf-8")

    def _build_repo(
        self,
        root: Path,
        *,
        policy: dict[str, object] | None = None,
        workflow_doc: str | None = None,
        setup_doc: str | None = None,
    ) -> None:
        self._write_json(root / "contracts" / "global_agent_workflow_policy.json", policy or self._policy())
        self._write_text(root / "docs" / "GLOBAL_AGENT_WORKFLOW.md", workflow_doc or self._workflow_doc())
        self._write_text(root / "docs" / "CODEX_APP_USER_SETUP.md", setup_doc or self._setup_doc())

    def test_pass_when_policy_and_docs_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "PASS")

    def test_skills_as_authority_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["authority_layers"]["skills"] = "truth_authority"
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("authority_layers do not match the required workflow/evidence roles", report["blockers"])

    def test_context7_as_product_domain_source_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["authority_layers"]["context7"] = "product_domain_evidence"
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")

    def test_serena_as_external_docs_source_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["authority_layers"]["serena"] = "external_docs_evidence"
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")

    def test_domain_logic_without_domain_evidence_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["required_evidence_matrix"]["domain_business_rule"] = ["serena"]
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("domain/business logic is allowed without domain evidence", report["blockers"])

    def test_backend_auth_payment_db_migration_requires_three_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["required_evidence_matrix"]["backend_auth_payment_db_migration"] = ["serena", "context7"]
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("backend auth/payment/DB/migration is allowed without Serena + Context7 + Domain RAG", report["blockers"])

    def test_missing_app_settings_pointer_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root, setup_doc="# Codex App User Setup\n")
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")

    def test_incomplete_app_settings_pointer_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._build_repo(root, setup_doc="# Codex App User Setup\n\nAgent environment: Windows native\n")
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")

    def test_missing_fallback_disclosure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["fallback_rules"].pop("missing_domain_rag", None)
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("fallback_rules.missing_domain_rag must be declared", report["blockers"])

    def test_missing_touched_code_runtime_verification_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy.pop("touched_code_runtime_verification", None)
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("policy is missing required top-level keys: touched_code_runtime_verification", report["blockers"])

    def test_missing_touched_code_pointer_text_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            policy = self._policy()
            policy["app_settings_pointer"]["exact_text"] = "Before work, read and follow:\n"
            self._build_repo(root, policy=policy)
            report = self.module.evaluate_global_agent_workflow(root)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("policy app_settings_pointer.exact_text is missing touched-code runtime verification text", report["blockers"])


if __name__ == "__main__":
    unittest.main()
