"""
worktreeflow configuration management.

Supports layered configuration:
1. Auto-detect from git remotes (lowest priority)
2. .worktreeflow.toml config file
3. CLI flags (highest priority)
"""

import sys
from pathlib import Path
from typing import Optional

try:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        try:
            import tomllib  # type: ignore[import]
        except ModuleNotFoundError:
            import tomli as tomllib
except ModuleNotFoundError:
    tomllib = None  # type: ignore[assignment]

CONFIG_FILENAME = ".worktreeflow.toml"


class RepoConfig:
    """
    Repository-specific configuration.

    Values are resolved in this order:
    1. Detected from git remotes (defaults)
    2. .worktreeflow.toml file overrides
    3. CLI flag overrides (applied at call sites)
    """

    # Repository defaults - auto-detected from remotes when possible
    DEFAULT_UPSTREAM_REPO: Optional[str] = None  # Detected from upstream remote
    DEFAULT_BASE_BRANCH: str = "main"

    # Branch naming conventions
    FEATURE_BRANCH_PREFIX: str = "feat/"
    BACKUP_BRANCH_PREFIX: str = "backup/"

    # Worktree configuration
    WORKTREE_BASE_PATH: str = "../wt"

    # Remote names
    ORIGIN_REMOTE: str = "origin"
    UPSTREAM_REMOTE: str = "upstream"

    # Git configuration
    PULL_FF_ONLY: bool = True

    # GitHub settings
    GITHUB_HOST: str = "github.com"
    USE_SSH: bool = True

    # PR defaults
    DEFAULT_DRAFT_PR: bool = False
    PR_BODY_TEMPLATE: str = """## Changes

{commit_list}

## Testing

- [ ] Tests pass
- [ ] Manual testing completed"""

    # Command defaults
    FORCE_DELETE_BRANCH: bool = False
    AUTO_STASH: bool = False
    CREATE_BACKUP_BRANCHES: bool = True

    # Confirmation prompts
    SKIP_CONFIRMATIONS: bool = False


def load_config(repo_root: Optional[Path] = None) -> None:
    """
    Load configuration from .worktreeflow.toml if it exists.

    Applies values onto RepoConfig class attributes.

    Args:
        repo_root: Repository root directory to search for config file.
    """
    if tomllib is None:
        return

    if repo_root is None:
        return

    config_path = repo_root / CONFIG_FILENAME
    if not config_path.exists():
        return

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Map TOML sections to RepoConfig attributes
    _MAPPING = {
        "upstream_repo": "DEFAULT_UPSTREAM_REPO",
        "base_branch": "DEFAULT_BASE_BRANCH",
        "feature_branch_prefix": "FEATURE_BRANCH_PREFIX",
        "backup_branch_prefix": "BACKUP_BRANCH_PREFIX",
        "worktree_base_path": "WORKTREE_BASE_PATH",
        "origin_remote": "ORIGIN_REMOTE",
        "upstream_remote": "UPSTREAM_REMOTE",
        "pull_ff_only": "PULL_FF_ONLY",
        "github_host": "GITHUB_HOST",
        "use_ssh": "USE_SSH",
        "default_draft_pr": "DEFAULT_DRAFT_PR",
        "pr_body_template": "PR_BODY_TEMPLATE",
        "force_delete_branch": "FORCE_DELETE_BRANCH",
        "auto_stash": "AUTO_STASH",
        "create_backup_branches": "CREATE_BACKUP_BRANCHES",
        "skip_confirmations": "SKIP_CONFIRMATIONS",
    }

    repo_section = data.get("repo", {})
    workflow_section = data.get("workflow", {})
    pr_section = data.get("pr", {})

    merged = {**repo_section, **workflow_section, **pr_section}

    for toml_key, attr_name in _MAPPING.items():
        if toml_key in merged:
            setattr(RepoConfig, attr_name, merged[toml_key])
