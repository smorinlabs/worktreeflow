"""Tests for SafetyValidator class."""

import pytest

from worktreeflow.wtf import SafetyValidator


class TestValidateBranchName:
    """Tests for SafetyValidator.validate_branch_name()."""

    @pytest.mark.parametrize(
        "name",
        [
            "main",
            "feature/add-login",
            "feat/my-feature",
            "release/v1.0.0",
            "fix/bug-123",
        ],
    )
    def test_valid_branch_names(self, name):
        # Should not raise
        SafetyValidator.validate_branch_name(name)

    @pytest.mark.parametrize(
        "name,reason",
        [
            ("feature branch", "contains space"),
            ("feat~1", "contains tilde"),
            ("feat^2", "contains caret"),
            ("feat:bar", "contains colon"),
            ("feat?bar", "contains question mark"),
            ("feat*bar", "contains asterisk"),
            ("feat[0]", "contains bracket"),
        ],
    )
    def test_invalid_characters(self, name, reason):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name(name)

    def test_double_dot_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("feat..bar")

    def test_leading_slash_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("/main")

    def test_trailing_slash_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("main/")

    def test_lock_suffix_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("branch.lock")

    def test_at_brace_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("feat@{1}")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("")

    def test_head_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_branch_name("HEAD")


class TestValidateSlug:
    """Tests for SafetyValidator.validate_slug()."""

    def test_valid_slug(self):
        assert SafetyValidator.validate_slug("my-feature") == "my-feature"

    def test_strips_whitespace(self):
        assert SafetyValidator.validate_slug("  my-feature  ") == "my-feature"

    def test_empty_slug_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_slug("")

    def test_whitespace_in_slug_rejected(self):
        with pytest.raises(ValueError):
            SafetyValidator.validate_slug("my feature")

    @pytest.mark.parametrize(
        "slug",
        [
            "feat~1",
            "feat^2",
            "feat:bar",
            "feat?x",
            "feat*x",
            "feat[0]",
            "feat\\bar",
        ],
    )
    def test_special_characters_rejected(self, slug):
        with pytest.raises(ValueError):
            SafetyValidator.validate_slug(slug)
