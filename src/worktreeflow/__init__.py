"""
worktreeflow - Git workflow manager for feature branches using worktrees
"""

__version__ = "0.2.0"
__author__ = "Steve Morin"
__license__ = "MIT"

# Import main CLI for convenience
from worktreeflow.wtf import cli

__all__ = ["cli", "__version__"]
