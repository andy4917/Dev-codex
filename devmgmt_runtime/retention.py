from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CLASSIFICATIONS = {
    "RETAIN_AUTHORITY",
    "RETAIN_RUNTIME",
    "RETAIN_SCRIPT",
    "RETAIN_TEST",
    "RETAIN_DOC",
    "RETAIN_CURRENT_REPORT",
    "RETAIN_EXTERNAL_EVIDENCE",
    "PRODUCT_EXCLUDED",
    "DELETE_NOW",
    "REWRITE_THEN_DELETE",
    "MANUAL_REMEDIATION",
}

RETAIN_DOC_FILES = {
    "docs/AGENT_GUARDRAILS.md",
    "docs/AI_TOOLCHAIN_USAGE.md",
    "docs/CODEX_APP_USER_SETUP.md",
    "docs/CODEX_APP_MAINTENANCE.md",
    "docs/CONTEXT7_USAGE.md",
    "docs/GLOBAL_AGENT_WORKFLOW.md",
    "docs/GLOBAL_RUNTIME_ARCHITECTURE.md",
    "docs/PREREQUISITES.md",
    "docs/PROMPT_BLOCKS.md",
    "docs/RUNBOOK.md",
    "docs/SERENA_USAGE.md",
    "docs/USER_DEV_ENVIRONMENT_BASELINE.md",
    "docs/USER_SCORECARD.md",
}
DELETE_DOC_FILES = {
    "docs/CLOSE_OUT.md",
    "docs/DEPENDENCY_INVERSION.md",
    "docs/DEVELOPMENT_ENVIRONMENT_GLOBAL_STATE.md",
    "docs/HOOKS_LEGACY_RUNTIME.md",
    "docs/LOCAL_ENVIRONMENTS.md",
    "docs/RELEASE_PLAN.md",
    "docs/ROLLBACK.md",
    "docs/SESSION_THREAD_CONTAMINATION_AUDIT.md",
    "docs/SYNCTHING.md",
    "docs/TOOLCHAIN.md",
    "docs/USER_READINESS.md",
}
DELETE_SCRIPT_FILES = {
    "scripts/audit_workspace.py",
    "scripts/check_active_config_smoke.py",
    "scripts/check_agent_instruction.py",
    "scripts/check_artifact_hygiene.py",
    "scripts/check_git_surface.py",
    "scripts/check_hook_readiness.py",
    "scripts/check_startup_workflow.py",
    "scripts/render_codex_runtime.py",
    "scripts/repair_serena_startup.py",
    "scripts/run_score_layer.py",
    "scripts/check_product_file_organization.py",
    "scripts/check_toolchain_surface.py",
    "scripts/drift_audit.py",
    "scripts/generate_closeout_v2_reports.py",
    "scripts/remove_windows_codex_policy_mirrors.py",
    "scripts/verify_migration_evidence.py",
}
DELETE_TEST_FILES = {
    "tests/test_app_thread_worktree_policy.py",
    "tests/test_artifact_hygiene.py",
    "tests/test_audit_workspace_contract.py",
    "tests/test_check_active_config_smoke.py",
    "tests/test_check_agent_instruction.py",
    "tests/test_check_hook_readiness.py",
    "tests/test_check_startup_workflow.py",
    "tests/test_check_toolchain_surface.py",
    "tests/test_git_surface.py",
    "tests/test_repair_serena_startup.py",
    "tests/test_score_layer.py",
    "tests/test_drift_audit.py",
    "tests/test_closeout_v2_reports.py",
    "tests/test_hostile_boundary_meta.py",
    "tests/test_product_file_organization.py",
    "tests/test_quarantine_hostile_audit.py",
    "tests/test_verify_migration_evidence.py",
    "tests/test_windows_codex_policy_mirror_removal.py",
}
DELETE_TOP_LEVEL = {
    "cleanup_report.json",
    "mermaid-diagram (4).png",
    "mermaid-diagram (5).png",
    "migration_manifest.json",
}
CURRENT_REPORT_FILES = {
    "reports/app-remote-access-blocker-analysis.final.json",
    "reports/app-remote-access-blocker-analysis.final.md",
    "reports/codex-app-usability-final.json",
    "reports/codex-app-usability-final.md",
    "reports/config-provenance.final.json",
    "reports/config-provenance.final.md",
    "reports/codex-app-maintenance.final.json",
    "reports/codex-app-maintenance.final.md",
    "reports/global-agent-workflow.final.json",
    "reports/global-agent-workflow.final.md",
    "reports/path-preflight.final.json",
    "reports/path-preflight.final.md",
    "reports/reference-graph.final.json",
    "reports/reference-graph.final.md",
    "reports/retention-manifest.final.json",
    "reports/retention-manifest.final.md",
    "reports/toolchain-usage.session.json",
    "reports/user-dev-environment-baseline.final.json",
    "reports/user-dev-environment-baseline.final.md",
    "reports/windows-app-local-readiness.final.json",
    "reports/user-scorecard.json",
    "reports/user-scorecard.review.json",
    "reports/workspace-dependency-surface.json",
    "reports/workspace-structure.final.json",
    "reports/workspace-structure.final.md",
}
REPORT_DELETE_PATTERNS = (
    "after-",
    "before-",
    "closeout-v2",
    "dry-run",
    "hostile",
    "plan-check",
    "post-apply",
    "pre-",
    "root-cause-removal",
    "root-removal",
    "unified-phase",
)
TEXT_EXTENSIONS = {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
PYTHON_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z0-9_\.]+)", re.MULTILINE)


