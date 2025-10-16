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
"""

import sys
import re
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field

import click
import git
from git import Repo, GitCommandError
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# ==================== REPOSITORY CONFIGURATION ====================
# Customize these settings for your specific repository
# When copying this script to a new repo, update these values first

class RepoConfig:
    """
    Repository-specific configuration - modify these for your repo.
    This centralizes all repo-specific settings for easy customization.
    """
    
    # Repository defaults
    DEFAULT_UPSTREAM_REPO = "humanlayer/humanlayer"  # Format: owner/repo
    DEFAULT_BASE_BRANCH = "main"  # or "master", "develop", etc.
    
    # Branch naming conventions
    FEATURE_BRANCH_PREFIX = "feat/"  # Features will be: feat/{slug}
    BACKUP_BRANCH_PREFIX = "backup/"  # Backups will be: backup/{branch}-{timestamp}
    
    # Worktree configuration
    WORKTREE_BASE_PATH = "../wt"  # Relative to repo root
    # Pattern for worktree paths: {base_path}/{repo_name}/{slug}
    
    # Remote names (standard Git convention, rarely needs changing)
    ORIGIN_REMOTE = "origin"  # Your fork
    UPSTREAM_REMOTE = "upstream"  # Original repo
    
    # Git configuration
    PULL_FF_ONLY = True  # Configure pull.ff=only for clean history
    
    # GitHub settings
    GITHUB_HOST = "github.com"  # GitHub Enterprise users can change this
    USE_SSH = True  # True for SSH URLs, False for HTTPS
    
    # PR defaults
    DEFAULT_DRAFT_PR = False  # Create PRs as drafts by default
    PR_BODY_TEMPLATE = """## Changes

{commit_list}

## Testing

- [ ] Tests pass
- [ ] Manual testing completed"""
    
    # Command defaults
    FORCE_DELETE_BRANCH = False  # Use -D instead of -d for branch deletion
    AUTO_STASH = False  # Automatically stash changes during updates
    CREATE_BACKUP_BRANCHES = True  # Create backup branches before destructive operations
    
    # Confirmation prompts
    SKIP_CONFIRMATIONS = False  # Skip confirmation prompts (dangerous!)

# ==================== END CONFIGURATION ====================

# Global console for rich output
console = Console()

# Try to import cased-kit (optional) - commented out for now
# HAS_CASED_KIT = False
# try:
#     import importlib.util
#     if importlib.util.find_spec('kit') is not None:
#         from kit import Repository as CasedRepository
#         HAS_CASED_KIT = True
# except ImportError:
#     pass
HAS_CASED_KIT = False  # Disabled for now


@dataclass
class CommandEntry:
    """Record of a bash command execution."""
    command: str
    description: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    executed: bool = False
    result: Optional[str] = None


class BashCommandLogger:
    """
    Logs and documents all bash command equivalents.
    
    This class ensures transparency by documenting what bash commands
    would be (or are being) executed for each operation.
    """
    
    def __init__(self, debug: bool = False, dry_run: bool = False):
        self.debug = debug
        self.dry_run = dry_run
        self.commands: List[CommandEntry] = []
        
    def log(self, bash_cmd: str, description: Optional[str] = None) -> None:
        """
        Log a bash command with optional description.
        
        Args:
            bash_cmd: The bash command that would be executed
            description: Optional description of what the command does
        """
        entry = CommandEntry(command=bash_cmd, description=description)
        self.commands.append(entry)
        
        if self.debug:
            console.print(f"[cyan][BASH][/cyan] {bash_cmd}")
            if description:
                console.print(f"       [dim]{description}[/dim]")
        
        if self.dry_run:
            console.print(f"[yellow][DRY-RUN][/yellow] Would execute: {bash_cmd}")
    
    def execute(self, bash_cmd: str, description: Optional[str] = None, 
                check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
        """
        Log and execute a bash command.
        
        Args:
            bash_cmd: Command to execute
            description: Optional description
            check: Whether to raise on non-zero exit
            capture_output: Whether to capture stdout/stderr
            
        Returns:
            CompletedProcess result
        """
        self.log(bash_cmd, description)
        
        if self.dry_run:
            # Return mock result in dry-run mode (text mode)
            return subprocess.CompletedProcess(args=bash_cmd, returncode=0, stdout="", stderr="")
        
        # Mark as executed
        if self.commands:
            self.commands[-1].executed = True
        
        # Execute the command
        result = subprocess.run(
            bash_cmd,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True
        )
        
        # Store result
        if self.commands:
            self.commands[-1].result = result.stdout if capture_output else "executed"
        
        return result
    
    def save_history(self, filepath: str = ".wtf_history.json") -> None:
        """Save command history for audit/learning."""
        history = []
        for entry in self.commands:
            history.append({
                "command": entry.command,
                "description": entry.description,
                "timestamp": entry.timestamp.isoformat(),
                "executed": entry.executed,
                "result": entry.result
            })
        
        with open(filepath, "w") as f:
            json.dump(history, f, indent=2)
        
        if self.debug:
            console.print(f"[green]Command history saved to {filepath}[/green]")


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
        # Check for invalid characters
        invalid_chars = r'[\s~^:?*\[]'
        if re.search(invalid_chars, branch):
            raise ValueError(f"Branch name '{branch}' contains invalid characters (spaces, ~, ^, :, ?, *, [)")
        
        # Check for invalid patterns
        if ".." in branch:
            raise ValueError(f"Branch name cannot contain two consecutive dots (..)")
        
        if branch.startswith("/") or branch.endswith("/"):
            raise ValueError(f"Branch name cannot start or end with slash")
        
        if branch.endswith(".lock"):
            raise ValueError(f"Branch name cannot end with .lock")
        
        if "@{" in branch:
            raise ValueError(f"Branch name cannot contain @{{ sequence")
        
        # Additional Git ref validation
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
        
        # Strip whitespace
        slug = slug.strip()
        
        # Check for whitespace in slug
        if re.search(r'\s', slug):
            raise ValueError(f"SLUG '{slug}' contains whitespace. Please use a slug without spaces.")
        
        # Check for other invalid characters
        if re.search(r'[~^:?*\[\]\\]', slug):
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
            GitError: If uncommitted changes exist and stash=False
        """
        if repo.is_dirty(untracked_files=True):
            if stash:
                console.print("[yellow]Stashing uncommitted changes...[/yellow]")
                repo.git.stash("push", "-m", f"wtf auto-stash {datetime.now()}")
                return True
            else:
                raise GitCommandError(
                    "git status",
                    1,
                    stderr="You have uncommitted changes. Please commit or stash them first.\n"
                           "  To stash: git stash\n"
                           "  To see changes: git status\n"
                           "  Or use --stash flag to auto-stash"
                )
        return False


