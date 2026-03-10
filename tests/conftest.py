"""Shared test fixtures for worktreeflow tests."""

import pytest
from git import Repo

from worktreeflow.wtf import BashCommandLogger


@pytest.fixture
def dry_run_logger():
    """A BashCommandLogger in dry-run mode (no real commands executed)."""
    return BashCommandLogger(dry_run=True)


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a temporary git repository with an initial commit."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    # Create initial commit
    readme = tmp_path / "README.md"
    readme.write_text("# Test Repo\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")

    return repo
