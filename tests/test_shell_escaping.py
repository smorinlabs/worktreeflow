"""Tests for shell injection prevention in PR creation (B02 regression)."""

import shlex

from worktreeflow.wtf import GitWorkflowManager


def _build_pr_command(title: str, body: str, draft: bool = False) -> str:
    """Build a PR command using the same logic as GitWorkflowManager.

    We can't easily call wt_pr() directly (it needs a real git repo),
    so we replicate the shlex.quote() command construction to verify
    the pattern is safe.
    """
    upstream_repo = "owner/repo"
    fork_owner = "myuser"
    branch_name = "feat/test"
    base = "main"

    pr_cmd = (
        f"gh pr create"
        f" --repo {shlex.quote(upstream_repo)}"
        f" --head {shlex.quote(f'{fork_owner}:{branch_name}')}"
        f" --base {shlex.quote(base)}"
        f" --title {shlex.quote(title)}"
        f" --body {shlex.quote(body)}"
    )
    if draft:
        pr_cmd += " --draft"
    return pr_cmd


class TestShellEscaping:
    """B02 regression: Verify shell metacharacters are safely escaped."""

    def test_semicolon_injection(self):
        cmd = _build_pr_command('test"; rm -rf / #', "body")
        # shlex.split should parse this as a single --title argument
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == 'test"; rm -rf / #'

    def test_backtick_injection(self):
        cmd = _build_pr_command("`whoami`", "body")
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == "`whoami`"

    def test_dollar_paren_injection(self):
        cmd = _build_pr_command("$(cat /etc/passwd)", "body")
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == "$(cat /etc/passwd)"

    def test_newline_injection(self):
        cmd = _build_pr_command("title\n; rm -rf /", "body")
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == "title\n; rm -rf /"

    def test_pipe_injection(self):
        cmd = _build_pr_command("title | cat /etc/passwd", "body")
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == "title | cat /etc/passwd"

    def test_single_quote_in_title(self):
        cmd = _build_pr_command("it's a test", "body")
        parts = shlex.split(cmd)
        title_idx = parts.index("--title") + 1
        assert parts[title_idx] == "it's a test"

    def test_body_injection(self):
        cmd = _build_pr_command("title", 'body\n; rm -rf /; echo "')
        parts = shlex.split(cmd)
        body_idx = parts.index("--body") + 1
        assert parts[body_idx] == 'body\n; rm -rf /; echo "'

    def test_draft_flag_appended(self):
        cmd = _build_pr_command("title", "body", draft=True)
        assert cmd.endswith(" --draft")

    def test_no_draft_flag_when_false(self):
        cmd = _build_pr_command("title", "body", draft=False)
        assert "--draft" not in cmd


class TestShellEscapingInSource:
    """Verify the actual source code uses shlex.quote (not manual escaping)."""

    def test_shlex_imported(self):
        """Ensure shlex is available in the module."""
        import worktreeflow.wtf as wtf_module

        assert hasattr(wtf_module, "shlex") or "shlex" in dir(wtf_module)

    def test_no_manual_escaping_pattern(self):
        """The old manual escaping pattern should not exist in the PR method."""
        import inspect

        source = inspect.getsource(GitWorkflowManager.wt_pr)
        assert "title_escaped" not in source
        assert "body_escaped" not in source
        assert ".replace('\"', '\\\\\"')" not in source