def classify_relative_path(relative_path: str, *, is_dir: bool) -> dict[str, str]:
    relative = relative_path.replace("\\", "/").strip()
    if relative in {"", "."}:
        return {"classification": "RETAIN_RUNTIME", "reason": "workspace root remains active"}
    parts = tuple(Path(relative).parts)
    top_level = parts[0]

    if top_level == ".git":
        return {"classification": "PRODUCT_EXCLUDED", "reason": "git internals are outside repo-owned retention decisions"}
    if relative in DELETE_TOP_LEVEL:
        return {"classification": "DELETE_NOW", "reason": "stale top-level artifact is not part of the retained architecture"}
    if relative in {".env.example", ".envrc", ".gitignore"}:
        return {"classification": "RETAIN_RUNTIME", "reason": "repo bootstrap/runtime surface remains active"}
    if top_level in {".patch-links"}:
        return {"classification": "RETAIN_EXTERNAL_EVIDENCE", "reason": "external evidence linkage surface is retained as inert metadata"}
    if top_level in {".serena"}:
        return {"classification": "MANUAL_REMEDIATION", "reason": "Serena project metadata is retained separately from readiness and code-modification gates"}

    if top_level == "contracts":
        return {"classification": "RETAIN_AUTHORITY", "reason": "contracts remain repo-owned source-of-truth or policy modules"}

    if top_level == "devmgmt_runtime":
        return {"classification": "RETAIN_RUNTIME", "reason": "runtime library remains active"}

    if top_level == "scripts":
        if relative in DELETE_SCRIPT_FILES:
            return {"classification": "DELETE_NOW", "reason": "legacy script only supports removed closeout or mirror behavior"}
        return {"classification": "RETAIN_SCRIPT", "reason": "script remains part of the active verification or repair surface"}

    if top_level == "tests":
        if relative in DELETE_TEST_FILES:
            return {"classification": "DELETE_NOW", "reason": "legacy test encodes removed closeout or mirror behavior"}
        return {"classification": "RETAIN_TEST", "reason": "test guards the active architecture"}

    if top_level == "docs":
        if relative in DELETE_DOC_FILES:
            return {"classification": "DELETE_NOW", "reason": "stale doc describes superseded rollout or fallback behavior"}
        if relative in RETAIN_DOC_FILES:
            return {"classification": "RETAIN_DOC", "reason": "doc describes the retained final architecture or workflow"}
        return {"classification": "DELETE_NOW", "reason": "doc is outside the retained final architecture allowlist"}

    if top_level == "reports":
        if relative == "reports/generated-runtime-preview" or relative.startswith("reports/generated-runtime-preview/"):
            return {"classification": "DELETE_NOW", "reason": "generated runtime previews are decommissioned in Windows-only mode"}
        if relative in CURRENT_REPORT_FILES:
            return {"classification": "RETAIN_CURRENT_REPORT", "reason": "current final evidence report is retained"}
        if any(token in Path(relative).name for token in REPORT_DELETE_PATTERNS):
            return {"classification": "DELETE_NOW", "reason": "legacy report variant is superseded by current final evidence"}
        if relative.endswith((".json", ".md")):
            return {"classification": "DELETE_NOW", "reason": "non-final report is not retained as active evidence"}
        return {"classification": "RETAIN_CURRENT_REPORT", "reason": "current report support path is retained"}

    if top_level == "quarantine":
        if relative.endswith("MANIFEST.json") or is_dir:
            return {"classification": "RETAIN_EXTERNAL_EVIDENCE", "reason": "manifest-only inert archive remains as external evidence"}
        return {"classification": "DELETE_NOW", "reason": "quarantine payload is not retained on active repo surfaces"}

    return {"classification": "DELETE_NOW", "reason": "path is outside the retained surface allowlist"}


