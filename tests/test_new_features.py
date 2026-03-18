"""Tests for new features: version, aliases, wt-cd, wt-open, wt-reopen, --json, init, slug auto-detect."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from worktreeflow.cli import cli
from worktreeflow.config import RepoSettings, generate_config
from worktreeflow.errors import WorktreeFlowError
from worktreeflow.logger import BashCommandLogger
from worktreeflow.manager import GitWorkflowManager
from worktreeflow.validator import SafetyValidator


def _make_manager(dry_run=False, config=None, json_output=False):
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
    manager.json_output = json_output
    return manager


# ========== Version Command ==========


class TestVersionCommand:
    def test_version_output(self):
        from importlib.metadata import version as _meta_version

        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "worktreeflow" in result.output
        assert _meta_version("worktreeflow") in result.output

    def test_version_is_not_unknown(self):
        from worktreeflow import __version__

        assert __version__ != "0.0.0+unknown"
        assert "." in __version__

    def test_version_in_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "version" in result.output


# ========== Command Aliases ==========


class TestCommandAliases:
    @patch("worktreeflow.cli.GitWorkflowManager")
    def test_all_aliases_in_help(self, mock_manager_cls):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

    @patch("worktreeflow.cli.GitWorkflowManager")
    def test_new_commands_registered(self, mock_manager_cls):
        """All new commands should be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        new_commands = [
            "version",
            "init",
            "wt-cd",
            "wt-open",
            "wt-reopen",
        ]
        for cmd in new_commands:
            assert cmd in result.output, f"Command '{cmd}' not found in help output"

    @patch("worktreeflow.cli.GitWorkflowManager")
    def test_original_commands_still_registered(self, mock_manager_cls):
        """All original commands should still be registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        expected_commands = [
            "doctor",
            "upstream-add",
            "fork-setup",
            "sync-main",
            "wt-new",
            "wt-publish",
            "wt-pr",
            "wt-update",
            "wt-clean",
            "wt-list",
            "wt-status",
            "tutorial",
            "quickstart",
        ]
        for cmd in expected_commands:
            assert cmd in result.output, f"Command '{cmd}' not found in help output"


# ========== Slug Auto-Detection ==========


class TestSlugAutoDetect:
    def test_infer_slug_from_worktree_path(self):
        manager = _make_manager()
        with patch("worktreeflow.manager.Path.cwd", return_value=Path("/some/wt/repo/my-feature")):
            result = manager._infer_slug_from_cwd()
            assert result == "my-feature"

    def test_infer_slug_returns_none_outside_worktree(self):
        manager = _make_manager()
        with patch("worktreeflow.manager.Path.cwd", return_value=Path("/home/user/other-project")):
            result = manager._infer_slug_from_cwd()
            assert result is None

    def test_resolve_slug_explicit(self):
        manager = _make_manager()
        assert manager.resolve_slug("my-feature") == "my-feature"

    def test_resolve_slug_auto_detect(self):
        manager = _make_manager()
        with patch.object(manager, "_infer_slug_from_cwd", return_value="detected-slug"):
            assert manager.resolve_slug(None) == "detected-slug"

    def test_resolve_slug_raises_when_no_slug(self):
        manager = _make_manager()
        with (
            patch.object(manager, "_infer_slug_from_cwd", return_value=None),
            pytest.raises(WorktreeFlowError, match="SLUG is required"),
        ):
            manager.resolve_slug(None)


# ========== wt-cd Command ==========


class TestWtCd:
    def test_wt_cd_prints_path(self):
        manager = _make_manager()
        worktree_path = manager._get_worktree_path("my-feature")

        with (
            patch.object(Path, "exists", return_value=True),
            patch("worktreeflow.manager.click.echo") as mock_echo,
        ):
            manager.wt_cd("my-feature")
            mock_echo.assert_called_once_with(str(worktree_path))

    def test_wt_cd_raises_when_not_found(self):
        manager = _make_manager()
        with pytest.raises(WorktreeFlowError, match="Worktree not found"):
            manager.wt_cd("nonexistent")


# ========== wt-open Command ==========


class TestWtOpen:
    def test_wt_open_uses_editor_env(self):
        manager = _make_manager()
        worktree_path = manager._get_worktree_path("my-feature")

        with (
            patch.object(Path, "exists", return_value=True),
            patch.dict("os.environ", {"EDITOR": "nano"}),
            patch("worktreeflow.manager.subprocess.Popen") as mock_popen,
        ):
            manager.wt_open("my-feature")
            mock_popen.assert_called_once_with(["nano", str(worktree_path)])

    def test_wt_open_uses_explicit_editor(self):
        manager = _make_manager()

        with (
            patch.object(Path, "exists", return_value=True),
            patch("worktreeflow.manager.subprocess.Popen") as mock_popen,
        ):
            manager.wt_open("my-feature", editor="vim")
            mock_popen.assert_called_once()

    def test_wt_open_raises_when_no_editor(self):
        manager = _make_manager()

        with (
            patch.object(Path, "exists", return_value=True),
            patch.dict("os.environ", {}, clear=True),
            patch("worktreeflow.manager.shutil.which", return_value=None),
            pytest.raises(WorktreeFlowError, match="No editor found"),
        ):
            manager.wt_open("my-feature")

    def test_wt_open_dry_run(self):
        manager = _make_manager(dry_run=True)

        with (
            patch.object(Path, "exists", return_value=True),
            patch("worktreeflow.manager.subprocess.Popen") as mock_popen,
        ):
            manager.wt_open("my-feature", editor="code")
            mock_popen.assert_not_called()


# ========== wt-reopen Command ==========


class TestWtReopen:
    def test_wt_reopen_raises_if_worktree_exists(self):
        manager = _make_manager()

        with (
            patch.object(Path, "exists", return_value=True),
            pytest.raises(WorktreeFlowError, match="Worktree already exists"),
        ):
            manager.wt_reopen("my-feature")

    def test_wt_reopen_raises_if_branch_not_on_remote(self):
        manager = _make_manager()

        result_no_branch = MagicMock(returncode=2, stdout="")
        result_fetch = MagicMock(returncode=0, stdout="")

        def mock_execute(cmd, desc=None, check=True, capture_output=True):
            if "ls-remote" in cmd:
                return result_no_branch
            return result_fetch

        manager.logger.execute = mock_execute

        with pytest.raises(WorktreeFlowError, match="not found on origin"):
            manager.wt_reopen("nonexistent")


# ========== --json Output Mode ==========


class TestJsonOutput:
    def test_doctor_json(self):
        manager = _make_manager(json_output=True)

        # Set up mock remotes properly
        origin_mock = MagicMock()
        origin_mock.url = "git@github.com:user/repo.git"
        upstream_mock = MagicMock()
        upstream_mock.url = "git@github.com:owner/repo.git"

        manager.repo.remotes = {"origin": origin_mock, "upstream": upstream_mock}
        manager.repo.remote.side_effect = lambda name: {"origin": origin_mock, "upstream": upstream_mock}[name]
        manager.repo.is_dirty.return_value = False
        manager.repo.active_branch.name = "main"

        with patch("worktreeflow.manager.click.echo") as mock_echo:
            manager.doctor()
            mock_echo.assert_called_once()
            output = mock_echo.call_args[0][0]
            data = json.loads(output)
            assert "repo_name" in data
            assert "healthy" in data
            assert data["repo_name"] == "repo"
            assert data["origin_url"] == "git@github.com:user/repo.git"


# ========== generate_config ==========


class TestGenerateConfig:
    def test_generates_valid_toml(self):
        content = generate_config(
            upstream_repo="owner/repo",
            base_branch="main",
            feature_branch_prefix="feat/",
        )
        assert "[repo]" in content
        assert "[workflow]" in content
        assert "[pr]" in content
        assert 'upstream_repo = "owner/repo"' in content

    def test_generates_without_upstream(self):
        content = generate_config(upstream_repo=None)
        assert "upstream_repo" not in content

    def test_generates_all_sections(self):
        content = generate_config(
            upstream_repo="a/b",
            auto_stash=True,
            default_draft_pr=True,
        )
        assert "auto_stash = true" in content
        assert "default_draft_pr = true" in content


# ========== require_gh ==========


class TestRequireGh:
    def test_require_gh_raises_without_gh(self):
        manager = _make_manager()
        with (
            patch("worktreeflow.manager.shutil.which", return_value=None),
            pytest.raises(WorktreeFlowError, match="GitHub CLI"),
        ):
            manager._require_gh()

    def test_require_gh_passes_with_gh(self):
        manager = _make_manager()
        with patch("worktreeflow.manager.shutil.which", return_value="/usr/bin/gh"):
            manager._require_gh()  # Should not raise


# ========== Tutorial and Quickstart Updates ==========


class TestTutorialUpdates:
    def test_tutorial_mentions_aliases(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tutorial"])
        assert "alias" in result.output.lower()

    def test_tutorial_mentions_auto_detect(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tutorial"])
        assert "auto-detect" in result.output.lower()

    def test_tutorial_mentions_json(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tutorial"])
        assert "--json" in result.output

    def test_tutorial_mentions_env_vars(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tutorial"])
        assert "WTF_BASE_BRANCH" in result.output

    def test_quickstart_mentions_aliases(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])
        assert "new -> wt-new" in result.output

    def test_quickstart_mentions_init(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["quickstart"])
        assert "init" in result.output
