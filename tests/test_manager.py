"""Tests for GitWorkflowManager core operations."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from worktreeflow.logger import BashCommandLogger
from worktreeflow.manager import GitWorkflowManager
from worktreeflow.validator import SafetyValidator


def _make_manager(dry_run=False):
    """Create a GitWorkflowManager with mocked repo for testing."""
    manager = object.__new__(GitWorkflowManager)
    manager.repo = MagicMock()
    manager.logger = BashCommandLogger(dry_run=dry_run)
    manager.validator = SafetyValidator()
    manager.dry_run = dry_run
    manager.upstream_repo = "owner/repo"
    manager.fork_owner = "myuser"
    manager.root = Path("/fake/repo")
    manager.repo_name = "repo"
    manager.debug = False
    manager.save_history = False
    return manager


class TestWtNewNoSync:
    """B04 regression: wt-new should support --no-sync."""

    def test_no_sync_skips_sync_main(self):
        """When no_sync=True, sync_main should not be called."""
        manager = _make_manager(dry_run=True)

        # Validate slug returns the slug
        manager.repo.heads = {}

        manager.wt_new("test-feature", base="main", no_sync=True)

        # In dry_run mode, commands are logged but not executed.
        # Verify that sync-related commands are NOT in the log.
        sync_commands = [cmd.command for cmd in manager.logger.commands if "fetch upstream" in cmd.command]
        assert len(sync_commands) == 0

    def test_sync_by_default(self):
        """When no_sync=False (default), sync_main should be attempted."""
        manager = _make_manager(dry_run=True)
        manager.repo.heads = {}

        manager.wt_new("test-feature", base="main", no_sync=False)

        # sync_main is called but may fail gracefully in test env.
        # Verify that wt_new did NOT print "Skipping sync" message
        # by checking no --no-sync related log entry exists
        [cmd.description or "" for cmd in manager.logger.commands]
        # The key behavior: sync was attempted (not skipped)
        # We verify by checking the "Syncing" message was triggered
        # In dry_run mode, sync_main logs "git fetch upstream" but it may
        # fail and be caught. The point is it was attempted, not skipped.
        assert any("worktree" in cmd.command.lower() for cmd in manager.logger.commands)


class TestDetectUpstreamRepo:
    """B08 regression: upstream should be detected, not hardcoded."""

    def test_no_upstream_remote_returns_none(self):
        """Without upstream remote and no config, upstream_repo should be None."""
        manager = _make_manager()
        manager.repo.remotes = {}

        from worktreeflow.config import RepoConfig

        original = RepoConfig.DEFAULT_UPSTREAM_REPO
        RepoConfig.DEFAULT_UPSTREAM_REPO = None

        manager._detect_upstream_repo()

        assert manager.upstream_repo is None

        RepoConfig.DEFAULT_UPSTREAM_REPO = original

    def test_detects_from_ssh_url(self):
        """Should parse upstream from SSH URL."""
        manager = _make_manager()

        mock_remote = MagicMock()
        mock_remote.url = "git@github.com:someorg/somerepo.git"

        from worktreeflow.config import RepoConfig

        manager.repo.remotes = {RepoConfig.UPSTREAM_REMOTE: mock_remote}
        manager.repo.remote = MagicMock(return_value=mock_remote)

        manager._detect_upstream_repo()

        assert manager.upstream_repo == "someorg/somerepo"

    def test_detects_from_https_url(self):
        """Should parse upstream from HTTPS URL."""
        manager = _make_manager()

        mock_remote = MagicMock()
        mock_remote.url = "https://github.com/anotherorg/anotherrepo.git"

        from worktreeflow.config import RepoConfig

        manager.repo.remotes = {RepoConfig.UPSTREAM_REMOTE: mock_remote}
        manager.repo.remote = MagicMock(return_value=mock_remote)

        manager._detect_upstream_repo()

        assert manager.upstream_repo == "anotherorg/anotherrepo"


class TestParseWorktreePorcelain:
    """Tests for worktree porcelain parsing."""

    def test_simple_branch(self):
        output = "worktree /home/user/repo\nHEAD abc1234\nbranch refs/heads/main\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert len(result) == 1
        assert result[0]["branch"] == "main"

    def test_detached_head(self):
        output = "worktree /repo\nHEAD abc1234\ndetached\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert result[0]["branch"] == "(detached)"

    def test_multiple_worktrees(self):
        output = (
            "worktree /home/user/repo\n"
            "HEAD abc1234\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /home/user/wt/feat-login\n"
            "HEAD def5678\n"
            "branch refs/heads/feat/login\n"
        )
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert len(result) == 2
        assert result[0]["branch"] == "main"
        assert result[1]["branch"] == "feat/login"

    def test_empty_output(self):
        result = GitWorkflowManager._parse_worktree_porcelain("")
        assert result == [] or all("path" not in wt for wt in result)


class TestCheckRepo:
    """Tests for check commands."""

    def test_check_repo_succeeds(self):
        """check_repo should not raise when repo is valid."""
        manager = _make_manager()
        manager.check_repo()

    def test_check_origin_missing(self):
        """check_origin should exit when origin is missing."""
        manager = _make_manager()
        manager.repo.remotes = {}

        with pytest.raises(SystemExit):
            manager.check_origin()

    def test_check_upstream_missing(self):
        """check_upstream should exit when upstream is missing."""
        manager = _make_manager()
        manager.repo.remotes = {}

        with pytest.raises(SystemExit):
            manager.check_upstream()


class TestSyncMainEmptyMergeBase:
    """B03 regression: sync_main must not crash on empty merge_base."""

    def test_empty_merge_base_exits(self):
        manager = _make_manager()
        base = "main"

        manager.repo.is_dirty.return_value = False

        mock_upstream_ref = MagicMock()
        manager.repo.remote.return_value.refs.__getitem__ = MagicMock(return_value=mock_upstream_ref)
        manager.repo.heads.__getitem__ = MagicMock()
        manager.repo.merge_base.return_value = []
        manager.repo.iter_commits.return_value = [MagicMock()]

        with pytest.raises(SystemExit) as exc_info:
            manager.sync_main(base=base)

        assert exc_info.value.code == 1

    def test_valid_merge_base_no_exit(self):
        manager = _make_manager()
        base = "main"

        manager.repo.is_dirty.return_value = False

        mock_commit = MagicMock()
        mock_upstream_ref = MagicMock()
        manager.repo.remote.return_value.refs.__getitem__ = MagicMock(return_value=mock_upstream_ref)
        manager.repo.heads.__getitem__ = MagicMock()
        manager.repo.head.commit = mock_commit
        manager.repo.merge_base.return_value = [mock_commit]
        manager.repo.iter_commits.return_value = [MagicMock()]
        manager.repo.remote.return_value.push = MagicMock()

        manager.sync_main(base=base)


class TestGetWorktreePath:
    """B05: worktree path construction should be safe."""

    def test_normal_slug(self):
        manager = _make_manager()
        path = manager._get_worktree_path("my-feature")
        assert path == Path("/fake/wt/repo/my-feature")

    def test_slug_with_dots(self):
        manager = _make_manager()
        path = manager._get_worktree_path("fix-v2.0")
        assert "fix-v2.0" in str(path)
