"""
worktreeflow - Git workflow manager for feature branches using worktrees
"""

try:
    from importlib.metadata import version as _metadata_version

    __version__ = _metadata_version("worktreeflow")
except Exception:
    __version__ = "0.0.0+unknown"

__author__ = "Steve Morin"
__license__ = "MIT"

from worktreeflow.cli import cli
from worktreeflow.errors import WorktreeFlowError

__all__ = ["cli", "WorktreeFlowError", "__version__"]
