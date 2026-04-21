from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "check_git_surface.py"


def _load_module():
    scripts_dir = str(ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location("check_git_surface", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load check_git_surface.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GitSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_windows_git_vs_wsl_git_drift_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True)
            with patch.object(self.module, "load_authority", return_value={"canonical_roots": {}}), patch.object(
                self.module, "canonical_repo_roots", return_value=[repo]
            ), patch.object(
                self.module, "first_existing_git_exe", return_value=Path("/mnt/c/Program Files/Git/cmd/git.exe")
            ), patch.object(
                self.module, "probe_git_scope"
            ) as probe, patch.object(
                self.module, "git_lfs_available", side_effect=[{"available": True}, {"available": True}]
            ), patch.object(
                self.module, "repo_git_probe", return_value={"repo_root": str(repo), "status": "present", "dirty": [], "is_sparse_checkout": False, "is_worktree": False}
            ):
                probe.side_effect = [
                    {"available": True, "lines": ["file:/home/u/.gitconfig\tcore.autocrlf=input"], "map": {"core.autocrlf": "input"}},
                    {"available": False, "lines": [], "map": {}},
                    {"available": True, "lines": ["file:C:/Users/a/.gitconfig\tcore.autocrlf=true"], "map": {"core.autocrlf": "true"}},
                    {"available": False, "lines": [], "map": {}},
                ]
                report = self.module.evaluate_git_surfaces()
        self.assertEqual(report["status"], "WARN")
        self.assertTrue(report["global_drift"])

    def test_lfs_configured_on_windows_but_missing_in_wsl_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True)
            with patch.object(self.module, "load_authority", return_value={"canonical_roots": {}}), patch.object(
                self.module, "canonical_repo_roots", return_value=[repo]
            ), patch.object(
                self.module, "first_existing_git_exe", return_value=Path("/mnt/c/Program Files/Git/cmd/git.exe")
            ), patch.object(
                self.module, "probe_git_scope"
            ) as probe, patch.object(
                self.module, "git_lfs_available", side_effect=[{"available": False}, {"available": True}]
            ), patch.object(
                self.module, "repo_git_probe", return_value={"repo_root": str(repo), "status": "present", "dirty": [], "is_sparse_checkout": False, "is_worktree": False}
            ):
                probe.side_effect = [
                    {"available": True, "lines": [], "map": {}},
                    {"available": False, "lines": [], "map": {}},
                    {"available": True, "lines": ["file:C:/Users/a/.gitconfig\tfilter.lfs.clean=git-lfs clean -- %f"], "map": {"filter.lfs.clean": "git-lfs clean -- %f"}},
                    {"available": False, "lines": [], "map": {}},
                ]
                report = self.module.evaluate_git_surfaces()
        self.assertIn("Git LFS is configured but unavailable in WSL.", report["warnings"])

    def test_stale_safe_directory_is_detected(self) -> None:
        lines = ["file:/home/u/.gitconfig\tsafe.directory=/missing/repo"]
        self.assertEqual(self.module.stale_safe_directories(lines), ["/missing/repo"])

    def test_dirty_repos_are_reported_but_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True)
            repo_probe = {
                "repo_root": str(repo),
                "status": "present",
                "dirty": [" M README.md"],
                "is_sparse_checkout": False,
                "is_worktree": False,
            }
            with patch.object(self.module, "load_authority", return_value={"canonical_roots": {}}), patch.object(
                self.module, "canonical_repo_roots", return_value=[repo]
            ), patch.object(
                self.module, "first_existing_git_exe", return_value=None
            ), patch.object(
                self.module, "probe_git_scope", return_value={"available": False, "lines": [], "map": {}}
            ), patch.object(
                self.module, "git_lfs_available", return_value={"available": False}
            ), patch.object(
                self.module, "repo_git_probe", return_value=repo_probe
            ):
                report = self.module.evaluate_git_surfaces()
        self.assertEqual(report["status"], "WARN")
        self.assertEqual(report["repo_reports"][0]["dirty"], [" M README.md"])

    def test_dev_management_gitattributes_proposal_is_repo_local_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            other_repo = tmp / "other-repo"
            other_repo.mkdir()
            management_repo = tmp / "Dev-Management"
            management_repo.mkdir()
            with patch.object(self.module, "ROOT", management_repo):
                management_proposal = self.module.dev_management_gitattributes_proposal(management_repo)
                other_proposal = self.module.dev_management_gitattributes_proposal(other_repo)
        self.assertEqual(management_proposal["status"], "PROPOSED")
        self.assertEqual(other_proposal["status"], "WAIVED")

    def test_stale_worktree_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True)
            repo_probe = {
                "repo_root": str(repo),
                "status": "present",
                "dirty": [],
                "is_sparse_checkout": False,
                "is_worktree": True,
                "worktree_policy_status": "WARN",
                "branch_lock_status": "PASS",
                "active_worktree_root": str(repo / "task-worktree"),
                "canonical_repo_root": str(repo),
            }
            with patch.object(self.module, "load_authority", return_value={"canonical_roots": {}}), patch.object(
                self.module, "load_execution_surfaces", return_value={"worktree_policy": {}}
            ), patch.object(
                self.module, "canonical_repo_roots", return_value=[repo]
            ), patch.object(
                self.module, "first_existing_git_exe", return_value=None
            ), patch.object(
                self.module, "probe_git_scope", return_value={"available": False, "lines": [], "map": {}}
            ), patch.object(
                self.module, "git_lfs_available", return_value={"available": False}
            ), patch.object(
                self.module, "repo_git_probe", return_value=repo_probe
            ):
                report = self.module.evaluate_git_surfaces()
        self.assertEqual(report["status"], "WARN")

    def test_branch_lock_conflict_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True)
            repo_probe = {
                "repo_root": str(repo),
                "status": "present",
                "dirty": [],
                "is_sparse_checkout": False,
                "is_worktree": True,
                "worktree_policy_status": "PASS",
                "branch_lock_status": "BLOCKED",
                "active_worktree_root": str(repo / "task-worktree"),
                "canonical_repo_root": str(repo),
            }
            with patch.object(self.module, "load_authority", return_value={"canonical_roots": {}}), patch.object(
                self.module, "load_execution_surfaces", return_value={"worktree_policy": {}}
            ), patch.object(
                self.module, "canonical_repo_roots", return_value=[repo]
            ), patch.object(
                self.module, "first_existing_git_exe", return_value=None
            ), patch.object(
                self.module, "probe_git_scope", return_value={"available": False, "lines": [], "map": {}}
            ), patch.object(
                self.module, "git_lfs_available", return_value={"available": False}
            ), patch.object(
                self.module, "repo_git_probe", return_value=repo_probe
            ):
                report = self.module.evaluate_git_surfaces()
        self.assertEqual(report["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
