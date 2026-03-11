"""
Input validation and safety checks for worktreeflow Git operations.
"""

import re
from datetime import datetime

from git import GitCommandError, Repo
from rich.console import Console

console = Console()


class SafetyValidator:
    """
    Input validation and safety checks for Git operations.

    Ensures branch names, slugs, and other inputs are safe and valid.
    """

    @staticmethod
    def validate_branch_name(branch: str) -> None:
        """
        Validate branch name per Git standards.

        Bash equivalent:
            git check-ref-format --branch "{branch}"

        Raises:
            ValueError: If branch name is invalid
        """
        invalid_chars = r"[\s~^:?*\[]"
        if re.search(invalid_chars, branch):
            raise ValueError(f"Branch name '{branch}' contains invalid characters (spaces, ~, ^, :, ?, *, [)")

        if ".." in branch:
            raise ValueError("Branch name cannot contain two consecutive dots (..)")

        if branch.startswith("/") or branch.endswith("/"):
            raise ValueError("Branch name cannot start or end with slash")

        if branch.endswith(".lock"):
            raise ValueError("Branch name cannot end with .lock")

        if "@{" in branch:
            raise ValueError("Branch name cannot contain @{ sequence")

        if not branch or branch == "HEAD":
            raise ValueError(f"Invalid branch name: {branch}")

    @staticmethod
    def validate_slug(slug: str) -> str:
        """
        Validate and clean a feature slug.

        Args:
            slug: The feature slug to validate

        Returns:
            Cleaned slug

        Raises:
            ValueError: If slug is invalid
        """
        if not slug:
            raise ValueError("SLUG is required")

        slug = slug.strip()

        if re.search(r"\s", slug):
            raise ValueError(f"SLUG '{slug}' contains whitespace. Please use a slug without spaces.")

        if re.search(r"[~^:?*\[\]\\]", slug):
            raise ValueError(f"SLUG '{slug}' contains invalid characters")

        return slug

    @staticmethod
    def check_uncommitted_changes(repo: Repo, stash: bool = False) -> bool:
        """
        Check for uncommitted changes in repository.

        Bash equivalent:
            git diff --quiet && git diff --cached --quiet

        Args:
            repo: GitPython Repo object
            stash: Whether to auto-stash changes

        Returns:
            True if changes were stashed, False otherwise

        Raises:
            GitCommandError: If uncommitted changes exist and stash=False
        """
        if repo.is_dirty(untracked_files=True):
            if stash:
                console.print("[yellow]Stashing uncommitted changes...[/yellow]")
                repo.git.stash("push", "-m", f"wtf auto-stash {datetime.now().isoformat()}")
                return True
            else:
                raise GitCommandError(
                    "git status",
                    1,
                    stderr="You have uncommitted changes. Please commit or stash them first.\n"
                    "  To stash: git stash\n"
                    "  To see changes: git status\n"
                    "  Or use --stash flag to auto-stash",
                )
        return False
