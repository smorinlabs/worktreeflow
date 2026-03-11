"""
worktreeflow configuration management.

Supports layered configuration:
1. Auto-detect from git remotes (lowest priority)
2. .worktreeflow.toml config file
3. CLI flags (highest priority)
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = ".worktreeflow.toml"


class RepoConfig:
    """
    Repository-specific configuration.

    Values are resolved in this order:
    1. Detected from git remotes (defaults)
    2. .worktreeflow.toml file overrides
    3. CLI flag overrides (applied at call sites)

    Note: This class is retained for backward compatibility.
    New code should use RepoSettings instances from load_config().
    """

    # Repository defaults - auto-detected from remotes when possible
    DEFAULT_UPSTREAM_REPO: str | None = None  # Detected from upstream remote
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


@dataclass
class RepoSettings:
    """
    Instance-based repository configuration.

    Unlike RepoConfig (which uses class-level mutation), this is an immutable
    instance that can be safely passed around without global side effects.
    """

    upstream_repo: str | None = None
    base_branch: str = "main"
    feature_branch_prefix: str = "feat/"
    backup_branch_prefix: str = "backup/"
    worktree_base_path: str = "../wt"
    origin_remote: str = "origin"
    upstream_remote: str = "upstream"
    pull_ff_only: bool = True
    github_host: str = "github.com"
    use_ssh: bool = True
    default_draft_pr: bool = False
    pr_body_template: str = field(
        default="## Changes\n\n{commit_list}\n\n## Testing\n\n- [ ] Tests pass\n- [ ] Manual testing completed"
    )
    force_delete_branch: bool = False
    auto_stash: bool = False
    create_backup_branches: bool = True
    skip_confirmations: bool = False


def load_config(repo_root: Path | None = None) -> RepoSettings:
    """
    Load configuration from .worktreeflow.toml if it exists.

    Returns a RepoSettings instance with values from the config file
    applied on top of defaults. Also updates RepoConfig class attributes
    for backward compatibility.

    Args:
        repo_root: Repository root directory to search for config file.

    Returns:
        RepoSettings instance with loaded configuration.
    """
    settings = RepoSettings()

    if repo_root is None:
        return settings

    config_path = repo_root / CONFIG_FILENAME
    if not config_path.exists():
        return settings

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Map TOML keys to both RepoSettings fields and RepoConfig attributes
    _MAPPING = {
        "upstream_repo": ("upstream_repo", "DEFAULT_UPSTREAM_REPO"),
        "base_branch": ("base_branch", "DEFAULT_BASE_BRANCH"),
        "feature_branch_prefix": ("feature_branch_prefix", "FEATURE_BRANCH_PREFIX"),
        "backup_branch_prefix": ("backup_branch_prefix", "BACKUP_BRANCH_PREFIX"),
        "worktree_base_path": ("worktree_base_path", "WORKTREE_BASE_PATH"),
        "origin_remote": ("origin_remote", "ORIGIN_REMOTE"),
        "upstream_remote": ("upstream_remote", "UPSTREAM_REMOTE"),
        "pull_ff_only": ("pull_ff_only", "PULL_FF_ONLY"),
        "github_host": ("github_host", "GITHUB_HOST"),
        "use_ssh": ("use_ssh", "USE_SSH"),
        "default_draft_pr": ("default_draft_pr", "DEFAULT_DRAFT_PR"),
        "pr_body_template": ("pr_body_template", "PR_BODY_TEMPLATE"),
        "force_delete_branch": ("force_delete_branch", "FORCE_DELETE_BRANCH"),
        "auto_stash": ("auto_stash", "AUTO_STASH"),
        "create_backup_branches": ("create_backup_branches", "CREATE_BACKUP_BRANCHES"),
        "skip_confirmations": ("skip_confirmations", "SKIP_CONFIRMATIONS"),
    }

    repo_section = data.get("repo", {})
    workflow_section = data.get("workflow", {})
    pr_section = data.get("pr", {})

    merged = {**repo_section, **workflow_section, **pr_section}

    for toml_key, (settings_field, repo_config_attr) in _MAPPING.items():
        if toml_key in merged:
            setattr(settings, settings_field, merged[toml_key])
            # Backward compat: also set on RepoConfig class
            setattr(RepoConfig, repo_config_attr, merged[toml_key])

    return settings


def generate_config(
    upstream_repo: str | None = None,
    base_branch: str = "main",
    feature_branch_prefix: str = "feat/",
    use_ssh: bool = True,
    auto_stash: bool = False,
    create_backup_branches: bool = True,
    default_draft_pr: bool = False,
) -> str:
    """
    Generate a .worktreeflow.toml config file content.

    Args:
        upstream_repo: Upstream repo in owner/repo format.
        base_branch: Base branch name.
        feature_branch_prefix: Prefix for feature branches.
        use_ssh: Whether to use SSH URLs.
        auto_stash: Whether to auto-stash during updates.
        create_backup_branches: Whether to create backups.
        default_draft_pr: Whether to create PRs as drafts.

    Returns:
        TOML file content as a string.
    """
    lines = ["# worktreeflow configuration", "# See: https://github.com/smorinlabs/worktreeflow", ""]
    lines.append("[repo]")
    if upstream_repo:
        lines.append(f'upstream_repo = "{upstream_repo}"')
    lines.append(f'base_branch = "{base_branch}"')
    lines.append(f"use_ssh = {'true' if use_ssh else 'false'}")
    lines.append("")
    lines.append("[workflow]")
    lines.append(f'feature_branch_prefix = "{feature_branch_prefix}"')
    lines.append(f"auto_stash = {'true' if auto_stash else 'false'}")
    lines.append(f"create_backup_branches = {'true' if create_backup_branches else 'false'}")
    lines.append("")
    lines.append("[pr]")
    lines.append(f"default_draft_pr = {'true' if default_draft_pr else 'false'}")
    lines.append("")
    return "\n".join(lines)
