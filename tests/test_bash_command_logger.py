"""Tests for BashCommandLogger class."""

import json

import pytest

from worktreeflow.wtf import BashCommandLogger


class TestLog:
    """Tests for BashCommandLogger.log()."""

    def test_log_appends_command(self):
        logger = BashCommandLogger()
        logger.log("git status", "Check status")
        assert len(logger.commands) == 1
        assert logger.commands[0].command == "git status"
        assert logger.commands[0].description == "Check status"

    def test_log_multiple_commands(self):
        logger = BashCommandLogger()
        logger.log("git status")
        logger.log("git diff")
        assert len(logger.commands) == 2

    def test_log_without_description(self):
        logger = BashCommandLogger()
        logger.log("git status")
        assert logger.commands[0].description is None


class TestExecuteDryRun:
    """Tests for BashCommandLogger.execute() in dry-run mode."""

    def test_dry_run_returns_zero_exit(self, dry_run_logger):
        result = dry_run_logger.execute("echo hello")
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_dry_run_does_not_execute(self, dry_run_logger):
        # This command would fail if actually executed
        result = dry_run_logger.execute("false")
        assert result.returncode == 0  # Dry-run always returns 0

    def test_dry_run_logs_command(self, dry_run_logger):
        dry_run_logger.execute("git push origin main", "Push to remote")
        assert len(dry_run_logger.commands) == 1
        assert dry_run_logger.commands[0].command == "git push origin main"

    def test_dry_run_marks_not_executed(self, dry_run_logger):
        dry_run_logger.execute("git push")
        assert dry_run_logger.commands[0].executed is False


class TestSaveHistory:
    """Tests for BashCommandLogger.save_history()."""

    def test_save_creates_valid_json(self, tmp_path):
        logger = BashCommandLogger()
        logger.log("git status", "Check status")
        logger.log("git diff", "Show diff")

        filepath = str(tmp_path / "history.json")
        logger.save_history(filepath)

        with open(filepath) as f:
            data = json.load(f)

        assert len(data) == 2
        assert data[0]["command"] == "git status"
        assert data[0]["description"] == "Check status"
        assert "timestamp" in data[0]
        assert data[0]["executed"] is False

    def test_save_empty_history(self, tmp_path):
        logger = BashCommandLogger()
        filepath = str(tmp_path / "history.json")
        logger.save_history(filepath)

        with open(filepath) as f:
            data = json.load(f)
        assert data == []
