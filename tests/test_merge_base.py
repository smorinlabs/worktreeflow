"""Tests for merge_base empty list handling (B03 regression)."""

from unittest.mock import MagicMock

import pytest

from worktreeflow.wtf import BashCommandLogger, GitWorkflowManager, SafetyValidator


def _make_manager(dry_run=False):
    """Create a GitWorkflowManager with mocked repo for testing."""
    manager = object.__new__(GitWorkflowManager)
    manager.repo = MagicMock()
    manager.logger = BashCommandLogger(dry_run=dry_run)
    manager.validator = SafetyValidator()
    manager.dry_run = False
    manager.upstream_repo = "owner/repo"
    manager.fork_owner = "myuser"
    return manager


class TestSyncMainEmptyMergeBase:
    """B03 regression: sync_main must not crash on empty merge_base."""

    def test_empty_merge_base_exits(self):
        """When merge_base returns [], should sys.exit(1) not IndexError."""
        manager = _make_manager()
        base = "main"

        # Repo is clean (no uncommitted changes)
        manager.repo.is_dirty.return_value = False

        mock_upstream_ref = MagicMock()
        manager.repo.remote.return_value.refs.__getitem__ = MagicMock(return_value=mock_upstream_ref)
        manager.repo.heads.__getitem__ = MagicMock()
        manager.repo.merge_base.return_value = []  # Empty = unrelated histories
        manager.repo.iter_commits.return_value = [MagicMock()]  # Has new commits

        with pytest.raises(SystemExit) as exc_info:
            manager.sync_main(base=base)

        assert exc_info.value.code == 1

    def test_valid_merge_base_no_exit(self):
        """When merge_base returns a valid commit, should not exit."""
        manager = _make_manager()
        base = "main"

        # Repo is clean
        manager.repo.is_dirty.return_value = False

        mock_commit = MagicMock()
        mock_upstream_ref = MagicMock()
        manager.repo.remote.return_value.refs.__getitem__ = MagicMock(return_value=mock_upstream_ref)
        manager.repo.heads.__getitem__ = MagicMock()
        manager.repo.head.commit = mock_commit
        manager.repo.merge_base.return_value = [mock_commit]  # Same commit = ff possible
        manager.repo.iter_commits.return_value = [MagicMock()]  # Has new commits
        manager.repo.remote.return_value.push = MagicMock()

        # Should not raise SystemExit
        manager.sync_main(base=base)


class TestZeroFfsyncEmptyMergeBase:
    """B03 regression: zero_ffsync must not crash on empty merge_base."""

    def test_empty_merge_base_exits(self):
        """When merge_base returns [], should sys.exit(1) not IndexError."""
        manager = _make_manager()
        base = "main"

        manager.repo.remote.return_value.fetch = MagicMock()
        mock_origin_ref = MagicMock()
        mock_upstream_ref = MagicMock()

        # Make refs indexable
        def get_ref(name):
            remote = MagicMock()
            remote.refs.__getitem__ = MagicMock(
                side_effect=lambda b: mock_origin_ref if "origin" in str(remote) else mock_upstream_ref
            )
            remote.fetch = MagicMock()
            return remote

        origin_remote = MagicMock()
        origin_remote.refs.__getitem__ = MagicMock(return_value=mock_origin_ref)
        origin_remote.fetch = MagicMock()

        upstream_remote = MagicMock()
        upstream_remote.refs.__getitem__ = MagicMock(return_value=mock_upstream_ref)
        upstream_remote.fetch = MagicMock()

        def remote_side_effect(name):
            if name == "origin":
                return origin_remote
            return upstream_remote

        manager.repo.remote.side_effect = remote_side_effect
        manager.repo.merge_base.return_value = []  # Empty = unrelated histories

        # Check for unpushed commits — simulate no local branch
        manager.repo.heads = {}

        with pytest.raises(SystemExit) as exc_info:
            manager.zero_ffsync(base=base)

        assert exc_info.value.code == 1
