"""Tests for --quiet and --verbose output control."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from worktreeflow.config import RepoSettings
from worktreeflow.logger import BashCommandLogger
from worktreeflow.manager import GitWorkflowManager
from worktreeflow.validator import SafetyValidator


def _make_manager(dry_run=False, quiet=False, verbose=False):
    """Create a GitWorkflowManager with mocked repo for testing."""
    manager = object.__new__(GitWorkflowManager)
    manager.repo = MagicMock()
    manager.logger = BashCommandLogger(dry_run=dry_run)
    manager.validator = SafetyValidator()
    manager.config = RepoSettings()
    manager.dry_run = dry_run
    manager.upstream_repo = "owner/repo"
    manager.fork_owner = "myuser"
    manager.root = Path("/fake/repo")
    manager.repo_name = "repo"
    manager.debug = False
    manager.save_history = False
    manager.quiet = quiet
    manager.verbose = verbose
    return manager


class TestQuietMode:
    """Test that quiet mode suppresses info output."""

    def test_info_suppressed_in_quiet_mode(self, capsys):
        manager = _make_manager(quiet=True)
        manager.info("This should not be printed")
        captured = capsys.readouterr()
        assert "This should not be printed" not in captured.out

    def test_info_shown_in_normal_mode(self):
        manager = _make_manager(quiet=False)
        # info() calls console.print which uses rich, so we verify it doesn't raise
        manager.info("This should work fine")

    def test_error_shown_in_quiet_mode(self):
        manager = _make_manager(quiet=True)
        # error() always prints, even in quiet mode
        manager.error("This error should always show")

    def test_check_repo_quiet(self, capsys):
        manager = _make_manager(quiet=True)
        manager.check_repo()
        captured = capsys.readouterr()
        # In quiet mode, info messages are suppressed
        assert "Inside Git repository" not in captured.out


class TestVerboseMode:
    """Test that verbose mode shows extra detail."""

    def test_detail_shown_in_verbose_mode(self):
        manager = _make_manager(verbose=True)
        # detail() should work when verbose=True
        manager.detail("Extra detail here")

    def test_detail_hidden_in_normal_mode(self, capsys):
        manager = _make_manager(verbose=False)
        manager.detail("This should not be printed")
        captured = capsys.readouterr()
        assert "This should not be printed" not in captured.out

    def test_detail_hidden_when_quiet_overrides_verbose(self, capsys):
        manager = _make_manager(quiet=True, verbose=True)
        manager.detail("This should not be printed")
        captured = capsys.readouterr()
        assert "This should not be printed" not in captured.out


class TestCliQuietVerboseFlags:
    """Test CLI flag integration."""

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_quiet_flag_registered(self, mock_manager_cls):
        from click.testing import CliRunner

        from worktreeflow.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        assert '--quiet' in result.output or '-q' in result.output

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_verbose_flag_registered(self, mock_manager_cls):
        from click.testing import CliRunner

        from worktreeflow.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        assert '--verbose' in result.output or '-v' in result.output

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_quiet_verbose_mutually_exclusive(self, mock_manager_cls):
        from click.testing import CliRunner

        from worktreeflow.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['--quiet', '--verbose', 'doctor'])
        assert result.exit_code != 0
        assert "Cannot use --quiet and --verbose together" in result.output
