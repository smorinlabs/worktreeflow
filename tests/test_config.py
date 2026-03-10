"""Tests for configuration loading."""

import sys
import pytest

from worktreeflow.config import RepoConfig, load_config


class TestRepoConfigDefaults:
    """Test default configuration values."""

    def test_no_hardcoded_upstream(self):
        """B08 regression: DEFAULT_UPSTREAM_REPO must not be hardcoded."""
        assert RepoConfig.DEFAULT_UPSTREAM_REPO is None or RepoConfig.DEFAULT_UPSTREAM_REPO != "humanlayer/humanlayer"

    def test_default_base_branch(self):
        assert RepoConfig.DEFAULT_BASE_BRANCH == "main"

    def test_default_feature_prefix(self):
        assert RepoConfig.FEATURE_BRANCH_PREFIX == "feat/"

    def test_default_worktree_path(self):
        assert RepoConfig.WORKTREE_BASE_PATH == "../wt"


class TestLoadConfig:
    """Test TOML config file loading."""

    def test_load_nonexistent_file(self, tmp_path):
        """Loading from a directory without config should be a no-op."""
        original_upstream = RepoConfig.DEFAULT_UPSTREAM_REPO
        load_config(tmp_path)
        assert RepoConfig.DEFAULT_UPSTREAM_REPO == original_upstream

    def test_load_config_sets_values(self, tmp_path):
        """Config file values should override defaults."""
        if sys.version_info < (3, 11):
            try:
                import tomli  # noqa: F401
            except ModuleNotFoundError:
                pytest.skip("tomli not available for Python < 3.11")

        config_file = tmp_path / ".worktreeflow.toml"
        config_file.write_text(
            '[repo]\n'
            'upstream_repo = "testorg/testrepo"\n'
            'base_branch = "develop"\n'
            '\n'
            '[workflow]\n'
            'feature_branch_prefix = "feature/"\n'
        )
        load_config(tmp_path)

        assert RepoConfig.DEFAULT_UPSTREAM_REPO == "testorg/testrepo"
        assert RepoConfig.DEFAULT_BASE_BRANCH == "develop"
        assert RepoConfig.FEATURE_BRANCH_PREFIX == "feature/"

        # Reset to defaults for other tests
        RepoConfig.DEFAULT_UPSTREAM_REPO = None
        RepoConfig.DEFAULT_BASE_BRANCH = "main"
        RepoConfig.FEATURE_BRANCH_PREFIX = "feat/"

    def test_load_config_none_root(self):
        """Passing None should be a no-op."""
        load_config(None)
