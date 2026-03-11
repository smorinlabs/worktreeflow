"""Tests for configurable branch prefix."""

from pathlib import Path
from unittest.mock import MagicMock

from worktreeflow.config import RepoSettings
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


class TestMakeBranchName:
    """Test configurable branch name prefix."""

    def test_default_prefix(self):
        manager = _make_manager()
        assert manager._make_branch_name("my-feature") == "feat/my-feature"

    def test_custom_prefix(self):
        config = RepoSettings(feature_branch_prefix="feature/")
        manager = _make_manager(config=config)
        assert manager._make_branch_name("my-feature") == "feature/my-feature"

    def test_no_slash_prefix(self):
        config = RepoSettings(feature_branch_prefix="fix-")
        manager = _make_manager(config=config)
        assert manager._make_branch_name("bug123") == "fix-bug123"

    def test_empty_prefix(self):
        config = RepoSettings(feature_branch_prefix="")
        manager = _make_manager(config=config)
        assert manager._make_branch_name("my-feature") == "my-feature"


class TestRepoSettings:
    """Test RepoSettings dataclass."""

    def test_defaults(self):
        settings = RepoSettings()
        assert settings.feature_branch_prefix == "feat/"
        assert settings.backup_branch_prefix == "backup/"
        assert settings.base_branch == "main"
        assert settings.upstream_repo is None
        assert settings.origin_remote == "origin"
        assert settings.upstream_remote == "upstream"

    def test_custom_values(self):
        settings = RepoSettings(
            feature_branch_prefix="feature/",
            base_branch="develop",
            upstream_repo="org/repo",
        )
        assert settings.feature_branch_prefix == "feature/"
        assert settings.base_branch == "develop"
        assert settings.upstream_repo == "org/repo"


class TestLoadConfigReturnsSettings:
    """Test that load_config returns a RepoSettings instance."""

    def test_load_config_returns_settings(self, tmp_path):
        from worktreeflow.config import load_config

        settings = load_config(tmp_path)
        assert isinstance(settings, RepoSettings)

    def test_load_config_none_returns_defaults(self):
        from worktreeflow.config import load_config

        settings = load_config(None)
        assert isinstance(settings, RepoSettings)
        assert settings.feature_branch_prefix == "feat/"

    def test_load_config_with_toml(self, tmp_path):
        from worktreeflow.config import RepoConfig, load_config

        config_file = tmp_path / ".worktreeflow.toml"
        config_file.write_text('[workflow]\nfeature_branch_prefix = "feature/"\n')
        settings = load_config(tmp_path)
        assert settings.feature_branch_prefix == "feature/"
        # Also verify backward compat
        assert RepoConfig.FEATURE_BRANCH_PREFIX == "feature/"

        # Reset for other tests
        RepoConfig.FEATURE_BRANCH_PREFIX = "feat/"


class TestWtNewUsesPrefix:
    """Test that wt-new uses the configured prefix."""

    def test_wt_new_dry_run_uses_custom_prefix(self):
        config = RepoSettings(feature_branch_prefix="feature/")
        manager = _make_manager(dry_run=True, config=config)
        manager.repo.heads = {}

        manager.wt_new("test-feature", base="main", no_sync=True)

        # Verify the branch name uses the custom prefix in logged commands
        worktree_cmds = [cmd.command for cmd in manager.logger.commands if "worktree add" in cmd.command]
        assert len(worktree_cmds) > 0
        assert "feature/test-feature" in worktree_cmds[0]
        assert "feat/" not in worktree_cmds[0]
