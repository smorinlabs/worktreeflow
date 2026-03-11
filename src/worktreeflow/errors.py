"""Custom exceptions for worktreeflow."""


class WorktreeFlowError(Exception):
    """
    Base exception for worktreeflow errors.

    Raised from business logic instead of calling sys.exit(1) directly.
    Caught at the CLI layer to print the message and exit cleanly.
    """
