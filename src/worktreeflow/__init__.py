"""
worktreeflow - Git workflow manager for feature branches using worktrees
"""

__version__ = "0.3.0"
__author__ = "Steve Morin"
__license__ = "MIT"

from worktreeflow.cli import cli
from worktreeflow.errors import WorktreeFlowError

__all__ = ["cli", "WorktreeFlowError", "__version__"]
