"""Tests for WorktreeFlowError pattern and CLI error handling."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from worktreeflow.config import RepoSettings
from worktreeflow.errors import WorktreeFlowError
from worktreeflow.logger import BashCommandLogger
from worktreeflow.manager import GitWorkflowManager
from worktreeflow.validator import SafetyValidator


def _make_manager(dry_run=False, config=None):
    """Create a GitWorkflowManager with mocked repo for testing."""
    manager = object.__new__(GitWorkflowManager)
    manager.repo = MagicMock()
    manager.logger = BashCommandLogger(dry_run=dry_run)
    manager.validator = SafetyValidator()
    manager.config = config or RepoSettings()
    manager.dry_run = dry_run
    manager.upstream_repo = "owner/repo"
    manager.fork_owner = "myuser"
    manager.root = Path("/fake/repo")
    manager.repo_name = "repo"
    manager.debug = False
    manager.save_history = False
    manager.quiet = False
    manager.verbose = False
    return manager


class TestWorktreeFlowError:
    """Test that WorktreeFlowError is raised instead of sys.exit."""

    def test_check_origin_raises_error(self):
        manager = _make_manager()
        manager.repo.remotes = {}
        with pytest.raises(WorktreeFlowError, match="Missing 'origin' remote"):
            manager.check_origin()

    def test_check_upstream_raises_error(self):
        manager = _make_manager()
        manager.repo.remotes = {}
        with pytest.raises(WorktreeFlowError, match="Missing 'upstream' remote"):
            manager.check_upstream()

    def test_upstream_add_no_repo_raises(self):
        manager = _make_manager()
        manager.upstream_repo = None
        with pytest.raises(WorktreeFlowError, match="No upstream repo specified"):
            manager.upstream_add()

    def test_fork_setup_no_gh_raises(self):
        manager = _make_manager()
        with patch("worktreeflow.manager.shutil.which", return_value=None), \
             pytest.raises(WorktreeFlowError, match="GitHub CLI required"):
            manager.fork_setup()

    def test_fork_setup_no_upstream_raises(self):
        manager = _make_manager()
        manager.upstream_repo = None
        with patch("worktreeflow.manager.shutil.which", return_value="/usr/bin/gh"), \
             pytest.raises(WorktreeFlowError, match="No upstream repo configured"):
            manager.fork_setup()

    def test_wt_publish_no_worktree_raises(self):
        manager = _make_manager()
        # active branch is something else
        manager.repo.active_branch.name = "main"
        with pytest.raises(WorktreeFlowError, match="Worktree not found"):
            manager.wt_publish("nonexistent")

    def test_wt_pr_no_fork_owner_raises(self):
        manager = _make_manager()
        manager.fork_owner = None
        with pytest.raises(WorktreeFlowError, match="Could not determine fork owner"):
            manager.wt_pr("test-feature")

    def test_wt_pr_no_upstream_raises(self):
        manager = _make_manager()
        manager.upstream_repo = None
        with pytest.raises(WorktreeFlowError, match="No upstream repo configured"):
            manager.wt_pr("test-feature")

    def test_wt_pr_no_gh_raises(self):
        manager = _make_manager()
        with patch("worktreeflow.manager.shutil.which", return_value=None), \
             pytest.raises(WorktreeFlowError, match="GitHub CLI required"):
            manager.wt_pr("test-feature")

    def test_wt_update_no_worktree_raises(self):
        manager = _make_manager()
        manager.repo.active_branch.name = "main"
        with pytest.raises(WorktreeFlowError, match="Worktree not found"):
            manager.wt_update("nonexistent")

    def test_wt_status_no_worktree_raises(self):
        manager = _make_manager()
        with pytest.raises(WorktreeFlowError, match="Worktree not found"):
            manager.wt_status("nonexistent")

    def test_sync_main_force_requires_confirm(self):
        manager = _make_manager()
        manager.repo.is_dirty.return_value = False
        with pytest.raises(WorktreeFlowError, match="--confirm"):
            manager.sync_main_force(confirm=False)

    def test_sync_main_force_dirty_no_force_raises(self):
        manager = _make_manager()
        manager.repo.is_dirty.return_value = True
        manager.repo.active_branch.name = "main"
        with pytest.raises(WorktreeFlowError, match="uncommitted changes"):
            manager.sync_main_force(confirm=True, force=False)


class TestWtCleanErrors:
    """Test wt-clean error paths."""

    def test_uncommitted_changes_without_force(self):
        manager = _make_manager()
        manager._get_worktree_path("test")

        # Simulate worktree exists with uncommitted changes
        with patch.object(Path, "exists", return_value=True):
            result_mock = MagicMock()
            result_mock.returncode = 0
            result_mock.stdout = "M some_file.py"
            manager.logger.execute = MagicMock(return_value=result_mock)

            with pytest.raises(WorktreeFlowError, match="uncommitted changes"):
                manager.wt_clean("test", wt_force=False)

    def test_inside_worktree_raises(self):
        manager = _make_manager()
        worktree_path = manager._get_worktree_path("test")

        # Simulate being inside the worktree
        with patch.object(Path, "exists", return_value=True), \
             patch("worktreeflow.manager.Path.cwd", return_value=worktree_path):
            result_mock = MagicMock()
            result_mock.returncode = 1
            result_mock.stdout = ""
            manager.logger.execute = MagicMock(return_value=result_mock)

            with pytest.raises(WorktreeFlowError, match="Cannot remove worktree while inside"):
                manager.wt_clean("test", confirm=True)


class TestWtUpdateErrors:
    """Test wt-update error paths."""

    def test_uncommitted_changes_without_stash(self):
        manager = _make_manager()
        manager.repo.active_branch.name = "feat/test"

        # Fetch upstream succeeds, behind/ahead checks succeed
        result_behind = MagicMock(stdout="3\n", returncode=0)
        result_ahead = MagicMock(stdout="1\n", returncode=0)
        result_status = MagicMock(stdout="M dirty_file.py\n", returncode=0)

        call_count = [0]
        def mock_execute(cmd, desc=None, check=True, capture_output=True):
            call_count[0] += 1
            if "rev-list --count" in cmd and "HEAD..upstream" in cmd:
                return result_behind
            if "rev-list --count" in cmd and "upstream" in cmd and "..HEAD" in cmd:
                return result_ahead
            if "status --porcelain" in cmd:
                return result_status
            return MagicMock(stdout="", returncode=0)

        manager.logger.execute = mock_execute
        with pytest.raises(WorktreeFlowError, match="uncommitted changes"):
            manager.wt_update("test", stash=False)
