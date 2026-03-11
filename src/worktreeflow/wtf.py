#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "gitpython>=3.1.40",
#   "click>=8.1.0",
#   "rich>=13.0",
#   "typing-extensions>=4.0",
# ]
# ///
"""
worktreeflow - Git Workflow Manager
====================================
Python port of hl + hl.mk with enhanced features and safety.

This script merges the capabilities of the hl bash wrapper and hl.mk makefile
into a single Python script using GitPython for Git operations.

Every Git operation documents its bash equivalent for transparency.

This module re-exports all public API for backward compatibility.
The implementation has been split into:
  - config.py: Configuration management
  - logger.py: Bash command logging
  - validator.py: Input validation
  - manager.py: Core workflow operations
  - cli.py: Click CLI interface
"""

# Re-export public API for backward compatibility
# Keep these available for tests that import from wtf directly
import shlex  # noqa: F401

from worktreeflow.cli import cli  # noqa: F401
from worktreeflow.config import RepoConfig, load_config  # noqa: F401
from worktreeflow.logger import BashCommandLogger, CommandEntry  # noqa: F401
from worktreeflow.manager import GitWorkflowManager  # noqa: F401
from worktreeflow.validator import SafetyValidator  # noqa: F401

if __name__ == "__main__":
    cli()