def build_retention_manifest(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    entries: list[dict[str, Any]] = []
    all_paths = [root, *sorted(root.rglob("*"))]
    summary: dict[str, int] = {key: 0 for key in sorted(CLASSIFICATIONS)}
    for path in all_paths:
        relative = "." if path == root else str(path.relative_to(root)).replace("\\", "/")
        classified = classify_relative_path(relative, is_dir=path.is_dir())
        classification = classified["classification"]
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"unknown retention classification for {relative}: {classification}")
        summary[classification] += 1
        entries.append(
            {
                "path": relative,
                "type": "directory" if path.is_dir() else "file",
                "classification": classification,
                "reason": classified["reason"],
            }
        )
    return {
        "repo_root": str(root),
        "entries": entries,
        "summary": summary,
        "unknown_count": 0,
    }


def _python_import_targets(relative_path: str, text: str, existing_files: set[str]) -> list[str]:
    edges: set[str] = set()
    for module_name in PYTHON_IMPORT_RE.findall(text):
        root_name = module_name.split(".", 1)[0]
        script_target = f"scripts/{root_name}.py"
        runtime_target = f"devmgmt_runtime/{module_name.replace('.', '/')}.py"
        if script_target in existing_files and script_target != relative_path:
            edges.add(script_target)
        if runtime_target in existing_files and runtime_target != relative_path:
            edges.add(runtime_target)
        root_runtime = f"devmgmt_runtime/{root_name}.py"
        if root_runtime in existing_files and root_runtime != relative_path:
            edges.add(root_runtime)
    return sorted(edges)


def build_reference_graph(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root).expanduser().resolve()
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.parts and path.suffix.lower() in TEXT_EXTENSIONS
    ]
    relative_files = [str(path.relative_to(root)).replace("\\", "/") for path in files]
    existing = set(relative_files)
    curated_targets = [
        item
        for item in relative_files
        if item.startswith(("contracts/", "docs/", "scripts/", "tests/", "reports/"))
    ]
    edges: list[dict[str, str]] = []
    for path, relative in zip(files, relative_files, strict=True):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        targets = set(_python_import_targets(relative, text, existing))
        for target in curated_targets:
            if target == relative:
                continue
            if target in text:
                targets.add(target)
            else:
                name = Path(target).name
                if name and name in text and "/" not in name:
                    targets.add(target)
        for target in sorted(targets):
            edges.append({"source": relative, "target": target})
    inbound: dict[str, int] = {item: 0 for item in relative_files}
    outbound: dict[str, int] = {item: 0 for item in relative_files}
    for edge in edges:
        outbound[edge["source"]] += 1
        inbound[edge["target"]] = inbound.get(edge["target"], 0) + 1
    nodes = [
        {
            "path": path,
            "inbound": inbound.get(path, 0),
            "outbound": outbound.get(path, 0),
        }
        for path in relative_files
    ]
    return {
        "repo_root": str(root),
        "nodes": nodes,
        "edges": edges,
    }
