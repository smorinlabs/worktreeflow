"""Tests for worktree porcelain output parsing (B01 regression)."""

from worktreeflow.wtf import GitWorkflowManager


class TestParseWorktreePorcelain:
    """Regression tests for B01: off-by-one in branch name parsing."""

    def test_simple_branch(self):
        output = "worktree /home/user/repo\nHEAD abc1234\nbranch refs/heads/main\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert len(result) == 1
        assert result[0]["branch"] == "main"

    def test_branch_no_leading_slash(self):
        """B01 regression: branch name must NOT have a leading slash."""
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/main\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert not result[0]["branch"].startswith("/")
        assert result[0]["branch"] == "main"

    def test_nested_branch_name(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/feature/deep/nested\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert result[0]["branch"] == "feature/deep/nested"

    def test_single_char_branch(self):
        output = "worktree /repo\nHEAD abc\nbranch refs/heads/a\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert result[0]["branch"] == "a"

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
        assert result[0]["path"] == "/home/user/repo"
        assert result[1]["branch"] == "feat/login"
        assert result[1]["path"] == "/home/user/wt/feat-login"

    def test_head_parsing(self):
        output = "worktree /repo\nHEAD abc1234def5678\nbranch refs/heads/main\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert result[0]["head"] == "abc1234def5678"

    def test_path_parsing(self):
        output = "worktree /home/user/my repo\nHEAD abc\nbranch refs/heads/main\n"
        result = GitWorkflowManager._parse_worktree_porcelain(output)
        assert result[0]["path"] == "/home/user/my repo"

    def test_empty_output(self):
        result = GitWorkflowManager._parse_worktree_porcelain("")
        # Empty string produces one empty-string line, no worktree prefix → empty result
        assert result == [] or all("path" not in wt for wt in result)
