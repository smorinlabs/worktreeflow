"""Tests for CLI interface."""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from worktreeflow.cli import cli


class TestCliHelp:
    """Test CLI help and basic structure."""

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_help_output(self, mock_manager_cls):
        """CLI --help should list all commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        assert result.exit_code == 0
        assert 'workflow manager' in result.output.lower()

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_commands_registered(self, mock_manager_cls):
        """All expected commands should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])

        expected_commands = [
            'doctor', 'upstream-add', 'fork-setup',
            'sync-main', 'sync-main-force', 'zero-ffsync',
            'wt-new', 'wt-publish', 'wt-pr', 'wt-update',
            'wt-clean', 'wt-list', 'wt-status',
            'check-repo', 'check-origin', 'check-upstream',
            'tutorial', 'quickstart',
        ]
        for cmd in expected_commands:
            assert cmd in result.output, f"Command '{cmd}' not found in help output"

    @patch('worktreeflow.cli.GitWorkflowManager')
    def test_wt_new_has_no_sync_option(self, mock_manager_cls):
        """wt-new should have --no-sync option."""
        runner = CliRunner()
        result = runner.invoke(cli, ['wt-new', '--help'])
        assert '--no-sync' in result.output


class TestTutorialAndQuickstart:
    """Test tutorial and quickstart commands."""

    def test_tutorial_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['tutorial'])
        assert result.exit_code == 0
        assert 'Tutorial' in result.output or 'tutorial' in result.output.lower()

    def test_quickstart_output(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['quickstart'])
        assert result.exit_code == 0
        assert 'Quickstart' in result.output or 'quickstart' in result.output.lower()

    def test_tutorial_mentions_shell_completion(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['tutorial'])
        assert '_WTF_COMPLETE' in result.output

    def test_tutorial_mentions_no_sync(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['tutorial'])
        assert '--no-sync' in result.output
