"""
Core Git workflow manager for worktreeflow.

Contains all Git workflow operations using GitPython.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import git
from git import GitCommandError, Repo
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from worktreeflow.config import RepoSettings, load_config
from worktreeflow.errors import WorktreeFlowError
from worktreeflow.logger import BashCommandLogger
from worktreeflow.validator import SafetyValidator

console = Console()


class GitWorkflowManager:
    """
    Main Git workflow manager using GitPython.

    This class contains all the Git workflow operations, merging functionality
    from both hl and hl.mk into a unified Python implementation.
    """

    def __init__(
        self,
        debug: bool = False,
        dry_run: bool = False,
        save_history: bool = False,
        quiet: bool = False,
        verbose: bool = False,
        json_output: bool = False,
    ):
        """
        Initialize the workflow manager.

        Args:
            debug: Show debug output including bash commands
            dry_run: Preview mode without actual execution
            save_history: Save command history to file
            quiet: Suppress non-error output
            verbose: Show extra detail beyond default output
            json_output: Output machine-readable JSON instead of Rich tables
        """
        self.debug = debug
        self.dry_run = dry_run
        self.save_history = save_history
        self.quiet = quiet
        self.verbose = verbose
        self.json_output = json_output
        self.logger = BashCommandLogger(debug=debug, dry_run=dry_run)
        self.validator = SafetyValidator()
        self.config: RepoSettings = RepoSettings()

        self._init_repo_info()

    def info(self, message: Any) -> None:
        """Print an informational message, suppressed in quiet mode."""
        if not self.quiet:
            console.print(message)

    def detail(self, message: Any) -> None:
        """Print a detailed message, only shown in verbose mode."""
        if self.verbose and not self.quiet:
            console.print(message)

    def error(self, message: Any) -> None:
        """Print an error message (always shown, even in quiet mode)."""
        console.print(message)

    def _make_branch_name(self, slug: str) -> str:
        """Build a full branch name from a slug using the configured prefix."""
        return f"{self.config.feature_branch_prefix}{slug}"

    def _init_repo_info(self) -> None:
        """Initialize repository information and configuration."""
        try:
            self.logger.log("git rev-parse --show-toplevel", "Find repository root")
            self.repo = Repo(search_parent_directories=True)
            working_dir = self.repo.working_tree_dir
            if working_dir is None:
                raise WorktreeFlowError("Repository has no working tree (bare repository?)")
            self.root = Path(working_dir)

            self.repo_name = self.root.name

            # Load config file before detecting remotes
            self.config = load_config(self.root)

            self._detect_fork_owner()
            self._detect_upstream_repo()

        except git.InvalidGitRepositoryError as exc:
            raise WorktreeFlowError("Not inside a Git repository") from exc

    def _detect_fork_owner(self) -> None:
        """Detect fork owner from origin remote URL."""
        self.fork_owner = None

        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            self.logger.log("git remote get-url origin", "Get origin URL")

            # Parse owner from URL (works for SSH and HTTPS)
            match = re.search(r"(?:github\.com[:/])([^/]+)/.*", origin_url)
            if match:
                self.fork_owner = match.group(1)

        # Fallback to gh CLI if available
        if not self.fork_owner and shutil.which("gh"):
            try:
                result = self.logger.execute("gh api user -q .login", "Get GitHub username")
                if not self.dry_run and result.returncode == 0:
                    self.fork_owner = result.stdout.strip()
            except OSError:
                pass

    def _detect_upstream_repo(self) -> None:
        """
        Detect upstream repository from remote URL.

        Falls back to config file value, or None if neither is available.
        B08 fix: No longer hardcodes a default upstream repo.
        B09 fix: Uses robust URL parsing that handles malformed URLs gracefully.
        """
        # Start with config file value (may be None)
        self.upstream_repo = self.config.upstream_repo

        if self.config.upstream_remote in self.repo.remotes:
            upstream_url = self.repo.remote("upstream").url
            self.logger.log("git remote get-url upstream", "Get upstream URL")

            # B09 fix: robust URL parsing with proper error handling
            match = re.search(r"(?:github\.com[:/])([^/]+/[^/.]+)", upstream_url)
            if match:
                self.upstream_repo = match.group(1).removesuffix(".git")
            else:
                self.info(f"[yellow]Warning: Could not parse upstream URL: {upstream_url}[/yellow]")

    def _get_worktree_path(self, slug: str) -> Path:
        """
        Get the worktree path for a given slug.

        B05 fix: Uses Path operations instead of string interpolation.
        """
        return self.root.parent / "wt" / self.repo_name / slug

    def _infer_slug_from_cwd(self) -> str | None:
        """
        Infer the worktree slug from the current working directory.

        Checks if cwd is inside a worktree path matching the pattern
        {worktree_base}/{repo_name}/{slug}.

        Returns:
            The inferred slug, or None if not inside a worktree.
        """
        cwd = Path.cwd()
        # Expected pattern: .../wt/{repo_name}/{slug}
        try:
            parts = cwd.parts
            for i, part in enumerate(parts):
                if part == "wt" and i + 2 < len(parts) and parts[i + 1] == self.repo_name:
                    return parts[i + 2]
        except (IndexError, ValueError):
            pass

        # Also try matching by checking if cwd matches a known worktree path
        try:
            for i, part in enumerate(parts):
                if part == self.repo_name and i > 0 and parts[i - 1] == "wt":
                    return parts[i + 1]
        except (IndexError, ValueError):
            pass

        return None

    def resolve_slug(self, slug: str | None) -> str:
        """
        Resolve slug from explicit argument or auto-detect from cwd.

        Args:
            slug: Explicit slug, or None to auto-detect.

        Returns:
            Resolved slug string.

        Raises:
            WorktreeFlowError: If slug is None and cannot be inferred.
        """
        if slug is not None:
            return slug

        inferred = self._infer_slug_from_cwd()
        if inferred:
            self.detail(f"[dim]Auto-detected slug: {inferred}[/dim]")
            return inferred

        raise WorktreeFlowError(
            "SLUG is required when not inside a worktree.\n"
            "  Either provide SLUG as an argument, or cd into a worktree first.\n"
            "  List worktrees: wtf wt-list"
        )

    def _require_gh(self) -> None:
        """Ensure the GitHub CLI is available, raising a clear error if not."""
        if not shutil.which("gh"):
            raise WorktreeFlowError(
                "GitHub CLI (gh) is required for this command.\n"
                "  Install from: https://cli.github.com/\n"
                "  Then authenticate: gh auth login"
            )

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
        origin_url = self.repo.remote("origin").url if "origin" in self.repo.remotes else None
        upstream_url = self.repo.remote("upstream").url if "upstream" in self.repo.remotes else None
        has_gh = bool(shutil.which("gh"))

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = f"(detached) {self.repo.head.commit.hexsha[:7]}"

        is_dirty = self.repo.is_dirty()
        config_path = self.root / ".worktreeflow.toml"

        issues = []
        if "origin" not in self.repo.remotes:
            issues.append("Missing 'origin' remote (your fork)")
        if "upstream" not in self.repo.remotes:
            issues.append("Missing 'upstream' remote. Run: wtf upstream-add")
        if not self.fork_owner:
            issues.append("Could not detect fork owner")
        if not has_gh:
            issues.append("GitHub CLI not found. Install from: https://cli.github.com/")
        if not self.upstream_repo:
            issues.append("Upstream repo not configured. Run: wtf upstream-add --repo owner/repo")

        if self.json_output:
            data = {
                "repo_root": str(self.root),
                "repo_name": self.repo_name,
                "upstream_repo": self.upstream_repo,
                "fork_owner": self.fork_owner,
                "origin_url": origin_url,
                "upstream_url": upstream_url,
                "has_gh_cli": has_gh,
                "current_branch": current_branch,
                "is_dirty": is_dirty,
                "config_file": str(config_path) if config_path.exists() else None,
                "branch_prefix": self.config.feature_branch_prefix,
                "issues": issues,
                "healthy": len(issues) == 0,
            }
            click.echo(json.dumps(data, indent=2))
            return

        self.info(Panel.fit("[bold]Environment Check[/bold]", style="cyan"))

        table = Table(show_header=False, box=None)
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Repo root:", str(self.root))
        table.add_row("Repo name:", self.repo_name)
        table.add_row("Upstream repo:", self.upstream_repo or "[yellow]Not configured[/yellow]")
        table.add_row("Fork owner:", self.fork_owner or "[red]Not detected[/red]")
        table.add_row("Origin URL:", origin_url or "[red]Missing[/red]")
        table.add_row("Upstream URL:", upstream_url or "[red]Missing[/red]")

        gh_display = "[green]✓[/green]" if has_gh else "[red]✗[/red]"
        table.add_row("Has gh CLI:", gh_display)
        table.add_row("Current branch:", current_branch)

        is_dirty_display = "[yellow]Yes[/yellow]" if is_dirty else "No"
        table.add_row("Has changes:", is_dirty_display)
        table.add_row("Config file:", str(config_path) if config_path.exists() else "[dim]Not found[/dim]")
        table.add_row("Branch prefix:", self.config.feature_branch_prefix)

        self.info(table)

        if issues:
            self.info("\n[yellow]Issues found:[/yellow]")
            for issue in issues:
                self.info(f"  \u2022 {issue}")
        else:
            self.info("\n[green]✓ Environment check passed[/green]")

    def upstream_add(self, repo_upstream: str | None = None, update: bool = False) -> None:
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
            if not re.match(r"^[^/]+/[^/]+$", repo_upstream):
                raise ValueError(f"REPO_UPSTREAM must be in 'owner/repo' format. Got: '{repo_upstream}'")
            self.upstream_repo = repo_upstream

        if not self.upstream_repo:
            raise WorktreeFlowError("No upstream repo specified.\n  Run: wtf upstream-add --repo owner/repo")

        # Detect URL type from origin (SSH vs HTTPS)
        url_type = "SSH"
        upstream_url = f"git@github.com:{self.upstream_repo}.git"

        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            if origin_url.startswith("https://"):
                url_type = "HTTPS"
                upstream_url = f"https://github.com/{self.upstream_repo}.git"

        if "upstream" in self.repo.remotes:
            existing_url = self.repo.remote("upstream").url
            self.info(f"Current upstream: {existing_url}")

            if existing_url == upstream_url:
                self.info("[green]✓ Upstream already correctly set[/green]")
            elif update:
                self.info(f"Updating upstream to: {upstream_url} ({url_type})")
                self.logger.log(f'git remote set-url upstream "{upstream_url}"')
                if not self.dry_run:
                    self.repo.remote("upstream").set_url(upstream_url)
                self.info("[green]✓ Updated upstream remote[/green]")
            else:
                raise WorktreeFlowError(
                    f"Upstream already set to {existing_url}.\n"
                    f"  To update to {upstream_url}, run: wtf upstream-add --update\n"
                    f"  Or manually: git remote set-url upstream {upstream_url}"
                )
        else:
            self.info(f"Adding upstream: {upstream_url} ({url_type})")
            self.logger.log(f'git remote add upstream "{upstream_url}"')
            if not self.dry_run:
                self.repo.create_remote("upstream", upstream_url)
            self.info("[green]✓ Added upstream remote[/green]")

        # Configure pull.ff
        self.logger.log("git config pull.ff only")
        if not self.dry_run:
            try:
                with self.repo.config_writer() as config:
                    config.set_value("pull", "ff", "only")
            except (OSError, KeyError) as e:
                self.info(f"[yellow]Warning: Could not set pull.ff config: {e}[/yellow]")
        self.info("[green]✓ Configured pull.ff=only[/green]")

        self.info("\nRemotes:")
        if not self.dry_run:
            for remote in self.repo.remotes:
                self.info(f"  {remote.name}: {remote.url}")

    def fork_setup(self) -> None:
        """
        Create fork if needed and set up remotes.

        Bash equivalents:
            gh api user -q .login
            gh repo view {user}/repo --json name
            gh repo fork {upstream} --clone=false
            git remote rename origin upstream
            git remote add origin git@github.com:{user}/{repo}.git

        Requires gh CLI to be installed and authenticated.
        """
        self._require_gh()

        if not self.upstream_repo:
            raise WorktreeFlowError("No upstream repo configured.\n  Run: wtf upstream-add --repo owner/repo")

        self.info("[cyan]Setting up fork...[/cyan]")

        result = self.logger.execute("gh api user -q .login", "Get GitHub username")
        if self.dry_run:
            github_user = "YOUR_USERNAME"
        else:
            if result.returncode != 0:
                raise WorktreeFlowError("Not authenticated. Run: gh auth login")
            github_user = result.stdout.strip()

        self.info(f"GitHub user: {github_user}")

        # B09 fix: safe repo name extraction
        parts = self.upstream_repo.split("/")
        if len(parts) != 2 or not parts[1]:
            raise WorktreeFlowError(
                f"Invalid upstream repo format: {self.upstream_repo}\n  Expected format: owner/repo"
            )
        repo_name = parts[1]

        fork_check_cmd = f"gh repo view {shlex.quote(f'{github_user}/{repo_name}')} --json name 2>/dev/null"
        result = self.logger.execute(fork_check_cmd, "Check if fork exists", check=False)

        if result.returncode != 0:
            self.info("Creating fork...")
            fork_cmd = f"gh repo fork {shlex.quote(self.upstream_repo)} --clone=false"
            self.logger.execute(fork_cmd, "Create fork")
            self.info(f"[green]Fork created: {github_user}/{repo_name}[/green]")
        else:
            self.info(f"[green]Fork already exists: {github_user}/{repo_name}[/green]")

        self.info("\nConfiguring remotes...")

        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            if self.upstream_repo in origin_url:
                if "upstream" not in self.repo.remotes:
                    self.info("Renaming origin to upstream...")
                    self.logger.log("git remote rename origin upstream")
                    if not self.dry_run:
                        self.repo.remote("origin").rename("upstream")
                else:
                    self.info("Removing duplicate origin...")
                    self.logger.log("git remote remove origin")
                    if not self.dry_run:
                        self.repo.delete_remote(self.repo.remote("origin"))

        fork_url = f"git@github.com:{github_user}/{repo_name}.git"
        if "origin" not in self.repo.remotes:
            self.info("Adding fork as origin...")
            self.logger.log(f'git remote add origin "{fork_url}"')
            if not self.dry_run:
                self.repo.create_remote("origin", fork_url)
        else:
            current_origin = self.repo.remote("origin").url
            if github_user not in current_origin:
                self.logger.log(f'git remote set-url origin "{fork_url}"')
                if not self.dry_run:
                    self.repo.remote("origin").set_url(fork_url)

        if "upstream" not in self.repo.remotes:
            upstream_url = f"git@github.com:{self.upstream_repo}.git"
            self.logger.log(f'git remote add upstream "{upstream_url}"')
            if not self.dry_run:
                self.repo.create_remote("upstream", upstream_url)

        self.info("\n[green]Final remote configuration:[/green]")
        if not self.dry_run:
            for remote in self.repo.remotes:
                self.info(f"  {remote.name}: {remote.url}")

        self.info("\n[green]Fork setup complete![/green]")
        self.info("You can now:")
        self.info("  • Push to your fork: git push origin <branch>")
        self.info("  • Pull from upstream: git pull upstream main")
        self.info("  • Create PRs: wtf wt-pr SLUG")

    # ========== Sync Operations ==========

    def sync_main(self, base: str = "main", confirm: bool = False) -> None:
        """
        Fast-forward sync fork's main with upstream/main.

        Bash equivalents:
            git diff --quiet && git diff --cached --quiet
            git fetch upstream
            git log --oneline main..upstream/main
            git switch main
            git merge --ff-only upstream/main
            git push origin main

        Args:
            base: Base branch name (default: main)
            confirm: Skip confirmation prompts
        """
        self.info(f"[cyan]Syncing {base} with upstream...[/cyan]")

        self.validator.check_uncommitted_changes(self.repo, stash=False)

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch and current_branch != base:
            self.info(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")

        self.info("Fetching upstream...")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("upstream").fetch()

        # B07 fix: specific exception handling
        self.logger.log(f"git log --oneline {base}..upstream/{base}", "Show new commits")
        if not self.dry_run:
            try:
                new_commits = list(self.repo.iter_commits(f"{base}..upstream/{base}"))
                if new_commits:
                    self.info(f"\nNew commits from upstream/{base}:")
                    for commit in new_commits[:10]:
                        self.info(f"  {commit.hexsha[:7]} {commit.summary}")
                    if len(new_commits) > 10:
                        self.info(f"  ... and {len(new_commits) - 10} more")
                else:
                    self.info("[green]Already up-to-date[/green]")
                    return
            except GitCommandError as e:
                self.info(f"[yellow]Warning: Could not list new commits: {e}[/yellow]")

        # Switch to base branch
        self.logger.log(f"git switch {base}")
        if not self.dry_run:
            self.repo.heads[base].checkout()

        self.info(f"Fast-forwarding {base}...")
        self.logger.log(f"git merge --ff-only upstream/{base}")

        if not self.dry_run:
            try:
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(self.repo.head.commit, upstream_ref.commit)

                if not merge_base:
                    raise WorktreeFlowError(
                        f"No common ancestor between {base} and upstream/{base}.\n"
                        "The repositories appear to have unrelated histories.\n"
                        "To force-sync (DESTRUCTIVE): wtf sync-main-force --confirm"
                    )

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
                        f"     git log --oneline upstream/{base}..{base}",
                    )

                self.repo.head.reset(upstream_ref.commit, index=True, working_tree=True)

            except GitCommandError as e:
                raise WorktreeFlowError(str(e.stderr)) from e

        self.info(f"Pushing to origin/{base}...")
        self.logger.log(f"git push origin {base}")
        if not self.dry_run:
            self.repo.remote("origin").push(base)

        self.info(f"[green]✓ Fork {base} fast-forwarded to upstream/{base}[/green]")

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
            self.error(f"[red]WARNING: This will DESTROY any local commits on {base} not in upstream![/red]")

            self.logger.log(f"git log --oneline upstream/{base}..{base}", "Show commits to be lost")
            if not self.dry_run:
                try:
                    lost_commits = list(self.repo.iter_commits(f"upstream/{base}..{base}"))
                    if lost_commits:
                        self.error(f"\nCurrent {base} commits that will be LOST:")
                        for commit in lost_commits[:10]:
                            self.error(f"  {commit.hexsha[:7]} {commit.summary}")
                    else:
                        self.info("  (none)")
                except GitCommandError as e:
                    self.info(f"[yellow]Warning: Could not list commits: {e}[/yellow]")

            self.error("\nTo proceed, run:")
            self.error("  wtf sync-main-force --confirm")
            raise WorktreeFlowError("Destructive operation requires --confirm flag.")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch != base:
            if current_branch:
                self.info(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")
            else:
                self.info(f"[yellow]WARNING: HEAD is detached, switching to '{base}'[/yellow]")
            self.logger.log(f"git switch {base}")
            if not self.dry_run:
                self.repo.heads[base].checkout()

        if self.repo.is_dirty() and not force:
            raise WorktreeFlowError(
                "You have uncommitted changes that will be LOST!\n"
                "  To see changes: git status\n"
                "  To force anyway: wtf sync-main-force --confirm --force"
            )

        backup_branch = f"{self.config.backup_branch_prefix}{base}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        self.info(f"Creating backup branch: {backup_branch}")
        self.logger.log(f"git branch {backup_branch}")
        if not self.dry_run:
            self.repo.create_head(backup_branch)

        self.info("Fetching upstream...")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("upstream").fetch()

        self.info(f"Resetting {base} to upstream/{base}...")
        self.logger.log(f"git reset --hard upstream/{base}")
        if not self.dry_run:
            upstream_ref = self.repo.remote("upstream").refs[base]
            self.repo.head.reset(upstream_ref.commit, index=True, working_tree=True)

        self.info("Force-pushing to origin...")
        self.logger.log(f"git push --force-with-lease origin {base}")
        if not self.dry_run:
            self.repo.remote("origin").push(f"{base}:{base}", force=True)

        self.info(f"[green]✓ Fork {base} hard-reset to upstream/{base} and force-pushed[/green]")
        self.info(f"[green]✓ Previous state backed up to: {backup_branch}[/green]")
        self.info(f"\nTo restore the backup: git switch {backup_branch}")

    def zero_ffsync(self, base: str = "main") -> None:
        """
        Fast-forward push without checkout: origin/main <- upstream/main.

        Bash equivalents:
            git fetch origin
            git fetch upstream
            git rev-list origin/main..main
            git merge-base --is-ancestor origin/main upstream/main
            git push origin upstream/main:main

        Args:
            base: Base branch name
        """
        self.info(f"[cyan]Zero-checkout fast-forward sync of {base}...[/cyan]")

        self.info(f"Checking local {base} status...")
        self.logger.log("git fetch origin")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("origin").fetch()
            self.repo.remote("upstream").fetch()

        if base in self.repo.heads:
            self.logger.log(f"git rev-list origin/{base}..{base}", "Check unpushed commits")
            if not self.dry_run:
                try:
                    unpushed = list(self.repo.iter_commits(f"origin/{base}..{base}"))
                    if unpushed:
                        raise WorktreeFlowError(
                            f"Your local {base} has {len(unpushed)} unpushed commit(s).\n"
                            f"These would be lost if origin/{base} is updated directly.\n\n"
                            "Options:\n"
                            f"  1. Push your local commits first:\n"
                            f"     git push origin {base}\n"
                            "  2. Use sync-main instead (will checkout and merge):\n"
                            "     wtf sync-main\n"
                            "  3. If you want to discard local commits:\n"
                            "     wtf sync-main-force --confirm"
                        )
                except GitCommandError as e:
                    self.info(f"[yellow]Warning: Could not check unpushed commits: {e}[/yellow]")

        self.info(f"Checking if origin/{base} can fast-forward to upstream/{base}...")
        self.logger.log(f"git merge-base --is-ancestor origin/{base} upstream/{base}")

        if not self.dry_run:
            try:
                origin_ref = self.repo.remote("origin").refs[base]
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(origin_ref.commit, upstream_ref.commit)

                if not merge_base:
                    raise WorktreeFlowError(
                        f"No common ancestor between origin/{base} and upstream/{base}.\n"
                        "The repositories appear to have unrelated histories.\n"
                        "To force-sync (DESTRUCTIVE): wtf sync-main-force --confirm"
                    )

                if merge_base[0] != origin_ref.commit:
                    raise WorktreeFlowError(
                        f"Cannot fast-forward origin/{base} to upstream/{base}.\n"
                        f"origin/{base} has diverged from upstream/{base}.\n\n"
                        "To see the divergence:\n"
                        f"  git log --oneline --graph upstream/{base} origin/{base}\n\n"
                        "To force-sync (DESTRUCTIVE):\n"
                        "  wtf sync-main-force --confirm"
                    )

                new_commits = list(self.repo.iter_commits(f"{origin_ref.commit}..{upstream_ref.commit}"))
                if new_commits:
                    self.info("\nNew commits to be synced:")
                    for commit in new_commits[:10]:
                        self.info(f"  {commit.hexsha[:7]} {commit.summary}")
                else:
                    self.info("[green]Already up-to-date[/green]")
                    return

            except GitCommandError as e:
                raise WorktreeFlowError(str(e)) from e

        self.info("Syncing...")
        self.logger.log(f"git push origin upstream/{base}:{base}")
        if not self.dry_run:
            try:
                self.repo.remote("origin").push(f"upstream/{base}:{base}")
                self.info(f"[green]✓ Successfully fast-forwarded origin/{base} to upstream/{base}[/green]")
            except GitCommandError as exc:
                raise WorktreeFlowError(
                    "Push failed. This might happen if:\n"
                    f"  - Someone else pushed to origin/{base} in the meantime\n"
                    "  - You don't have push permissions\n"
                    "  Try: wtf sync-main"
                ) from exc

    # ========== Worktree Management ==========

    def wt_new(self, slug: str, base: str = "main", no_sync: bool = False) -> None:
        """
        Create worktree and new feature branch from fork/main.

        Bash equivalents:
            git worktree add {path} -b {prefix}{slug} {base}
            git worktree add {path} {branch}  # if branch exists

        Args:
            slug: Feature slug
            base: Base branch to branch from
            no_sync: Skip sync_main before creating worktree (B04 fix)
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)

        self.validator.validate_branch_name(branch_name)

        self.info(f"[cyan]Creating worktree for {branch_name}...[/cyan]")

        # B04 fix: sync is now optional
        if not no_sync:
            try:
                self.sync_main(base=base)
            except (GitCommandError, WorktreeFlowError):
                self.info("[yellow]Warning: Could not sync main. Continuing with worktree creation.[/yellow]")
        else:
            self.info("[dim]Skipping sync (--no-sync)[/dim]")

        worktree_path = self._get_worktree_path(slug)

        if worktree_path.exists():
            try:
                # B05 fix: use shlex.quote for path in shell command
                wt_check = self.logger.execute(
                    f'git worktree list --porcelain | grep "^worktree.*{shlex.quote(str(worktree_path))}"',
                    "Check if path is a worktree",
                    check=False,
                )
                if wt_check.returncode == 0:
                    self.info(f"[green]✓ Worktree already exists at: {worktree_path}[/green]")
                    self.info(f"  Branch: {branch_name}")
                    self.info(f"  To use it: cd {worktree_path}")
                    self.info(f"  To remove it: wtf wt-clean {slug}")
                    return
            except OSError:
                pass

            raise WorktreeFlowError(
                f"Directory exists but is not a git worktree: {worktree_path}\n"
                "  Remove it manually or choose a different SLUG"
            )

        # B05 fix: use shlex.quote for paths in shell commands
        quoted_path = shlex.quote(str(worktree_path))
        quoted_branch = shlex.quote(branch_name)
        quoted_base = shlex.quote(base)

        if branch_name in self.repo.heads:
            self.info(f"Branch {branch_name} already exists locally, using it for worktree")
            cmd = f"git worktree add {quoted_path} {quoted_branch}"
        else:
            self.info(f"Creating new branch {branch_name} from {base}")
            cmd = f"git worktree add {quoted_path} -b {quoted_branch} {quoted_base}"

        self.logger.execute(cmd, "Create worktree")

        if not self.dry_run:
            self.info(f"[green]✓ Created worktree: {worktree_path}[/green]")
            self.info(f"[green]✓ Branch: {branch_name}[/green]")
            self.info("\nNext steps:")
            self.info(f"  cd {worktree_path}")
            self.info("  # Make your changes")
            self.info(f"  git add -A && git commit -m '{self.config.feature_branch_prefix.rstrip('/')}: {slug}'")
            self.info(f"  wtf wt-publish {slug}")

    def wt_publish(self, slug: str) -> None:
        """
        Push worktree feature branch to origin and set upstream.

        Bash equivalents:
            git push -u origin {prefix}{slug}

        Args:
            slug: Feature slug
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)
        worktree_path = self._get_worktree_path(slug)

        self.info(f"[cyan]Publishing {branch_name}...[/cyan]")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None

        if current_branch == branch_name:
            self.detail(f"Running from worktree for branch {branch_name}")
            git_dir = "."
        elif worktree_path.exists():
            self.detail(f"Running from parent repo, targeting worktree at {worktree_path}")
            git_dir = str(worktree_path)
        else:
            raise WorktreeFlowError(
                f"Worktree not found.\n"
                f"  Expected worktree: {worktree_path}\n"
                f"  Current branch: {current_branch}\n"
                f"  Run 'wtf wt-new {slug}' first"
            )

        # B05 fix: quote paths in shell commands
        cmd = f"git -C {shlex.quote(git_dir)} push -u origin {shlex.quote(branch_name)}"
        self.logger.execute(cmd, "Push branch to origin")

        if not self.dry_run:
            self.info(f"[green]✓ Published branch {branch_name} to origin and set upstream[/green]")

    def wt_pr(
        self,
        slug: str,
        base: str = "main",
        title: str | None = None,
        body: str | None = None,
        draft: bool = False,
    ) -> None:
        """
        Open PR from fork feature to upstream/main.

        Args:
            slug: Feature slug
            base: Base branch for PR (default: main)
            title: PR title (auto-generated if not provided)
            body: PR body (auto-generated if not provided)
            draft: Create as draft PR
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)

        if not self.fork_owner:
            raise WorktreeFlowError("Could not determine fork owner")

        if not self.upstream_repo:
            raise WorktreeFlowError("No upstream repo configured. Run: wtf upstream-add --repo owner/repo")

        self._require_gh()

        self.info(f"[cyan]Creating PR for {branch_name}...[/cyan]")

        self.info("Checking for existing PR...")
        check_cmd = (
            f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
            f"--head {shlex.quote(f'{self.fork_owner}:{branch_name}')} "
            f"--json number,url,state"
        )
        result = self.logger.execute(check_cmd, "Check for existing PR", check=False)

        if not self.dry_run and result.returncode == 0 and result.stdout.strip() != "[]":
            pr_data = json.loads(result.stdout)[0]
            self.info(f"[green]✓ PR already exists (#{pr_data['number']}) - State: {pr_data['state']}[/green]")
            self.info(f"  URL: {pr_data['url']}")
            self.info(f"  View: gh pr view {pr_data['number']} --repo {self.upstream_repo}")
            return

        self.info("Checking if branch needs to be pushed...")

        worktree_path = self._get_worktree_path(slug)
        git_dir = str(worktree_path) if worktree_path.exists() else "."

        quoted_dir = shlex.quote(git_dir)
        quoted_branch = shlex.quote(branch_name)

        self.logger.execute(f"git -C {quoted_dir} fetch origin", "Fetch origin", check=False)

        check_remote = self.logger.execute(
            f'git -C {quoted_dir} rev-parse --verify "origin/{branch_name}"',
            "Check if branch exists on origin",
            check=False,
        )

        if check_remote.returncode != 0:
            self.info("Branch not on origin, pushing first...")
            self.logger.execute(f"git -C {quoted_dir} push -u origin {quoted_branch}", "Push branch")
        else:
            unpushed_check = self.logger.execute(
                f'git -C {quoted_dir} rev-list --count "origin/{branch_name}..{branch_name}"',
                "Check unpushed commits",
                check=False,
            )
            if not self.dry_run and unpushed_check.stdout and int(unpushed_check.stdout.strip() or 0) > 0:
                self.info("Unpushed commits found, pushing...")
                self.logger.execute(f"git -C {quoted_dir} push origin {quoted_branch}", "Push commits")

        prefix_label = self.config.feature_branch_prefix.rstrip("/")
        if not title or title == f"{prefix_label}: {slug}":
            result = self.logger.execute(
                f'git -C {quoted_dir} log -1 --pretty=format:"%s"', "Get last commit message", check=False
            )
            title = result.stdout.strip() if not self.dry_run and result.stdout else f"{prefix_label}: {slug}"

        if not body or body == "Summary, rationale, tests":
            result = self.logger.execute(
                f'git -C {quoted_dir} log "upstream/{base}..HEAD" --pretty=format:"- %s"',
                "Get commit messages",
                check=False,
            )
            if not self.dry_run and result.stdout:
                body = (
                    f"## Changes\n\n{result.stdout}\n\n## Testing\n\n- [ ] Tests pass\n- [ ] Manual testing completed"
                )
            else:
                body = "## Summary\n\nAdd description here\n\n## Testing\n\n- [ ] Tests pass"

        create_type = "draft PR" if draft else "PR"
        self.info(f"Creating {create_type}...")

        pr_cmd = (
            f"gh pr create"
            f" --repo {shlex.quote(self.upstream_repo)}"
            f" --head {shlex.quote(f'{self.fork_owner}:{branch_name}')}"
            f" --base {shlex.quote(base)}"
            f" --title {shlex.quote(title)}"
            f" --body {shlex.quote(body)}"
        )
        if draft:
            pr_cmd += " --draft"

        result = self.logger.execute(pr_cmd, f"Create {create_type}")

        if not self.dry_run:
            if result.returncode == 0:
                self.info(f"[green]✓ {create_type.capitalize()} created successfully[/green]")
                if result.stdout:
                    self.info(f"  URL: {result.stdout.strip()}")
            else:
                msg = "Failed to create PR"
                if result.stderr:
                    msg += f"\n{result.stderr}"
                raise WorktreeFlowError(msg)

    def wt_update(
        self,
        slug: str,
        base: str = "main",
        stash: bool = False,
        dry_run_preview: bool = False,
        merge: bool = False,
        no_backup: bool = False,
    ) -> None:
        """
        Rebase or merge worktree feature on upstream/main and push.

        Args:
            slug: Feature slug
            base: Base branch name
            stash: Auto-stash uncommitted changes
            dry_run_preview: Preview what would happen
            merge: Use merge instead of rebase
            no_backup: Skip backup branch creation
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)
        worktree_path = self._get_worktree_path(slug)

        self.info(f"[cyan]Updating {branch_name} with upstream/{base}...[/cyan]")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch == branch_name:
            git_dir = "."
        elif worktree_path.exists():
            git_dir = str(worktree_path)
        else:
            raise WorktreeFlowError(f"Worktree not found. Run 'wtf wt-new {slug}' first")

        quoted_dir = shlex.quote(git_dir)

        self.info("Fetching latest from upstream...")
        self.logger.execute("git fetch upstream", "Fetch upstream")

        self.info("\n=== Current Status ===")
        behind_cmd = f'git -C {quoted_dir} rev-list --count "HEAD..upstream/{base}"'
        ahead_cmd = f'git -C {quoted_dir} rev-list --count "upstream/{base}..HEAD"'

        behind_result = self.logger.execute(behind_cmd, "Check commits behind", check=False)
        ahead_result = self.logger.execute(ahead_cmd, "Check commits ahead", check=False)

        commits_behind = int(behind_result.stdout.strip() or 0) if (not self.dry_run and behind_result.stdout) else 0
        commits_ahead = int(ahead_result.stdout.strip() or 0) if (not self.dry_run and ahead_result.stdout) else 0

        self.info(f"Branch {branch_name} is:")
        self.info(f"  {commits_behind} commits behind upstream/{base}")
        self.info(f"  {commits_ahead} commits ahead of upstream/{base}")

        if commits_behind == 0:
            self.info(f"[green]✓ Already up-to-date with upstream/{base}[/green]")
            if commits_ahead > 0:
                self.info(f"Your branch has unpushed commits. Push with: wtf wt-publish {slug}")
            return

        if dry_run_preview:
            self.info("\n[yellow]=== DRY RUN MODE ===[/yellow]")
            self.info(f"Would update {branch_name} with {commits_behind} new commits from upstream/{base}")
            self.info(f"Your {commits_ahead} local commits would be replayed on top")
            if commits_ahead > 0:
                self.info("\nYour commits to be rebased:")
                log_cmd = f'git -C {quoted_dir} log --oneline "upstream/{base}..HEAD"'
                self.logger.execute(log_cmd, "Show commits to rebase")
            return

        status_cmd = f"git -C {quoted_dir} status --porcelain"
        status_result = self.logger.execute(status_cmd, "Check for changes", check=False)
        has_uncommitted = bool(status_result.stdout.strip()) if (not self.dry_run and status_result.stdout) else False

        stashed = False
        if has_uncommitted:
            if stash:
                self.info("Stashing uncommitted changes...")
                stash_msg = shlex.quote(f"wt-update auto-stash for {branch_name}")
                stash_cmd = f"git -C {quoted_dir} stash push -m {stash_msg}"
                self.logger.execute(stash_cmd, "Stash changes")
                stashed = True
            else:
                raise WorktreeFlowError(
                    "You have uncommitted changes. Either:\n"
                    "  1. Commit your changes first\n"
                    "  2. Run with --stash to auto-stash\n"
                    "  3. Manually stash: git stash"
                )

        backup_branch = None
        if not no_backup and commits_ahead > 0:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_branch = f"{self.config.backup_branch_prefix}{branch_name}-{timestamp}"
            self.info(f"Creating backup branch: {backup_branch}")
            backup_cmd = f"git -C {quoted_dir} branch {shlex.quote(backup_branch)}"
            self.logger.execute(backup_cmd, "Create backup", check=False)

        if merge:
            self.info(f"\nMerging upstream/{base} into {branch_name}...")
            update_cmd = f'git -C {quoted_dir} merge "upstream/{base}"'
            result = self.logger.execute(update_cmd, "Merge upstream", check=False)
        else:
            self.info(f"\nRebasing {branch_name} onto upstream/{base}...")
            update_cmd = f'git -C {quoted_dir} rebase "upstream/{base}"'
            result = self.logger.execute(update_cmd, "Rebase onto upstream", check=False)

        if not self.dry_run and result.returncode != 0:
            operation = "Merge" if merge else "Rebase"
            msg = f"{operation} conflicts detected!\nResolve conflicts, then:\n  git add <resolved-files>"
            if merge:
                msg += "\n  git merge --continue"
            else:
                msg += "\n  git rebase --continue\nOr abort with: git rebase --abort"
            if backup_branch:
                msg += f"\nYour original branch is backed up as: {backup_branch}"
            raise WorktreeFlowError(msg)

        self.info("Pushing to origin...")
        if merge:
            push_cmd = f"git -C {quoted_dir} push origin {shlex.quote(branch_name)}"
        else:
            push_cmd = f"git -C {quoted_dir} push --force-with-lease origin {shlex.quote(branch_name)}"

        result = self.logger.execute(push_cmd, "Push to origin", check=False)

        if not self.dry_run and result.returncode != 0:
            raise WorktreeFlowError(
                f"Push failed. Remote may have been updated.\n"
                f"If you're sure, use: git push --force origin {branch_name}"
            )

        if stashed:
            self.info("Restoring stashed changes...")
            pop_cmd = f"git -C {quoted_dir} stash pop"
            self.logger.execute(pop_cmd, "Restore stash", check=False)

        self.info(f"[green]✓ Successfully updated {branch_name} with upstream/{base}[/green]")

    def wt_clean(
        self,
        slug: str,
        force_delete: bool = False,
        wt_force: bool = False,
        dry_run_preview: bool = False,
        confirm: bool = False,
    ) -> None:
        """
        Remove worktree and prune branches.

        Args:
            slug: Feature slug
            force_delete: Force delete branch even if not merged
            wt_force: Force remove worktree with uncommitted changes
            dry_run_preview: Preview what would be deleted
            confirm: Skip confirmation prompts
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)
        worktree_path = self._get_worktree_path(slug)

        self.info("[cyan]=== Worktree Clean Summary ===[/cyan]")
        self.info(f"Branch:       {branch_name}")
        self.info(f"Worktree:     {worktree_path}")
        self.info("")

        has_worktree = worktree_path.exists()
        has_local_branch = branch_name in self.repo.heads
        has_remote_branch = False
        has_uncommitted = False
        has_pr = False

        if has_worktree:
            self.info(f"✓ Worktree exists at {worktree_path}")

            quoted_path = shlex.quote(str(worktree_path))
            status_cmd = f"git -C {quoted_path} status --porcelain"
            result = self.logger.execute(status_cmd, "Check for changes", check=False)
            if not self.dry_run and result.stdout:
                has_uncommitted = True
                self.info("[yellow]⚠️  Has uncommitted changes:[/yellow]")
                for line in result.stdout.strip().split("\n")[:5]:
                    self.info(f"  {line}")
        else:
            self.info(f"✗ No worktree at {worktree_path}")

        if has_local_branch:
            self.info(f"✓ Local branch {branch_name} exists")

        check_remote = self.logger.execute(
            f"git ls-remote --exit-code --heads origin {shlex.quote(branch_name)}", "Check remote branch", check=False
        )
        if check_remote.returncode == 0:
            has_remote_branch = True
            self.info(f"✓ Remote branch origin/{branch_name} exists")

        if shutil.which("gh") and self.fork_owner and self.upstream_repo:
            pr_check = self.logger.execute(
                f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
                f"--head {shlex.quote(f'{self.fork_owner}:{branch_name}')} "
                f"--json number,state",
                "Check for PR",
                check=False,
            )
            stdout = pr_check.stdout.strip() if not self.dry_run else ""
            if pr_check.returncode == 0 and stdout and stdout != "[]":
                try:
                    pr_data = json.loads(pr_check.stdout)[0]
                    has_pr = True
                    self.info(f"[yellow]⚠️  Has PR #{pr_data['number']} ({pr_data['state']})[/yellow]")
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass

        if dry_run_preview:
            self.info("\n[yellow]=== DRY RUN MODE - No changes will be made ===[/yellow]")
            self.info("Would perform:")
            if has_worktree:
                self.info(f"  - Remove worktree at {worktree_path}")
            if has_local_branch:
                self.info(f"  - Delete local branch {branch_name}")
            if has_remote_branch:
                self.info(f"  - Delete remote branch origin/{branch_name}")
            self.info("  - Prune remote references")
            return

        if has_uncommitted and not wt_force:
            raise WorktreeFlowError("Worktree has uncommitted changes. Use --wt-force to force removal.")

        if has_pr and not confirm:
            raise WorktreeFlowError("This branch has an open PR. Use --confirm to proceed anyway.")

        current_dir = Path.cwd()
        if current_dir == worktree_path or worktree_path in current_dir.parents:
            raise WorktreeFlowError(
                "Cannot remove worktree while inside it.\nPlease cd to parent repo or another directory first."
            )

        if not confirm and (has_worktree or has_local_branch or has_remote_branch):
            self.info("\nThis will:")
            if has_worktree:
                self.info(f"  - Remove worktree at {worktree_path}")
            if has_local_branch:
                self.info(f"  - Delete local branch {branch_name}")
            if has_remote_branch:
                self.info(f"  - Delete remote branch origin/{branch_name}")
            raise WorktreeFlowError("Run with --confirm to proceed, or --dry-run to preview.")

        self.info("\n[cyan]=== Cleaning ===[/cyan]")

        if has_worktree:
            self.info("Removing worktree...")
            force_flag = "--force" if wt_force else ""
            rm_cmd = f"git worktree remove {force_flag} {shlex.quote(str(worktree_path))}"
            self.logger.execute(rm_cmd, "Remove worktree")

        if has_local_branch:
            self.info("Deleting local branch...")
            delete_flag = "-D" if force_delete else "-d"
            del_cmd = f"git branch {delete_flag} {shlex.quote(branch_name)}"
            self.logger.execute(del_cmd, "Delete branch", check=False)

        if has_remote_branch:
            self.info("Deleting remote branch...")
            push_cmd = f"git push origin --delete {shlex.quote(branch_name)}"
            self.logger.execute(push_cmd, "Delete remote branch", check=False)

        self.info("Pruning remote references...")
        self.logger.execute("git remote prune origin", "Prune origin", check=False)
        self.logger.execute("git worktree prune", "Prune worktrees", check=False)

        self.info(f"[green]✓ Cleaned worktree and branches for {branch_name}[/green]")

    @staticmethod
    def _parse_worktree_porcelain(output: str) -> list:
        """Parse the porcelain output of 'git worktree list --porcelain'."""
        worktrees = []
        current_wt = {}

        for line in output.strip().split("\n"):
            if line.startswith("worktree "):
                if current_wt:
                    worktrees.append(current_wt)
                current_wt = {"path": line[9:]}
            elif line.startswith("HEAD "):
                current_wt["head"] = line[5:]
            elif line.startswith("branch "):
                current_wt["branch"] = line[7:].removeprefix("refs/heads/")
            elif line == "detached":
                current_wt["branch"] = "(detached)"

        if current_wt:
            worktrees.append(current_wt)

        return worktrees

    def wt_list(self) -> None:
        """
        List all worktrees with their status, last activity, and PR info.

        Bash equivalents:
            git worktree list --porcelain
            git -C <path> log -1 --format=%ci
            gh pr list --head <branch> --json number,state
        """
        self.info("[cyan]=== Git Worktrees ===[/cyan]\n")

        result = self.logger.execute("git worktree list --porcelain", "List worktrees")

        if not self.dry_run and result.stdout:
            worktrees = self._parse_worktree_porcelain(result.stdout)

            # Enrich each worktree with last activity and PR info
            for wt in worktrees:
                wt_path = wt["path"]
                branch = wt.get("branch", "(detached)")

                # Last commit date
                date_cmd = f"git -C {shlex.quote(wt_path)} log -1 --format=%ci 2>/dev/null"
                date_result = self.logger.execute(date_cmd, "Get last commit date", check=False)
                if date_result.stdout and date_result.stdout.strip():
                    try:
                        last_date = datetime.fromisoformat(date_result.stdout.strip().replace(" ", "T", 1))
                        wt["last_activity"] = last_date.strftime("%Y-%m-%d")
                        days_ago = (datetime.now(tz=last_date.tzinfo) - last_date).days
                        wt["days_ago"] = days_ago
                        wt["stale"] = days_ago > 30
                    except (ValueError, TypeError):
                        wt["last_activity"] = "unknown"
                        wt["days_ago"] = None
                        wt["stale"] = False
                else:
                    wt["last_activity"] = "unknown"
                    wt["days_ago"] = None
                    wt["stale"] = False

                # PR status (if gh is available)
                wt["pr"] = None
                if shutil.which("gh") and self.fork_owner and self.upstream_repo and branch != "(detached)":
                    pr_cmd = (
                        f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
                        f"--head {shlex.quote(f'{self.fork_owner}:{branch}')} "
                        f"--json number,state --limit 1"
                    )
                    pr_result = self.logger.execute(pr_cmd, "Check PR status", check=False)
                    if pr_result.returncode == 0 and pr_result.stdout.strip() not in ("", "[]"):
                        try:
                            pr_data = json.loads(pr_result.stdout)
                            if pr_data:
                                wt["pr"] = {"number": pr_data[0]["number"], "state": pr_data[0]["state"]}
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass

            if self.json_output:
                click.echo(json.dumps(worktrees, indent=2))
                return

            table = Table(show_header=True)
            table.add_column("Path", style="cyan")
            table.add_column("Branch", style="green")
            table.add_column("Last Activity")
            table.add_column("PR")

            for wt in worktrees:
                branch = wt.get("branch", "(detached)")
                activity = wt.get("last_activity", "unknown")
                days = wt.get("days_ago")
                if days is not None:
                    if wt.get("stale"):
                        activity = f"[yellow]{activity} ({days}d ago) STALE[/yellow]"
                    else:
                        activity = f"{activity} ({days}d ago)"

                pr_info = wt.get("pr")
                pr_display = ""
                if pr_info:
                    state_colors = {"OPEN": "green", "CLOSED": "red", "MERGED": "blue"}
                    color = state_colors.get(pr_info["state"], "white")
                    pr_display = f"[{color}]#{pr_info['number']} {pr_info['state']}[/{color}]"

                table.add_row(wt["path"], branch, activity, pr_display)

            self.info(table)
        else:
            if self.json_output:
                click.echo("[]")
                return
            self.info("No worktrees found")

        self.info("\nTo clean a worktree: wtf wt-clean SLUG")
        self.info("To clean stale refs: git worktree prune")

    def wt_status(self, slug: str, base: str = "main") -> None:
        """
        Show comprehensive status for a specific worktree.

        Args:
            slug: Feature slug
            base: Base branch name (default: main)
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)
        worktree_path = self._get_worktree_path(slug)

        self.info(Panel.fit(f"[bold cyan]Worktree Status: {branch_name}[/bold cyan]", style="cyan"))

        if not worktree_path.exists():
            raise WorktreeFlowError(f"Worktree not found at: {worktree_path}\n  Run: wtf wt-new {slug}")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None

        git_dir = "." if current_branch == branch_name else str(worktree_path)

        quoted_dir = shlex.quote(git_dir)

        head_cmd = f'git -C {quoted_dir} log -1 --pretty=format:"%h %s"'
        head_result = self.logger.execute(head_cmd, "Get HEAD commit", check=False)
        head_info = head_result.stdout.strip() if (not self.dry_run and head_result.stdout) else "(unknown)"

        self.info("\n[dim]Fetching latest from remotes...[/dim]")
        self.logger.execute("git fetch upstream", "Fetch upstream", check=False)
        self.logger.execute("git fetch origin", "Fetch origin", check=False)

        behind_upstream_cmd = f'git -C {quoted_dir} rev-list --count "HEAD..upstream/{base}"'
        ahead_upstream_cmd = f'git -C {quoted_dir} rev-list --count "upstream/{base}..HEAD"'

        behind_upstream_result = self.logger.execute(behind_upstream_cmd, "Check commits behind upstream", check=False)
        ahead_upstream_result = self.logger.execute(ahead_upstream_cmd, "Check commits ahead of upstream", check=False)

        def _parse_count(result: subprocess.CompletedProcess[str]) -> int:
            if not self.dry_run and result.stdout:
                return int(result.stdout.strip() or 0)
            return 0

        commits_behind_upstream = _parse_count(behind_upstream_result)
        commits_ahead_upstream = _parse_count(ahead_upstream_result)

        ahead_origin_cmd = f'git -C {quoted_dir} rev-list --count "origin/{branch_name}..HEAD"'
        ahead_origin_result = self.logger.execute(ahead_origin_cmd, "Check unpushed commits", check=False)
        commits_unpushed = _parse_count(ahead_origin_result)

        status_cmd = f"git -C {quoted_dir} status --porcelain"
        status_result = self.logger.execute(status_cmd, "Check working directory", check=False)

        if not self.dry_run and status_result.stdout:
            status_lines = status_result.stdout.strip().split("\n")
            modified = sum(1 for line in status_lines if line and line[0] in ["M", "A", "D", "R", "C"])
            untracked = sum(1 for line in status_lines if line.startswith("??"))
            total_changes = len(status_lines)
        else:
            modified = 0
            untracked = 0
            total_changes = 0

        pr_info = None
        if shutil.which("gh") and self.fork_owner and self.upstream_repo:
            pr_cmd = (
                f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
                f"--head {shlex.quote(f'{self.fork_owner}:{branch_name}')} "
                f"--json number,url,state,title"
            )
            pr_result = self.logger.execute(pr_cmd, "Check for PR", check=False)

            if not self.dry_run and pr_result.returncode == 0 and pr_result.stdout.strip() != "[]":
                pr_data = json.loads(pr_result.stdout)[0]
                pr_info = pr_data

        log_cmd = f"git -C {quoted_dir} log --oneline -n 5"
        log_result = self.logger.execute(log_cmd, "Get recent commits", check=False)
        recent_commits = []
        if not self.dry_run and log_result.stdout:
            for line in log_result.stdout.strip().split("\n"):
                if line:
                    recent_commits.append(line)

        # === JSON Output ===
        if self.json_output:
            data = {
                "slug": slug,
                "branch": branch_name,
                "path": str(worktree_path),
                "head": head_info,
                "commits_behind_upstream": commits_behind_upstream,
                "commits_ahead_upstream": commits_ahead_upstream,
                "commits_unpushed": commits_unpushed,
                "modified_files": modified,
                "untracked_files": untracked,
                "total_changes": total_changes,
                "pr": pr_info,
                "recent_commits": recent_commits,
            }
            click.echo(json.dumps(data, indent=2))
            return

        # === Display Status ===

        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Property", style="cyan")
        info_table.add_column("Value")

        info_table.add_row("Branch:", branch_name)
        info_table.add_row("Path:", str(worktree_path))
        info_table.add_row("HEAD:", head_info)

        self.info("\n")
        self.info(info_table)

        self.info("\n[bold cyan]Sync Status:[/bold cyan]")
        status_table = Table(show_header=False, box=None, padding=(0, 2))
        status_table.add_column("Metric", style="cyan")
        status_table.add_column("Count")
        status_table.add_column("Status")

        if commits_behind_upstream > 0:
            status_table.add_row(
                f"Behind upstream/{base}:", str(commits_behind_upstream), "[yellow]⚠️  Need to update[/yellow]"
            )
        else:
            status_table.add_row(f"Behind upstream/{base}:", "0", "[green]✓ Up-to-date[/green]")

        if commits_ahead_upstream > 0:
            status_table.add_row(
                f"Ahead of upstream/{base}:", str(commits_ahead_upstream), "[blue]ℹ️  Local changes[/blue]"
            )

        if commits_unpushed > 0:
            status_table.add_row("Unpushed commits:", str(commits_unpushed), "[yellow]⚠️  Not pushed[/yellow]")
        else:
            status_table.add_row("Unpushed commits:", "0", "[green]✓ All pushed[/green]")

        self.info(status_table)

        self.info("\n[bold cyan]Working Directory:[/bold cyan]")
        if total_changes > 0:
            wd_table = Table(show_header=False, box=None, padding=(0, 2))
            wd_table.add_column("Type", style="cyan")
            wd_table.add_column("Count")

            if modified > 0:
                wd_table.add_row("Modified/Staged:", str(modified))
            if untracked > 0:
                wd_table.add_row("Untracked:", str(untracked))

            self.info(wd_table)
            self.info(f"[yellow]⚠️  {total_changes} uncommitted change(s)[/yellow]")
        else:
            self.info("[green]✓ Clean working directory[/green]")

        if pr_info:
            self.info("\n[bold cyan]Pull Request:[/bold cyan]")

            state_colors = {"OPEN": "green", "CLOSED": "red", "MERGED": "blue"}
            state_color = state_colors.get(pr_info["state"], "white")

            pr_table = Table(show_header=False, box=None, padding=(0, 2))
            pr_table.add_column("Property", style="cyan")
            pr_table.add_column("Value")

            pr_table.add_row("Number:", f"#{pr_info['number']}")
            pr_table.add_row("State:", f"[{state_color}]{pr_info['state']}[/{state_color}]")
            pr_table.add_row("Title:", pr_info["title"])
            pr_table.add_row("URL:", pr_info["url"])

            self.info(pr_table)
        else:
            self.info("\n[dim]No pull request found[/dim]")

        if recent_commits:
            self.info("\n[bold cyan]Recent Commits:[/bold cyan]")
            for commit in recent_commits:
                self.info(f"  {commit}")

        self.info("\n[bold cyan]Suggested Actions:[/bold cyan]")
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
                self.info(f"  {suggestion}")
        else:
            self.info("  [green]✓ Everything looks good![/green]")

    # ========== Navigation & Editor Commands ==========

    def wt_cd(self, slug: str) -> None:
        """
        Print the absolute path to a worktree directory.

        Designed for shell composition: cd $(wtf wt-cd my-feature)

        Args:
            slug: Feature slug
        """
        slug = self.validator.validate_slug(slug)
        worktree_path = self._get_worktree_path(slug)

        if not worktree_path.exists():
            raise WorktreeFlowError(f"Worktree not found at: {worktree_path}\n  Create it first: wtf wt-new {slug}")

        # Use click.echo to print to stdout (not suppressed by --quiet)
        click.echo(str(worktree_path))

    def wt_open(self, slug: str, editor: str | None = None) -> None:
        """
        Open a worktree directory in the user's editor.

        Detection order: --editor flag, $EDITOR env, code, vim, nano.

        Args:
            slug: Feature slug
            editor: Optional editor command override
        """
        slug = self.validator.validate_slug(slug)
        worktree_path = self._get_worktree_path(slug)

        if not worktree_path.exists():
            raise WorktreeFlowError(f"Worktree not found at: {worktree_path}\n  Create it first: wtf wt-new {slug}")

        # Resolve editor
        if not editor:
            editor = os.environ.get("EDITOR")
        if not editor:
            for candidate in ("code", "vim", "nano"):
                if shutil.which(candidate):
                    editor = candidate
                    break
        if not editor:
            raise WorktreeFlowError(
                "No editor found. Set $EDITOR or pass --editor.\n  Example: wtf wt-open my-feature --editor code"
            )

        self.info(f"[cyan]Opening {worktree_path} in {editor}...[/cyan]")
        self.logger.log(f"{editor} {shlex.quote(str(worktree_path))}", "Open in editor")
        if not self.dry_run:
            subprocess.Popen([editor, str(worktree_path)])  # noqa: S603

    def wt_reopen(self, slug: str, base: str = "main") -> None:
        """
        Recreate a worktree from an existing remote branch.

        Useful when a worktree was cleaned up but the branch still exists
        on the remote, or when resuming work on another machine.

        Bash equivalents:
            git fetch origin
            git worktree add {path} -b {branch} origin/{branch}

        Args:
            slug: Feature slug
            base: Base branch name
        """
        slug = self.validator.validate_slug(slug)
        branch_name = self._make_branch_name(slug)
        worktree_path = self._get_worktree_path(slug)

        if worktree_path.exists():
            raise WorktreeFlowError(
                f"Worktree already exists at: {worktree_path}\n"
                f"  Use it: cd {worktree_path}\n"
                f"  Or clean it first: wtf wt-clean {slug}"
            )

        self.info(f"[cyan]Reopening worktree for {branch_name}...[/cyan]")

        # Fetch latest from origin
        self.info("Fetching from origin...")
        self.logger.execute("git fetch origin", "Fetch origin")

        # Check if branch exists on remote
        check_cmd = f"git ls-remote --exit-code --heads origin {shlex.quote(branch_name)}"
        result = self.logger.execute(check_cmd, "Check remote branch", check=False)

        if not self.dry_run and result.returncode != 0:
            raise WorktreeFlowError(
                f"Branch {branch_name} not found on origin.\n  To create a new worktree instead: wtf wt-new {slug}"
            )

        # Check if branch exists locally
        quoted_path = shlex.quote(str(worktree_path))
        quoted_branch = shlex.quote(branch_name)

        if branch_name in self.repo.heads:
            self.info(f"Using existing local branch {branch_name}")
            cmd = f"git worktree add {quoted_path} {quoted_branch}"
        else:
            self.info(f"Creating local branch {branch_name} tracking origin/{branch_name}")
            cmd = f"git worktree add {quoted_path} -b {quoted_branch} origin/{quoted_branch}"

        self.logger.execute(cmd, "Create worktree from remote branch")

        if not self.dry_run:
            self.info(f"[green]✓ Reopened worktree: {worktree_path}[/green]")
            self.info(f"[green]✓ Branch: {branch_name}[/green]")
            self.info(f"\nNext: cd {worktree_path}")

    def init_config(self) -> None:
        """
        Interactive configuration wizard that creates .worktreeflow.toml.

        Auto-detects values from git remotes and asks for confirmation.
        """
        from worktreeflow.config import generate_config

        config_path = self.root / ".worktreeflow.toml"
        if config_path.exists():
            self.info(f"[yellow]Config file already exists: {config_path}[/yellow]")
            if not click.confirm("Overwrite?", default=False):
                self.info("Aborted.")
                return

        self.info("[cyan]Worktreeflow Configuration Wizard[/cyan]\n")

        # Auto-detect values
        detected_upstream = self.upstream_repo
        detected_base = self.config.base_branch

        # Prompt for values with detected defaults
        upstream = click.prompt(
            "Upstream repo (owner/repo)",
            default=detected_upstream or "",
        )
        base_branch = click.prompt("Base branch", default=detected_base)
        feature_prefix = click.prompt(
            "Feature branch prefix",
            default=self.config.feature_branch_prefix,
        )
        use_ssh = click.confirm("Use SSH URLs?", default=self.config.use_ssh)
        auto_stash = click.confirm(
            "Auto-stash uncommitted changes during updates?",
            default=self.config.auto_stash,
        )
        create_backups = click.confirm(
            "Create backup branches before destructive operations?",
            default=self.config.create_backup_branches,
        )
        draft_pr = click.confirm(
            "Create PRs as drafts by default?",
            default=self.config.default_draft_pr,
        )

        content = generate_config(
            upstream_repo=upstream if upstream else None,
            base_branch=base_branch,
            feature_branch_prefix=feature_prefix,
            use_ssh=use_ssh,
            auto_stash=auto_stash,
            create_backup_branches=create_backups,
            default_draft_pr=draft_pr,
        )

        if not self.dry_run:
            config_path.write_text(content)
            self.info(f"\n[green]✓ Config written to {config_path}[/green]")
        else:
            self.info(f"\n[yellow][DRY-RUN] Would write config to {config_path}[/yellow]")
            self.info(content)

    # ========== Check Commands ==========

    def check_repo(self) -> None:
        """
        Verify we're inside a Git repository.

        Bash equivalent:
            git rev-parse --show-toplevel
        """
        self.info("[green]✓ Inside Git repository[/green]")
        self.info(f"  Root: {self.root}")
        self.info(f"  Name: {self.repo_name}")

    def check_origin(self) -> None:
        """
        Verify 'origin' remote exists.

        Bash equivalent:
            git remote get-url origin
        """
        if "origin" not in self.repo.remotes:
            raise WorktreeFlowError(
                "Missing 'origin' remote (your fork).\n"
                "  Add it with: git remote add origin <url>\n"
                "  Or run: wtf fork-setup"
            )

        origin_url = self.repo.remote("origin").url
        self.info("[green]✓ Origin remote exists[/green]")
        self.info(f"  URL: {origin_url}")
        if self.fork_owner:
            self.info(f"  Owner: {self.fork_owner}")

    def check_upstream(self) -> None:
        """
        Verify 'upstream' remote exists.

        Bash equivalent:
            git remote get-url upstream
        """
        if "upstream" not in self.repo.remotes:
            upstream_display = self.upstream_repo or "(not configured)"
            raise WorktreeFlowError(
                f"Missing 'upstream' remote ({upstream_display}).\n  Add it with: wtf upstream-add --repo owner/repo"
            )

        upstream_url = self.repo.remote("upstream").url
        self.info("[green]✓ Upstream remote exists[/green]")
        self.info(f"  URL: {upstream_url}")
        self.info(f"  Repo: {self.upstream_repo}")