class GitWorkflowManager:
    """
    Main Git workflow manager using GitPython.
    
    This class contains all the Git workflow operations, merging functionality
    from both hl and hl.mk into a unified Python implementation.
    """
    
    def __init__(self, debug: bool = False, dry_run: bool = False, save_history: bool = False):
        """
        Initialize the workflow manager.
        
        Args:
            debug: Show debug output including bash commands
            dry_run: Preview mode without actual execution
            save_history: Save command history to file
        """
        self.debug = debug
        self.dry_run = dry_run
        self.save_history = save_history
        self.logger = BashCommandLogger(debug=debug, dry_run=dry_run)
        self.validator = SafetyValidator()
        
        # Initialize repository info
        self._init_repo_info()
    
    def _init_repo_info(self) -> None:
        """Initialize repository information and configuration."""
        try:
            # Find repository root
            self.logger.log("git rev-parse --show-toplevel", "Find repository root")
            self.repo = Repo(search_parent_directories=True)
            self.root = Path(self.repo.working_tree_dir)
            
            # Get repo name
            self.repo_name = self.root.name
            
            # Detect fork owner from origin URL
            self._detect_fork_owner()
            
            # Detect upstream repo
            self._detect_upstream_repo()
            
        except git.InvalidGitRepositoryError:
            console.print("[red]Not inside a Git repository[/red]")
            sys.exit(1)
    
    def _detect_fork_owner(self) -> None:
        """Detect fork owner from origin remote URL."""
        self.fork_owner = None
        
        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            self.logger.log("git remote get-url origin", "Get origin URL")
            
            # Parse owner from URL (works for SSH and HTTPS)
            match = re.search(r'(?:github\.com[:/])([^/]+)/.*', origin_url)
            if match:
                self.fork_owner = match.group(1)
        
        # Fallback to gh CLI if available
        if not self.fork_owner and shutil.which("gh"):
            try:
                result = self.logger.execute("gh api user -q .login", "Get GitHub username")
                if not self.dry_run and result.returncode == 0:
                    self.fork_owner = result.stdout.strip()
            except Exception:
                pass
    
    def _detect_upstream_repo(self) -> None:
        """Detect upstream repository from remote."""
        self.upstream_repo = RepoConfig.DEFAULT_UPSTREAM_REPO  # Default from config
        
        if RepoConfig.UPSTREAM_REMOTE in self.repo.remotes:
            upstream_url = self.repo.remote("upstream").url
            self.logger.log("git remote get-url upstream", "Get upstream URL")
            
            # Parse repo from URL
            match = re.search(r'(?:github\.com[:/])([^/]+/[^/.]+)', upstream_url)
            if match:
                self.upstream_repo = match.group(1).replace(".git", "")
    
    def _get_worktree_path(self, slug: str) -> Path:
        """
        Get the worktree path for a given slug.
        
        Args:
            slug: Feature slug
            
        Returns:
            Path to worktree directory
        """
        return self.root.parent / "wt" / self.repo_name / slug
    
    # ========== Repository Setup Commands ==========
    
    def doctor(self) -> None:
        """
        Print detected settings and sanity-check environment.
        
        Bash equivalents:
            git rev-parse --show-toplevel
            git remote get-url origin
            git remote get-url upstream
            command -v gh
        """
        console.print(Panel.fit("[bold]Environment Check[/bold]", style="cyan"))
        
        # Create status table
        table = Table(show_header=False, box=None)
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        
        table.add_row("Repo root:", str(self.root))
        table.add_row("Repo name:", self.repo_name)
        table.add_row("Upstream repo:", self.upstream_repo)
        table.add_row("Fork owner:", self.fork_owner or "[red]Not detected[/red]")
        
        # Check remotes
        origin_url = self.repo.remote("origin").url if "origin" in self.repo.remotes else "[red]Missing[/red]"
        upstream_url = self.repo.remote("upstream").url if "upstream" in self.repo.remotes else "[red]Missing[/red]"
        
        table.add_row("Origin URL:", origin_url)
        table.add_row("Upstream URL:", upstream_url)
        
        # Check tools
        has_gh = "✓" if shutil.which("gh") else "✗"
        table.add_row("Has gh CLI:", f"[green]{has_gh}[/green]" if has_gh == "✓" else f"[red]{has_gh}[/red]")
        
        # Check current branch
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            # HEAD is detached
            current_branch = f"(detached) {self.repo.head.commit.hexsha[:7]}"
        table.add_row("Current branch:", current_branch)
        
        # Check if dirty
        is_dirty = "Yes" if self.repo.is_dirty() else "No"
        table.add_row("Has changes:", f"[yellow]{is_dirty}[/yellow]" if is_dirty == "Yes" else is_dirty)
        
        console.print(table)
        
        # Check for issues
        issues = []
        if "origin" not in self.repo.remotes:
            issues.append("Missing 'origin' remote (your fork)")
        if "upstream" not in self.repo.remotes:
            issues.append("Missing 'upstream' remote. Run: wtf upstream-add")
        if not self.fork_owner:
            issues.append("Could not detect fork owner")
        if not shutil.which("gh"):
            issues.append("GitHub CLI not found. Install from: https://cli.github.com/")
        
        if issues:
            console.print("\n[yellow]Issues found:[/yellow]")
            for issue in issues:
                console.print(f"  • {issue}")
        else:
            console.print("\n[green]✓ Environment check passed[/green]")
    
    def upstream_add(self, repo_upstream: Optional[str] = None, update: bool = False) -> None:
        """
        Add or update upstream remote.
        
        Bash equivalents:
            git remote add upstream git@github.com:{repo}.git
            git remote set-url upstream git@github.com:{repo}.git
            git config pull.ff only
        
        Args:
            repo_upstream: Override upstream repo (format: owner/repo)
            update: Force update existing upstream
        """
        if repo_upstream:
            # Validate format
            if not re.match(r'^[^/]+/[^/]+$', repo_upstream):
                raise ValueError(f"REPO_UPSTREAM must be in 'owner/repo' format. Got: '{repo_upstream}'")
            self.upstream_repo = repo_upstream
        
        # Detect URL type from origin (SSH vs HTTPS)
        url_type = "SSH"
        upstream_url = f"git@github.com:{self.upstream_repo}.git"
        
        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            if origin_url.startswith("https://"):
                url_type = "HTTPS"
                upstream_url = f"https://github.com/{self.upstream_repo}.git"
        
        # Check existing upstream
        if "upstream" in self.repo.remotes:
            existing_url = self.repo.remote("upstream").url
            console.print(f"Current upstream: {existing_url}")
            
            if existing_url == upstream_url:
                console.print("[green]✓ Upstream already correctly set[/green]")
            elif update:
                console.print(f"Updating upstream to: {upstream_url} ({url_type})")
                self.logger.log(f'git remote set-url upstream "{upstream_url}"')
                if not self.dry_run:
                    self.repo.remote("upstream").set_url(upstream_url)
                console.print("[green]✓ Updated upstream remote[/green]")
            else:
                console.print(f"\nTo update upstream to {upstream_url}, run:")
                console.print("  wtf upstream-add --update")
                console.print(f"Or manually: git remote set-url upstream {upstream_url}")
                sys.exit(1)
        else:
            # Add new upstream
            console.print(f"Adding upstream: {upstream_url} ({url_type})")
            self.logger.log(f'git remote add upstream "{upstream_url}"')
            if not self.dry_run:
                self.repo.create_remote("upstream", upstream_url)
            console.print("[green]✓ Added upstream remote[/green]")
        
        # Configure pull.ff
        self.logger.log("git config pull.ff only")
        if not self.dry_run:
            try:
                with self.repo.config_writer() as config:
                    config.set_value("pull", "ff", "only")
            except Exception as e:
                console.print(f"[yellow]Warning: Could not set pull.ff config: {e}[/yellow]")
        console.print("[green]✓ Configured pull.ff=only[/green]")
        
        # Show remotes
        console.print("\nRemotes:")
        if not self.dry_run:
            for remote in self.repo.remotes:
                console.print(f"  {remote.name}: {remote.url}")
    
    def fork_setup(self) -> None:
        """
        Create fork if needed and set up remotes.
        
        Bash equivalents:
            gh api user -q .login
            gh repo view {user}/humanlayer --json name
            gh repo fork {upstream} --clone=false
            git remote rename origin upstream
            git remote add origin git@github.com:{user}/{repo}.git
        
        Requires gh CLI to be installed and authenticated.
        """
        # Check gh CLI
        if not shutil.which("gh"):
            console.print("[red]GitHub CLI required. Install from: https://cli.github.com/[/red]")
            sys.exit(1)
        
        console.print("[cyan]Setting up fork...[/cyan]")
        
        # Get GitHub username
        result = self.logger.execute("gh api user -q .login", "Get GitHub username")
        if self.dry_run:
            github_user = "YOUR_USERNAME"
        else:
            if result.returncode != 0:
                console.print("[red]Not authenticated. Run: gh auth login[/red]")
                sys.exit(1)
            github_user = result.stdout.strip()
        
        console.print(f"GitHub user: {github_user}")
        
        # Extract repo name from upstream
        repo_name = self.upstream_repo.split("/")[1]
        
        # Check if fork exists
        fork_check_cmd = f'gh repo view "{github_user}/{repo_name}" --json name 2>/dev/null'
        result = self.logger.execute(fork_check_cmd, "Check if fork exists", check=False)
        
        if result.returncode != 0:
            # Create fork
            console.print("Creating fork...")
            fork_cmd = f'gh repo fork "{self.upstream_repo}" --clone=false'
            self.logger.execute(fork_cmd, "Create fork")
            console.print(f"[green]Fork created: {github_user}/{repo_name}[/green]")
        else:
            console.print(f"[green]Fork already exists: {github_user}/{repo_name}[/green]")
        
        # Fix remotes
        console.print("\nConfiguring remotes...")
        
        # Check current origin
        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            if self.upstream_repo in origin_url:
                # Origin points to upstream, need to fix
                if "upstream" not in self.repo.remotes:
                    console.print("Renaming origin to upstream...")
                    self.logger.log("git remote rename origin upstream")
                    if not self.dry_run:
                        self.repo.remote("origin").rename("upstream")
                else:
                    console.print("Removing duplicate origin...")
                    self.logger.log("git remote remove origin")
                    if not self.dry_run:
                        self.repo.delete_remote("origin")
        
        # Add fork as origin
        fork_url = f"git@github.com:{github_user}/{repo_name}.git"
        if "origin" not in self.repo.remotes:
            console.print("Adding fork as origin...")
            self.logger.log(f'git remote add origin "{fork_url}"')
            if not self.dry_run:
                self.repo.create_remote("origin", fork_url)
        else:
            # Update origin if needed
            current_origin = self.repo.remote("origin").url
            if github_user not in current_origin:
                self.logger.log(f'git remote set-url origin "{fork_url}"')
                if not self.dry_run:
                    self.repo.remote("origin").set_url(fork_url)
        
        # Ensure upstream is set correctly
        if "upstream" not in self.repo.remotes:
            upstream_url = f"git@github.com:{self.upstream_repo}.git"
            self.logger.log(f'git remote add upstream "{upstream_url}"')
            if not self.dry_run:
                self.repo.create_remote("upstream", upstream_url)
        
        # Show final configuration
        console.print("\n[green]Final remote configuration:[/green]")
        if not self.dry_run:
            for remote in self.repo.remotes:
                console.print(f"  {remote.name}: {remote.url}")
        
        console.print("\n[green]Fork setup complete![/green]")
        console.print("You can now:")
        console.print("  • Push to your fork: git push origin <branch>")
        console.print("  • Pull from upstream: git pull upstream main")
        console.print("  • Create PRs: wtf wt-pr SLUG")
    
    # ========== Sync Operations ==========
    
    def sync_main(self, base: str = "main", confirm: bool = False) -> None:
        """
        Fast-forward sync fork's main with upstream/main.
        
        Bash equivalents:
            git diff --quiet && git diff --cached --quiet  # Check for changes
            git fetch upstream
            git log --oneline main..upstream/main  # Show new commits
            git switch main
            git merge --ff-only upstream/main
            git push origin main
        
        Args:
            base: Base branch name (default: main)
            confirm: Skip confirmation prompts
        """
        console.print(f"[cyan]Syncing {base} with upstream...[/cyan]")
        
        # Check for uncommitted changes
        self.validator.check_uncommitted_changes(self.repo, stash=False)
        
        # Check current branch
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None  # HEAD is detached
        if current_branch and current_branch != base:
            console.print(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")
        
        # Fetch upstream
        console.print("Fetching upstream...")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("upstream").fetch()
        
        # Show what's new
        self.logger.log(f"git log --oneline {base}..upstream/{base}", "Show new commits")
        if not self.dry_run:
            try:
                new_commits = list(self.repo.iter_commits(f"{base}..upstream/{base}"))
                if new_commits:
                    console.print(f"\nNew commits from upstream/{base}:")
                    for commit in new_commits[:10]:
                        console.print(f"  {commit.hexsha[:7]} {commit.summary}")
                    if len(new_commits) > 10:
                        console.print(f"  ... and {len(new_commits) - 10} more")
                else:
                    console.print("[green]Already up-to-date[/green]")
                    return
            except Exception:
                pass
        
        # Switch to base branch
        self.logger.log(f"git switch {base}")
        if not self.dry_run:
            self.repo.heads[base].checkout()
        
        # Attempt fast-forward merge
        console.print(f"Fast-forwarding {base}...")
        self.logger.log(f"git merge --ff-only upstream/{base}")
        
        if not self.dry_run:
            try:
                # Check if fast-forward is possible
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(self.repo.head.commit, upstream_ref.commit)
                
                if merge_base[0] != self.repo.head.commit:
                    raise GitCommandError(
                        "git merge",
                        1,
                        stderr=f"Cannot fast-forward {base} to upstream/{base}\n"
                               f"Your {base} has diverged from upstream.\n"
                               "Options:\n"
                               f"  1. If you want to force-sync (DESTRUCTIVE):\n"
                               f"     wtf sync-main-force --confirm\n"
                               f"  2. To see the differences:\n"
                               f"     git log --oneline upstream/{base}..{base}"
                    )
                
                # Perform fast-forward
                self.repo.head.reset(upstream_ref.commit, index=True, working_tree=True)
                
            except GitCommandError as e:
                console.print(f"[red]ERROR: {e.stderr}[/red]")
                sys.exit(1)
        
        # Push to origin
        console.print(f"Pushing to origin/{base}...")
        self.logger.log(f"git push origin {base}")
        if not self.dry_run:
            self.repo.remote("origin").push(base)
        
        console.print(f"[green]✓ Fork {base} fast-forwarded to upstream/{base}[/green]")
    
    def sync_main_force(self, base: str = "main", confirm: bool = False, force: bool = False) -> None:
        """
        Force-sync fork main with upstream (creates backup).
        
        Bash equivalents:
            git branch backup/main-{timestamp}
            git fetch upstream
            git reset --hard upstream/main
            git push --force-with-lease origin main
        
        Args:
            base: Base branch name
            confirm: Skip confirmation
            force: Force even with uncommitted changes
        """
        if not confirm:
            console.print(f"[red]WARNING: This will DESTROY any local commits on {base} not in upstream![/red]")
            
            # Show what will be lost
            self.logger.log(f"git log --oneline upstream/{base}..{base}", "Show commits to be lost")
            if not self.dry_run:
                try:
                    lost_commits = list(self.repo.iter_commits(f"upstream/{base}..{base}"))
                    if lost_commits:
                        console.print(f"\nCurrent {base} commits that will be LOST:")
                        for commit in lost_commits[:10]:
                            console.print(f"  {commit.hexsha[:7]} {commit.summary}")
                    else:
                        console.print("  (none)")
                except Exception:
                    pass
            
            console.print("\nTo proceed, run:")
            console.print("  wtf sync-main-force --confirm")
            sys.exit(1)
        
        # Check current branch
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None  # HEAD is detached
        if current_branch != base:
            if current_branch:
                console.print(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")
            else:
                console.print(f"[yellow]WARNING: HEAD is detached, switching to '{base}'[/yellow]")
            self.logger.log(f"git switch {base}")
            if not self.dry_run:
                self.repo.heads[base].checkout()
        
        # Check for uncommitted changes
        if self.repo.is_dirty() and not force:
            console.print("[red]ERROR: You have uncommitted changes that will be LOST![/red]")
            console.print("  To see changes: git status")
            console.print("  To force anyway: wtf sync-main-force --confirm --force")
            sys.exit(1)
        
        # Create backup branch
        backup_branch = f"backup/{base}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        console.print(f"Creating backup branch: {backup_branch}")
        self.logger.log(f"git branch {backup_branch}")
        if not self.dry_run:
            self.repo.create_head(backup_branch)
        
        # Fetch and reset
        console.print("Fetching upstream...")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("upstream").fetch()
        
        console.print(f"Resetting {base} to upstream/{base}...")
        self.logger.log(f"git reset --hard upstream/{base}")
        if not self.dry_run:
            upstream_ref = self.repo.remote("upstream").refs[base]
            self.repo.head.reset(upstream_ref.commit, index=True, working_tree=True)
        
        console.print("Force-pushing to origin...")
        self.logger.log(f"git push --force-with-lease origin {base}")
        if not self.dry_run:
            self.repo.remote("origin").push(f"{base}:{base}", force=True)
        
        console.print(f"[green]✓ Fork {base} hard-reset to upstream/{base} and force-pushed[/green]")
        console.print(f"[green]✓ Previous state backed up to: {backup_branch}[/green]")
        console.print(f"\nTo restore the backup: git switch {backup_branch}")
    
    def zero_ffsync(self, base: str = "main") -> None:
        """
        Fast-forward push without checkout: origin/main <- upstream/main.
        
        Bash equivalents:
            git fetch origin
            git fetch upstream
            git rev-list origin/main..main  # Check unpushed commits
            git merge-base --is-ancestor origin/main upstream/main
            git push origin upstream/main:main
        
        Args:
            base: Base branch name
        """
        console.print(f"[cyan]Zero-checkout fast-forward sync of {base}...[/cyan]")
        
        # Check for unpushed local commits
        console.print(f"Checking local {base} status...")
        self.logger.log("git fetch origin")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("origin").fetch()
            self.repo.remote("upstream").fetch()
        
        # Check if local base has unpushed commits
        if base in self.repo.heads:
            self.logger.log(f"git rev-list origin/{base}..{base}", "Check unpushed commits")
            if not self.dry_run:
                try:
                    unpushed = list(self.repo.iter_commits(f"origin/{base}..{base}"))
                    if unpushed:
                        console.print(f"[red]ERROR: Your local {base} has {len(unpushed)} unpushed commit(s)[/red]")
                        console.print(f"These would be lost if origin/{base} is updated directly.")
                        console.print("\nOptions:")
                        console.print("  1. Push your local commits first:")
                        console.print(f"     git push origin {base}")
                        console.print("  2. Use sync-main instead (will checkout and merge):")
                        console.print("     wtf sync-main")
                        console.print("  3. If you want to discard local commits:")
                        console.print("     wtf sync-main-force --confirm")
                        sys.exit(1)
                except Exception:
                    pass
        
        # Check if fast-forward is possible
        console.print(f"Checking if origin/{base} can fast-forward to upstream/{base}...")
        self.logger.log(f"git merge-base --is-ancestor origin/{base} upstream/{base}")
        
        if not self.dry_run:
            try:
                origin_ref = self.repo.remote("origin").refs[base]
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(origin_ref.commit, upstream_ref.commit)
                
                if merge_base[0] != origin_ref.commit:
                    console.print(f"[red]ERROR: Cannot fast-forward origin/{base} to upstream/{base}[/red]")
                    console.print(f"origin/{base} has diverged from upstream/{base}")
                    console.print("\nTo see the divergence:")
                    console.print(f"  git log --oneline --graph upstream/{base} origin/{base}")
                    console.print("\nTo force-sync (DESTRUCTIVE):")
                    console.print("  wtf sync-main-force --confirm")
                    sys.exit(1)
                
                # Show new commits
                new_commits = list(self.repo.iter_commits(f"{origin_ref.commit}..{upstream_ref.commit}"))
                if new_commits:
                    console.print("\nNew commits to be synced:")
                    for commit in new_commits[:10]:
                        console.print(f"  {commit.hexsha[:7]} {commit.summary}")
                else:
                    console.print("[green]Already up-to-date[/green]")
                    return
                
            except Exception as e:
                console.print(f"[red]ERROR: {str(e)}[/red]")
                sys.exit(1)
        
        # Perform the push
        console.print("Syncing...")
        self.logger.log(f"git push origin upstream/{base}:{base}")
        if not self.dry_run:
            try:
                self.repo.remote("origin").push(f"upstream/{base}:{base}")
                console.print(f"[green]✓ Successfully fast-forwarded origin/{base} to upstream/{base}[/green]")
            except GitCommandError as e:
                console.print("[red]ERROR: Push failed. This might happen if:[/red]")
                console.print(f"  - Someone else pushed to origin/{base} in the meantime")
                console.print("  - You don't have push permissions")
                console.print("  Try: wtf sync-main")
                sys.exit(1)
    
    # ========== Worktree Management ==========
    
    def wt_new(self, slug: str, base: str = "main") -> None:
        """
        Create worktree and new feature branch from fork/main.
        
        Bash equivalents:
            git worktree add {path} -b feat/{slug} {base}
            git worktree add {path} {branch}  # if branch exists
        
        Args:
            slug: Feature slug
            base: Base branch to branch from
        """
        # Validate and clean slug
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        
        # Validate branch name
        self.validator.validate_branch_name(branch_name)
        
        console.print(f"[cyan]Creating worktree for {branch_name}...[/cyan]")
        
        # Sync main first
        self.sync_main(base=base)
        
        # Get worktree path
        worktree_path = self._get_worktree_path(slug)
        
        # Check if worktree already exists
        if worktree_path.exists():
            # Check if it's a valid worktree
            try:
                wt_check = self.logger.execute(
                    f'git worktree list --porcelain | grep "^worktree.*{worktree_path}"',
                    "Check if path is a worktree",
                    check=False
                )
                if wt_check.returncode == 0:
                    console.print(f"[green]✓ Worktree already exists at: {worktree_path}[/green]")
                    console.print(f"  Branch: {branch_name}")
                    console.print(f"  To use it: cd {worktree_path}")
                    console.print(f"  To remove it: wtf wt-clean {slug}")
                    return
            except Exception:
                pass
            
            console.print(f"[red]ERROR: Directory exists but is not a git worktree: {worktree_path}[/red]")
            console.print("  Remove it manually or choose a different SLUG")
            sys.exit(1)
        
        # Create worktree
        if branch_name in self.repo.heads:
            # Branch exists, use it
            console.print(f"Branch {branch_name} already exists locally, using it for worktree")
            cmd = f'git worktree add "{worktree_path}" "{branch_name}"'
        else:
            # Create new branch
            console.print(f"Creating new branch {branch_name} from {base}")
            cmd = f'git worktree add "{worktree_path}" -b "{branch_name}" "{base}"'
        
        self.logger.execute(cmd, "Create worktree")
        
        if not self.dry_run:
            console.print(f"[green]✓ Created worktree: {worktree_path}[/green]")
            console.print(f"[green]✓ Branch: {branch_name}[/green]")
            console.print(f"\nNext steps:")
            console.print(f"  cd {worktree_path}")
            console.print(f"  # Make your changes")
            console.print(f"  git add -A && git commit -m 'feat: {slug}'")
            console.print(f"  wtf wt-publish {slug}")
    
    def wt_publish(self, slug: str) -> None:
        """
        Push worktree feature branch to origin and set upstream.
        
        Bash equivalents:
            git push -u origin feat/{slug}
        
        Args:
            slug: Feature slug
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)
        
        console.print(f"[cyan]Publishing {branch_name}...[/cyan]")
        
        # Determine if we're in the worktree or parent repo
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None  # HEAD is detached
        
        if current_branch == branch_name:
            # Running from worktree
            console.print(f"Running from worktree for branch {branch_name}")
            git_dir = "."
        elif worktree_path.exists():
            # Running from parent, check worktree exists
            console.print(f"Running from parent repo, targeting worktree at {worktree_path}")
            git_dir = str(worktree_path)
        else:
            console.print("[red]ERROR: Worktree not found[/red]")
            console.print(f"  Expected worktree: {worktree_path}")
            console.print(f"  Current branch: {current_branch}")
            console.print(f"  Run 'wtf wt-new {slug}' first")
            sys.exit(1)
        
        # Push to origin
        cmd = f'git -C "{git_dir}" push -u origin "{branch_name}"'
        self.logger.execute(cmd, "Push branch to origin")
        
        if not self.dry_run:
            console.print(f"[green]✓ Published branch {branch_name} to origin and set upstream[/green]")
    
    def wt_pr(self, slug: str, base: str = "main", title: Optional[str] = None, 
              body: Optional[str] = None, draft: bool = False) -> None:
        """
        Open PR from fork feature to upstream/main.
        
        Bash equivalents:
            gh pr list --repo {upstream} --head {owner}:{branch}
            gh pr create --repo {upstream} --head {owner}:{branch} 
                         --base {base} --title "{title}" --body "{body}"
        
        Args:
            slug: Feature slug
            base: Base branch for PR (default: main)
            title: PR title (auto-generated if not provided)
            body: PR body (auto-generated if not provided)
            draft: Create as draft PR
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        
        if not self.fork_owner:
            console.print("[red]Could not determine fork owner[/red]")
            sys.exit(1)
        
        if not shutil.which("gh"):
            console.print("[red]GitHub CLI required. Install from: https://cli.github.com/[/red]")
            sys.exit(1)
        
        console.print(f"[cyan]Creating PR for {branch_name}...[/cyan]")
        
        # Check for existing PR
        console.print("Checking for existing PR...")
        check_cmd = (f'gh pr list --repo "{self.upstream_repo}" '
                    f'--head "{self.fork_owner}:{branch_name}" '
                    f'--json number,url,state')
        result = self.logger.execute(check_cmd, "Check for existing PR", check=False)
        
        if not self.dry_run and result.returncode == 0 and result.stdout.strip() != "[]":
            import json
            pr_data = json.loads(result.stdout)[0]
            console.print(f"[green]✓ PR already exists (#{pr_data['number']}) - State: {pr_data['state']}[/green]")
            console.print(f"  URL: {pr_data['url']}")
            console.print(f"  View: gh pr view {pr_data['number']} --repo {self.upstream_repo}")
            return
        
        # Check if branch needs to be pushed
        console.print("Checking if branch needs to be pushed...")
        
        # Try to get worktree path
        worktree_path = self._get_worktree_path(slug)
        if worktree_path.exists():
            git_dir = str(worktree_path)
        else:
            git_dir = "."
        
        # Fetch and check if branch exists on origin
        self.logger.execute(f'git -C "{git_dir}" fetch origin', "Fetch origin", check=False)
        
        check_remote = self.logger.execute(
            f'git -C "{git_dir}" rev-parse --verify "origin/{branch_name}"',
            "Check if branch exists on origin",
            check=False
        )
        
        if check_remote.returncode != 0:
            console.print("Branch not on origin, pushing first...")
            self.logger.execute(f'git -C "{git_dir}" push -u origin "{branch_name}"', "Push branch")
        else:
            # Check for unpushed commits
            unpushed_check = self.logger.execute(
                f'git -C "{git_dir}" rev-list --count "origin/{branch_name}..{branch_name}"',
                "Check unpushed commits",
                check=False
            )
            if not self.dry_run and unpushed_check.stdout and int(unpushed_check.stdout.strip() or 0) > 0:
                console.print("Unpushed commits found, pushing...")
                self.logger.execute(f'git -C "{git_dir}" push origin "{branch_name}"', "Push commits")
        
        # Generate PR title and body if not provided
        if not title or title == f"feat: {slug}":
            # Try to use last commit message
            result = self.logger.execute(
                f'git -C "{git_dir}" log -1 --pretty=format:"%s"',
                "Get last commit message",
                check=False
            )
            if not self.dry_run and result.stdout:
                title = result.stdout.strip()
            else:
                title = f"feat: {slug}"
        
        if not body or body == "Summary, rationale, tests":
            # Generate body from commits
            result = self.logger.execute(
                f'git -C "{git_dir}" log "upstream/{base}..HEAD" --pretty=format:"- %s"',
                "Get commit messages",
                check=False
            )
            if not self.dry_run and result.stdout:
                body = f"## Changes\n\n{result.stdout}\n\n## Testing\n\n- [ ] Tests pass\n- [ ] Manual testing completed"
            else:
                body = "## Summary\n\nAdd description here\n\n## Testing\n\n- [ ] Tests pass"
        
        # Create PR
        draft_flag = "--draft" if draft else ""
        create_type = "draft PR" if draft else "PR"
        console.print(f"Creating {create_type}...")
        
        # Escape quotes in title and body to prevent shell injection
        title_escaped = title.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        body_escaped = body.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
        
        # Use heredoc for body to handle multiline content
        pr_cmd = f'''gh pr create \\
            --repo "{self.upstream_repo}" \\
            --head "{self.fork_owner}:{branch_name}" \\
            --base "{base}" \\
            --title "{title_escaped}" \\
            --body "{body_escaped}" \\
            {draft_flag}'''
        
        result = self.logger.execute(pr_cmd, f"Create {create_type}")
        
        if not self.dry_run:
            if result.returncode == 0:
                console.print(f"[green]✓ {create_type.capitalize()} created successfully[/green]")
                if result.stdout:
                    console.print(f"  URL: {result.stdout.strip()}")
            else:
                console.print("[red]ERROR: Failed to create PR[/red]")
                if result.stderr:
                    console.print(result.stderr)
                sys.exit(1)
    
    def wt_update(self, slug: str, base: str = "main", stash: bool = False,
                  dry_run_preview: bool = False, merge: bool = False,
                  no_backup: bool = False) -> None:
        """
        Rebase or merge worktree feature on upstream/main and push.
        
        Bash equivalents:
            git fetch upstream
            git rev-list --count HEAD..upstream/main  # commits behind
            git rev-list --count upstream/main..HEAD  # commits ahead
            git stash push -m "auto-stash"  # if stash=True
            git branch backup/feat/{slug}-{timestamp}  # unless no_backup
            git rebase upstream/main  # or git merge upstream/main
            git push --force-with-lease origin feat/{slug}
        
        Args:
            slug: Feature slug
            base: Base branch name
            stash: Auto-stash uncommitted changes
            dry_run_preview: Preview what would happen
            merge: Use merge instead of rebase
            no_backup: Skip backup branch creation
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)
        
        console.print(f"[cyan]Updating {branch_name} with upstream/{base}...[/cyan]")
        
        # Determine working directory
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None  # HEAD is detached
        if current_branch == branch_name:
            git_dir = "."
        elif worktree_path.exists():
            git_dir = str(worktree_path)
        else:
            console.print(f"[red]ERROR: Worktree not found. Run 'wtf wt-new {slug}' first[/red]")
            sys.exit(1)
        
        # Fetch latest
        console.print("Fetching latest from upstream...")
        self.logger.execute("git fetch upstream", "Fetch upstream")
        
        # Check status
        console.print("\n=== Current Status ===")
        behind_cmd = f'git -C "{git_dir}" rev-list --count "HEAD..upstream/{base}"'
        ahead_cmd = f'git -C "{git_dir}" rev-list --count "upstream/{base}..HEAD"'
        
        behind_result = self.logger.execute(behind_cmd, "Check commits behind", check=False)
        ahead_result = self.logger.execute(ahead_cmd, "Check commits ahead", check=False)
        
        commits_behind = int(behind_result.stdout.strip() or 0) if (not self.dry_run and behind_result.stdout) else 0
        commits_ahead = int(ahead_result.stdout.strip() or 0) if (not self.dry_run and ahead_result.stdout) else 0
        
        console.print(f"Branch {branch_name} is:")
        console.print(f"  {commits_behind} commits behind upstream/{base}")
        console.print(f"  {commits_ahead} commits ahead of upstream/{base}")
        
        if commits_behind == 0:
            console.print(f"[green]✓ Already up-to-date with upstream/{base}[/green]")
            if commits_ahead > 0:
                console.print(f"Your branch has unpushed commits. Push with: wtf wt-publish {slug}")
            return
        
        if dry_run_preview:
            console.print("\n[yellow]=== DRY RUN MODE ===[/yellow]")
            console.print(f"Would update {branch_name} with {commits_behind} new commits from upstream/{base}")
            console.print(f"Your {commits_ahead} local commits would be replayed on top")
            if commits_ahead > 0:
                console.print("\nYour commits to be rebased:")
                log_cmd = f'git -C "{git_dir}" log --oneline "upstream/{base}..HEAD"'
                self.logger.execute(log_cmd, "Show commits to rebase")
            return
        
        # Check for uncommitted changes
        status_cmd = f'git -C "{git_dir}" status --porcelain'
        status_result = self.logger.execute(status_cmd, "Check for changes", check=False)
        has_uncommitted = bool(status_result.stdout.strip()) if (not self.dry_run and status_result.stdout) else False
        
        stashed = False
        if has_uncommitted:
            if stash:
                console.print("Stashing uncommitted changes...")
                stash_cmd = f'git -C "{git_dir}" stash push -m "wt-update auto-stash for {branch_name}"'
                self.logger.execute(stash_cmd, "Stash changes")
                stashed = True
            else:
                console.print("[red]ERROR: You have uncommitted changes. Either:[/red]")
                console.print("  1. Commit your changes first")
                console.print("  2. Run with --stash to auto-stash")
                console.print("  3. Manually stash: git stash")
                sys.exit(1)
        
        # Create backup branch
        backup_branch = None  # Initialize for later reference
        if not no_backup and commits_ahead > 0:
            backup_branch = f"backup/{branch_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            console.print(f"Creating backup branch: {backup_branch}")
            backup_cmd = f'git -C "{git_dir}" branch "{backup_branch}"'
            self.logger.execute(backup_cmd, "Create backup", check=False)
        
        # Perform update
        if merge:
            console.print(f"\nMerging upstream/{base} into {branch_name}...")
            update_cmd = f'git -C "{git_dir}" merge "upstream/{base}"'
            result = self.logger.execute(update_cmd, "Merge upstream", check=False)
        else:
            console.print(f"\nRebasing {branch_name} onto upstream/{base}...")
            update_cmd = f'git -C "{git_dir}" rebase "upstream/{base}"'
            result = self.logger.execute(update_cmd, "Rebase onto upstream", check=False)
        
        if not self.dry_run and result.returncode != 0:
            operation = "Merge" if merge else "Rebase"
            console.print(f"[red]ERROR: {operation} conflicts detected![/red]")
            console.print("Resolve conflicts, then:")
            console.print("  git add <resolved-files>")
            if merge:
                console.print("  git merge --continue")
            else:
                console.print("  git rebase --continue")
                console.print("Or abort with: git rebase --abort")
            if backup_branch:
                console.print(f"Your original branch is backed up as: {backup_branch}")
            sys.exit(1)
        
        # Push to origin
        console.print("Pushing to origin...")
        if merge:
            push_cmd = f'git -C "{git_dir}" push origin "{branch_name}"'
        else:
            push_cmd = f'git -C "{git_dir}" push --force-with-lease origin "{branch_name}"'
        
        result = self.logger.execute(push_cmd, "Push to origin", check=False)
        
        if not self.dry_run and result.returncode != 0:
            console.print("[red]ERROR: Push failed. Remote may have been updated.[/red]")
            console.print(f"If you're sure, use: git push --force origin {branch_name}")
            sys.exit(1)
        
        # Restore stash if needed
        if stashed:
            console.print("Restoring stashed changes...")
            pop_cmd = f'git -C "{git_dir}" stash pop'
            self.logger.execute(pop_cmd, "Restore stash", check=False)
        
        console.print(f"[green]✓ Successfully updated {branch_name} with upstream/{base}[/green]")
    
    def wt_clean(self, slug: str, force_delete: bool = False, wt_force: bool = False,
                 dry_run_preview: bool = False, confirm: bool = False) -> None:
        """
        Remove worktree and prune branches.
        
        Bash equivalents:
            git worktree remove {path}  # or --force
            git branch -d feat/{slug}   # or -D
            git push origin --delete feat/{slug}
            git remote prune origin
            git worktree prune
        
        Args:
            slug: Feature slug
            force_delete: Force delete branch even if not merged
            wt_force: Force remove worktree with uncommitted changes
            dry_run_preview: Preview what would be deleted
            confirm: Skip confirmation prompts
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)
        
        console.print(f"[cyan]=== Worktree Clean Summary ===[/cyan]")
        console.print(f"Branch:       {branch_name}")
        console.print(f"Worktree:     {worktree_path}")
        console.print("")
        
        # Check what exists
        has_worktree = worktree_path.exists()
        has_local_branch = branch_name in self.repo.heads
        has_remote_branch = False
        has_uncommitted = False
        has_pr = False
        
        # Check worktree
        if has_worktree:
            console.print(f"✓ Worktree exists at {worktree_path}")
            
            # Check for uncommitted changes
            status_cmd = f'git -C "{worktree_path}" status --porcelain'
            result = self.logger.execute(status_cmd, "Check for changes", check=False)
            if not self.dry_run and result.stdout:
                has_uncommitted = True
                console.print("[yellow]⚠️  Has uncommitted changes:[/yellow]")
                for line in result.stdout.strip().split('\n')[:5]:
                    console.print(f"  {line}")
        else:
            console.print(f"✗ No worktree at {worktree_path}")
        
        # Check local branch
        if has_local_branch:
            console.print(f"✓ Local branch {branch_name} exists")
        
        # Check remote branch
        check_remote = self.logger.execute(
            f'git ls-remote --exit-code --heads origin "{branch_name}"',
            "Check remote branch",
            check=False
        )
        if check_remote.returncode == 0:
            has_remote_branch = True
            console.print(f"✓ Remote branch origin/{branch_name} exists")
        
        # Check for PR
        if shutil.which("gh") and self.fork_owner:
            pr_check = self.logger.execute(
                f'gh pr list --repo "{self.upstream_repo}" '
                f'--head "{self.fork_owner}:{branch_name}" '
                f'--json number,state',
                "Check for PR",
                check=False
            )
            if not self.dry_run and pr_check.returncode == 0 and pr_check.stdout.strip() != "[]":
                import json
                pr_data = json.loads(pr_check.stdout)[0]
                has_pr = True
                console.print(f"[yellow]⚠️  Has PR #{pr_data['number']} ({pr_data['state']})[/yellow]")
        
        # Dry run mode
        if dry_run_preview:
            console.print("\n[yellow]=== DRY RUN MODE - No changes will be made ===[/yellow]")
            console.print("Would perform:")
            if has_worktree:
                console.print(f"  - Remove worktree at {worktree_path}")
            if has_local_branch:
                console.print(f"  - Delete local branch {branch_name}")
            if has_remote_branch:
                console.print(f"  - Delete remote branch origin/{branch_name}")
            console.print("  - Prune remote references")
            return
        
        # Safety checks
        if has_uncommitted and not wt_force:
            console.print("[red]ERROR: Worktree has uncommitted changes. Use --wt-force to force removal.[/red]")
            sys.exit(1)
        
        if has_pr and not confirm:
            console.print("[yellow]WARNING: This branch has an open PR. Are you sure you want to delete it?[/yellow]")
            console.print("Use --confirm to proceed anyway.")
            sys.exit(1)
        
        # Check if we're in the worktree being cleaned
        current_dir = Path.cwd()
        if current_dir == worktree_path or worktree_path in current_dir.parents:
            console.print("[red]ERROR: Cannot remove worktree while inside it.[/red]")
            console.print("Please cd to parent repo or another directory first.")
            sys.exit(1)
        
        # Confirmation
        if not confirm and (has_worktree or has_local_branch or has_remote_branch):
            console.print("\nThis will:")
            if has_worktree:
                console.print(f"  - Remove worktree at {worktree_path}")
            if has_local_branch:
                console.print(f"  - Delete local branch {branch_name}")
            if has_remote_branch:
                console.print(f"  - Delete remote branch origin/{branch_name}")
            console.print("\nRun with --confirm to proceed, or --dry-run to preview.")
            sys.exit(1)
        
        # Perform cleanup
        console.print("\n[cyan]=== Cleaning ===[/cyan]")
        
        if has_worktree:
            console.print("Removing worktree...")
            force_flag = "--force" if wt_force else ""
            rm_cmd = f'git worktree remove {force_flag} "{worktree_path}"'
            self.logger.execute(rm_cmd, "Remove worktree")
        
        if has_local_branch:
            console.print("Deleting local branch...")
            delete_flag = "-D" if force_delete else "-d"
            del_cmd = f'git branch {delete_flag} "{branch_name}"'
            self.logger.execute(del_cmd, "Delete branch", check=False)
        
        if has_remote_branch:
            console.print("Deleting remote branch...")
            push_cmd = f'git push origin --delete "{branch_name}"'
            self.logger.execute(push_cmd, "Delete remote branch", check=False)
        
        # Prune references
        console.print("Pruning remote references...")
        self.logger.execute("git remote prune origin", "Prune origin", check=False)
        self.logger.execute("git worktree prune", "Prune worktrees", check=False)
        
        console.print(f"[green]✓ Cleaned worktree and branches for {branch_name}[/green]")
    
    def wt_list(self) -> None:
        """
        List all worktrees with their status.

        Bash equivalents:
            git worktree list --porcelain
        """
        console.print("[cyan]=== Git Worktrees ===[/cyan]\n")

        result = self.logger.execute("git worktree list --porcelain", "List worktrees")

        if not self.dry_run and result.stdout:
            # Parse worktree list
            worktrees = []
            current_wt = {}

            for line in result.stdout.strip().split('\n'):
                if line.startswith("worktree "):
                    if current_wt:
                        worktrees.append(current_wt)
                    current_wt = {"path": line[9:]}
                elif line.startswith("HEAD "):
                    current_wt["head"] = line[5:]
                elif line.startswith("branch "):
                    current_wt["branch"] = line[17:]  # refs/heads/ prefix
                elif line == "detached":
                    current_wt["branch"] = "(detached)"

            if current_wt:
                worktrees.append(current_wt)

            # Display as table
            table = Table(show_header=True)
            table.add_column("Path", style="cyan")
            table.add_column("Branch", style="green")

            for wt in worktrees:
                table.add_row(wt["path"], wt.get("branch", "(detached)"))

            console.print(table)
        else:
            console.print("No worktrees found")

        console.print("\nTo clean a worktree: wtf wt-clean SLUG")
        console.print("To clean stale refs: git worktree prune")

    def wt_status(self, slug: str, base: str = "main") -> None:
        """
        Show comprehensive status for a specific worktree.

        Bash equivalents:
            git -C <worktree> status --porcelain
            git -C <worktree> log --oneline -n 5
            git fetch upstream && git fetch origin
            git rev-list --count HEAD..upstream/main
            git rev-list --count upstream/main..HEAD
            git rev-list --count HEAD..origin/branch
            gh pr list --repo <upstream> --head <owner>:<branch>

        Args:
            slug: Feature slug
            base: Base branch name (default: main)
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)

        console.print(Panel.fit(f"[bold cyan]Worktree Status: {branch_name}[/bold cyan]", style="cyan"))

        # Check if worktree exists
        if not worktree_path.exists():
            console.print(f"[red]✗ Worktree not found at: {worktree_path}[/red]")
            console.print(f"  Run: wtf wt-new {slug}")
            sys.exit(1)

        # Determine if we're working from worktree or parent
        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None

        if current_branch == branch_name:
            git_dir = "."
        else:
            git_dir = str(worktree_path)

        # === Gather Information ===

        # 1. Get current HEAD info
        head_cmd = f'git -C "{git_dir}" log -1 --pretty=format:"%h %s"'
        head_result = self.logger.execute(head_cmd, "Get HEAD commit", check=False)
        head_info = head_result.stdout.strip() if (not self.dry_run and head_result.stdout) else "(unknown)"

        # 2. Fetch remotes
        console.print("\n[dim]Fetching latest from remotes...[/dim]")
        self.logger.execute("git fetch upstream", "Fetch upstream", check=False)
        self.logger.execute("git fetch origin", "Fetch origin", check=False)

        # 3. Get commit counts
        behind_upstream_cmd = f'git -C "{git_dir}" rev-list --count "HEAD..upstream/{base}"'
        ahead_upstream_cmd = f'git -C "{git_dir}" rev-list --count "upstream/{base}..HEAD"'

        behind_upstream_result = self.logger.execute(behind_upstream_cmd, "Check commits behind upstream", check=False)
        ahead_upstream_result = self.logger.execute(ahead_upstream_cmd, "Check commits ahead of upstream", check=False)

        commits_behind_upstream = int(behind_upstream_result.stdout.strip() or 0) if (not self.dry_run and behind_upstream_result.stdout) else 0
        commits_ahead_upstream = int(ahead_upstream_result.stdout.strip() or 0) if (not self.dry_run and ahead_upstream_result.stdout) else 0

        # 4. Get unpushed commits (ahead of origin)
        ahead_origin_cmd = f'git -C "{git_dir}" rev-list --count "origin/{branch_name}..HEAD"'
        ahead_origin_result = self.logger.execute(ahead_origin_cmd, "Check unpushed commits", check=False)
        commits_unpushed = int(ahead_origin_result.stdout.strip() or 0) if (not self.dry_run and ahead_origin_result.stdout) else 0

        # 5. Check working directory status
        status_cmd = f'git -C "{git_dir}" status --porcelain'
        status_result = self.logger.execute(status_cmd, "Check working directory", check=False)

        if not self.dry_run and status_result.stdout:
            status_lines = status_result.stdout.strip().split('\n')
            modified = sum(1 for line in status_lines if line and line[0] in ['M', 'A', 'D', 'R', 'C'])
            untracked = sum(1 for line in status_lines if line.startswith('??'))
            total_changes = len(status_lines)
        else:
            modified = 0
            untracked = 0
            total_changes = 0

        # 6. Check for PR
        pr_info = None
        if shutil.which("gh") and self.fork_owner:
            pr_cmd = (f'gh pr list --repo "{self.upstream_repo}" '
                     f'--head "{self.fork_owner}:{branch_name}" '
                     f'--json number,url,state,title')
            pr_result = self.logger.execute(pr_cmd, "Check for PR", check=False)

            if not self.dry_run and pr_result.returncode == 0 and pr_result.stdout.strip() != "[]":
                pr_data = json.loads(pr_result.stdout)[0]
                pr_info = pr_data

        # 7. Get recent commits
        log_cmd = f'git -C "{git_dir}" log --oneline -n 5'
        log_result = self.logger.execute(log_cmd, "Get recent commits", check=False)
        recent_commits = []
        if not self.dry_run and log_result.stdout:
            for line in log_result.stdout.strip().split('\n'):
                if line:
                    recent_commits.append(line)

        # === Display Status ===

        # Info table
        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Property", style="cyan")
        info_table.add_column("Value")

        info_table.add_row("Branch:", branch_name)
        info_table.add_row("Path:", str(worktree_path))
        info_table.add_row("HEAD:", head_info)

        console.print("\n")
        console.print(info_table)

        # Status table
        console.print("\n[bold cyan]Sync Status:[/bold cyan]")
        status_table = Table(show_header=False, box=None, padding=(0, 2))
        status_table.add_column("Metric", style="cyan")
        status_table.add_column("Count")
        status_table.add_column("Status")

        # Behind/ahead upstream
        if commits_behind_upstream > 0:
            status_table.add_row(
                f"Behind upstream/{base}:",
                str(commits_behind_upstream),
                "[yellow]⚠️  Need to update[/yellow]"
            )
        else:
            status_table.add_row(
                f"Behind upstream/{base}:",
                "0",
                "[green]✓ Up-to-date[/green]"
            )

        if commits_ahead_upstream > 0:
            status_table.add_row(
                f"Ahead of upstream/{base}:",
                str(commits_ahead_upstream),
                "[blue]ℹ️  Local changes[/blue]"
            )

        # Unpushed commits
        if commits_unpushed > 0:
            status_table.add_row(
                "Unpushed commits:",
                str(commits_unpushed),
                "[yellow]⚠️  Not pushed[/yellow]"
            )
        else:
            status_table.add_row(
                "Unpushed commits:",
                "0",
                "[green]✓ All pushed[/green]"
            )

        console.print(status_table)

        # Working directory status
        console.print("\n[bold cyan]Working Directory:[/bold cyan]")
        if total_changes > 0:
            wd_table = Table(show_header=False, box=None, padding=(0, 2))
            wd_table.add_column("Type", style="cyan")
            wd_table.add_column("Count")

            if modified > 0:
                wd_table.add_row("Modified/Staged:", str(modified))
            if untracked > 0:
                wd_table.add_row("Untracked:", str(untracked))

            console.print(wd_table)
            console.print(f"[yellow]⚠️  {total_changes} uncommitted change(s)[/yellow]")
        else:
            console.print("[green]✓ Clean working directory[/green]")

        # PR status
        if pr_info:
            console.print(f"\n[bold cyan]Pull Request:[/bold cyan]")

            state_colors = {
                "OPEN": "green",
                "CLOSED": "red",
                "MERGED": "blue"
            }
            state_color = state_colors.get(pr_info['state'], "white")

            pr_table = Table(show_header=False, box=None, padding=(0, 2))
            pr_table.add_column("Property", style="cyan")
            pr_table.add_column("Value")

            pr_table.add_row("Number:", f"#{pr_info['number']}")
            pr_table.add_row("State:", f"[{state_color}]{pr_info['state']}[/{state_color}]")
            pr_table.add_row("Title:", pr_info['title'])
            pr_table.add_row("URL:", pr_info['url'])

            console.print(pr_table)
        else:
            console.print(f"\n[dim]No pull request found[/dim]")

        # Recent commits
        if recent_commits:
            console.print(f"\n[bold cyan]Recent Commits:[/bold cyan]")
            for commit in recent_commits:
                console.print(f"  {commit}")

        # Action suggestions
        console.print(f"\n[bold cyan]Suggested Actions:[/bold cyan]")
        suggestions = []

        if commits_behind_upstream > 0:
            suggestions.append(f"• Update with upstream: [green]wtf wt-update {slug}[/green]")

        if commits_unpushed > 0:
            suggestions.append(f"• Push changes: [green]wtf wt-publish {slug}[/green]")

        if total_changes > 0:
            suggestions.append("• Commit changes: [green]git add -A && git commit[/green]")

        if not pr_info and commits_ahead_upstream > 0:
            suggestions.append(f"• Create PR: [green]wtf wt-pr {slug}[/green]")

        if suggestions:
            for suggestion in suggestions:
                console.print(f"  {suggestion}")
        else:
            console.print("  [green]✓ Everything looks good![/green]")

    # ========== Check Commands ==========

    def check_repo(self) -> None:
        """
        Verify we're inside a Git repository.

        Bash equivalent:
            git rev-parse --show-toplevel

        Exits with code 1 if not in a repository.
        """
        try:
            console.print(f"[green]✓ Inside Git repository[/green]")
            console.print(f"  Root: {self.root}")
            console.print(f"  Name: {self.repo_name}")
        except Exception:
            console.print("[red]✗ Not inside a Git repository[/red]")
            console.print("  Change to your repository directory first")
            sys.exit(1)

    def check_origin(self) -> None:
        """
        Verify 'origin' remote exists.

        Bash equivalent:
            git remote get-url origin

        Exits with code 1 if origin is missing.
        """
        if "origin" not in self.repo.remotes:
            console.print("[red]✗ Missing 'origin' remote (your fork)[/red]")
            console.print("  Add it with: git remote add origin <url>")
            console.print("  Or run: wtf fork-setup")
            sys.exit(1)

        origin_url = self.repo.remote("origin").url
        console.print("[green]✓ Origin remote exists[/green]")
        console.print(f"  URL: {origin_url}")
        if self.fork_owner:
            console.print(f"  Owner: {self.fork_owner}")

    def check_upstream(self) -> None:
        """
        Verify 'upstream' remote exists.

        Bash equivalent:
            git remote get-url upstream

        Exits with code 1 if upstream is missing.
        """
        if "upstream" not in self.repo.remotes:
            console.print(f"[red]✗ Missing 'upstream' remote ({self.upstream_repo})[/red]")
            console.print("  Add it with: wtf upstream-add")
            console.print(f"  Or manually: git remote add upstream git@github.com:{self.upstream_repo}.git")
            sys.exit(1)

        upstream_url = self.repo.remote("upstream").url
        console.print("[green]✓ Upstream remote exists[/green]")
        console.print(f"  URL: {upstream_url}")
        console.print(f"  Repo: {self.upstream_repo}")


# ========== CLI Interface ==========

@click.group(invoke_without_command=True)
@click.option('--debug', '-d', is_flag=True, help='Enable debug output (shows bash commands)')
@click.option('--dry-run', '-n', is_flag=True, help='Preview commands without execution')
@click.option('--save-history', is_flag=True, help='Save command history to .wtf_history.json')
@click.pass_context
def cli(ctx, debug, dry_run, save_history):
    """
    Git workflow manager - Python port of hl + hl.mk
    
    This tool merges the capabilities of the hl bash wrapper and hl.mk makefile
    into a single Python script using GitPython for Git operations.
    
    Every Git operation documents its bash equivalent for transparency.
    
    Common workflow:
    
        wtf sync-main              # Update fork's main
        
        wtf wt-new issue-123       # Create worktree
        
        # ... make changes ...
        
        wtf wt-publish issue-123   # Push to fork
        
        wtf wt-pr issue-123        # Create PR
        
        wtf wt-update issue-123    # Rebase on upstream
        
        wtf wt-clean issue-123     # Clean up after merge
    """
    # Initialize the workflow manager
    ctx.obj = GitWorkflowManager(debug=debug, dry_run=dry_run, save_history=save_history)
    
    # Show help if no command given
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
    
    # Save history on exit if requested
    if save_history and ctx.invoked_subcommand:
        import atexit
        atexit.register(lambda: ctx.obj.logger.save_history())


# ========== Repository Setup Commands ==========

@cli.command()
@click.pass_obj
def doctor(manager):
    """Print detected settings and sanity-check environment."""
    manager.doctor()


@cli.command('upstream-add')
@click.option('--repo', 'repo_upstream', help='Override upstream repo (format: owner/repo)')
@click.option('--update', is_flag=True, help='Force update existing upstream')
@click.pass_obj
def upstream_add(manager, repo_upstream, update):
    """Add or update upstream remote (auto-detects SSH/HTTPS)."""
    manager.upstream_add(repo_upstream, update)


@cli.command('fork-setup')
@click.pass_obj
def fork_setup(manager):
    """Create fork if needed and set up remotes (requires gh CLI)."""
    manager.fork_setup()


# ========== Sync Commands ==========

@cli.command('sync-main')
@click.option('--base', default='main', help='Base branch name')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompts')
@click.pass_obj
def sync_main(manager, base, confirm):
    """FF-only: update fork's main from upstream/main."""
    manager.sync_main(base, confirm)


@cli.command('sync-main-force')
@click.option('--base', default='main', help='Base branch name')
@click.option('--confirm', is_flag=True, help='Confirm destructive operation')
@click.option('--force', is_flag=True, help='Force even with uncommitted changes')
@click.pass_obj
def sync_main_force(manager, base, confirm, force):
    """RECOVERY: reset fork main to upstream and force-push (creates backup)."""
    manager.sync_main_force(base, confirm, force)


@cli.command('zero-ffsync')
@click.option('--base', default='main', help='Base branch name')
@click.pass_obj
def zero_ffsync(manager, base):
    """FF-only push (no checkout): origin/main <- upstream/main."""
    manager.zero_ffsync(base)


# ========== Worktree Commands ==========

@cli.command('wt-new')
@click.argument('slug')
@click.option('--base', default='main', help='Base branch to branch from')
@click.pass_obj
def wt_new(manager, slug, base):
    """Create worktree + new feature branch from fork/main."""
    manager.wt_new(slug, base)


@cli.command('wt-publish')
@click.argument('slug')
@click.pass_obj
def wt_publish(manager, slug):
    """Push worktree feature branch to origin and set upstream."""
    manager.wt_publish(slug)


@cli.command('wt-pr')
@click.argument('slug')
@click.option('--base', default='main', help='Base branch for PR (default: main)')
@click.option('--title', help='PR title (auto-generated if not provided)')
@click.option('--body', help='PR body (auto-generated if not provided)')
@click.option('--draft', is_flag=True, help='Create as draft PR')
@click.pass_obj
def wt_pr(manager, slug, base, title, body, draft):
    """Open PR from fork feature to upstream/main (requires gh CLI)."""
    manager.wt_pr(slug, base, title, body, draft)


@cli.command('wt-update')
@click.argument('slug')
@click.option('--base', default='main', help='Base branch name')
@click.option('--stash', is_flag=True, help='Auto-stash uncommitted changes')
@click.option('--dry-run-preview', is_flag=True, help='Preview what would happen')
@click.option('--merge', is_flag=True, help='Use merge instead of rebase')
@click.option('--no-backup', is_flag=True, help='Skip backup branch creation')
@click.pass_obj
def wt_update(manager, slug, base, stash, dry_run_preview, merge, no_backup):
    """Rebase worktree feature on upstream/main and push."""
    manager.wt_update(slug, base, stash, dry_run_preview, merge, no_backup)


@cli.command('wt-clean')
@click.argument('slug')
@click.option('--force-delete', is_flag=True, help='Force delete branch even if not merged')
@click.option('--wt-force', is_flag=True, help='Force remove worktree with uncommitted changes')
@click.option('--dry-run-preview', is_flag=True, help='Preview what would be deleted')
@click.option('--confirm', is_flag=True, help='Skip confirmation prompts')
@click.pass_obj
def wt_clean(manager, slug, force_delete, wt_force, dry_run_preview, confirm):
    """Remove worktree and prune branches."""
    manager.wt_clean(slug, force_delete, wt_force, dry_run_preview, confirm)


@cli.command('wt-list')
@click.pass_obj
def wt_list(manager):
    """List all worktrees with their status."""
    manager.wt_list()


@cli.command('wt-status')
@click.argument('slug')
@click.option('--base', default='main', help='Base branch name')
@click.pass_obj
def wt_status(manager, slug, base):
    """Show comprehensive status for a worktree."""
    manager.wt_status(slug, base)


# ========== Check Commands ==========

@cli.command('check-repo')
@click.pass_obj
def check_repo(manager):
    """Verify we're inside a Git repository."""
    manager.check_repo()


@cli.command('check-origin')
@click.pass_obj
def check_origin(manager):
    """Verify 'origin' remote exists."""
    manager.check_origin()


@cli.command('check-upstream')
@click.pass_obj
def check_upstream(manager):
    """Verify 'upstream' remote exists."""
    manager.check_upstream()


# ========== Tutorial Commands ==========

@cli.command()
def tutorial():
    """Show detailed tutorial for all workflows."""
    tutorial_text = """
[bold cyan]Git Workflow Tutorial[/bold cyan]
=====================

[bold]0) First-time setup (fork & clone)[/bold]
If you do NOT have a fork locally yet:
  • Create your fork: [green]wtf fork-setup[/green]
    (Requires GitHub CLI and login: gh auth login)

If you ALREADY have the fork cloned:
  • Add upstream: [green]wtf upstream-add[/green]
  • Check setup: [green]wtf doctor[/green]

[bold]1) Keep your fork's main synced[/bold]
  • Full sync: [green]wtf sync-main[/green]
  • Quick sync: [green]wtf zero-ffsync[/green]
  • Recovery: [green]wtf sync-main-force --confirm[/green]

[bold]2) Worktree-based feature branches[/bold]
  A. Create: [green]wtf wt-new issue-199[/green]
  B. Work in: [green]cd ../wt/{repo}/issue-199[/green]
  C. Publish: [green]wtf wt-publish issue-199[/green]
  D. Open PR: [green]wtf wt-pr issue-199[/green]
  E. Update: [green]wtf wt-update issue-199[/green]
  F. Clean: [green]wtf wt-clean issue-199 --confirm[/green]

[bold]3) Debug and safety[/bold]
  • Debug mode: [green]wtf --debug <command>[/green]
  • Dry run: [green]wtf --dry-run <command>[/green]
  • Save history: [green]wtf --save-history <command>[/green]
"""
    console.print(tutorial_text)


@cli.command()
def quickstart():
    """Show quickstart guide."""
    quickstart_text = """
[bold cyan]Quickstart Guide[/bold cyan]
================

[bold]First time:[/bold]
  [green]wtf fork-setup[/green]         # Create fork and setup remotes

[bold]Daily workflow:[/bold]
  [green]wtf sync-main[/green]          # Update fork's main
  [green]wtf wt-new feat-x[/green]      # Create worktree
  # ... make changes ...
  [green]wtf wt-publish feat-x[/green]  # Push to fork
  [green]wtf wt-pr feat-x[/green]       # Create PR
  [green]wtf wt-update feat-x[/green]   # Rebase on upstream
  [green]wtf wt-clean feat-x[/green]    # Clean up after merge

[bold]Options:[/bold]
  --debug    Show bash commands
  --dry-run  Preview without execution
  --help     Show help for any command
"""
    console.print(quickstart_text)


if __name__ == "__main__":
    cli()
