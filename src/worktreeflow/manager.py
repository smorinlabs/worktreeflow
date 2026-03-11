"""
Core Git workflow manager for worktreeflow.

Contains all Git workflow operations using GitPython.
"""

import json
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import git
from git import GitCommandError, Repo
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from worktreeflow.config import RepoConfig, load_config
from worktreeflow.logger import BashCommandLogger
from worktreeflow.validator import SafetyValidator

console = Console()


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

        self._init_repo_info()

    def _init_repo_info(self) -> None:
        """Initialize repository information and configuration."""
        try:
            self.logger.log("git rev-parse --show-toplevel", "Find repository root")
            self.repo = Repo(search_parent_directories=True)
            assert self.repo.working_tree_dir is not None
            self.root = Path(self.repo.working_tree_dir)

            self.repo_name = self.root.name

            # Load config file before detecting remotes
            load_config(self.root)

            self._detect_fork_owner()
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
            match = re.search(r"(?:github\.com[:/])([^/]+)/.*", origin_url)
            if match:
                self.fork_owner = match.group(1)

        # Fallback to gh CLI if available
        if not self.fork_owner and shutil.which("gh"):
            try:
                result = self.logger.execute("gh api user -q .login", "Get GitHub username")
                if not self.dry_run and result.returncode == 0:
                    self.fork_owner = result.stdout.strip()
            except (subprocess.SubprocessError, OSError):
                pass

    def _detect_upstream_repo(self) -> None:
        """
        Detect upstream repository from remote URL.

        Falls back to config file value, or None if neither is available.
        B08 fix: No longer hardcodes a default upstream repo.
        B09 fix: Uses robust URL parsing that handles malformed URLs gracefully.
        """
        # Start with config file value (may be None)
        self.upstream_repo = RepoConfig.DEFAULT_UPSTREAM_REPO

        if RepoConfig.UPSTREAM_REMOTE in self.repo.remotes:
            upstream_url = self.repo.remote("upstream").url
            self.logger.log("git remote get-url upstream", "Get upstream URL")

            # B09 fix: robust URL parsing with proper error handling
            match = re.search(r"(?:github\.com[:/])([^/]+/[^/.]+)", upstream_url)
            if match:
                self.upstream_repo = match.group(1).removesuffix(".git")
            else:
                console.print(f"[yellow]Warning: Could not parse upstream URL: {upstream_url}[/yellow]")

    def _get_worktree_path(self, slug: str) -> Path:
        """
        Get the worktree path for a given slug.

        B05 fix: Uses Path operations instead of string interpolation.
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

        table = Table(show_header=False, box=None)
        table.add_column("Property", style="cyan")
        table.add_column("Value")

        table.add_row("Repo root:", str(self.root))
        table.add_row("Repo name:", self.repo_name)
        table.add_row("Upstream repo:", self.upstream_repo or "[yellow]Not configured[/yellow]")
        table.add_row("Fork owner:", self.fork_owner or "[red]Not detected[/red]")

        origin_url = self.repo.remote("origin").url if "origin" in self.repo.remotes else "[red]Missing[/red]"
        upstream_url = self.repo.remote("upstream").url if "upstream" in self.repo.remotes else "[red]Missing[/red]"

        table.add_row("Origin URL:", origin_url)
        table.add_row("Upstream URL:", upstream_url)

        has_gh = "✓" if shutil.which("gh") else "✗"
        table.add_row("Has gh CLI:", f"[green]{has_gh}[/green]" if has_gh == "✓" else f"[red]{has_gh}[/red]")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = f"(detached) {self.repo.head.commit.hexsha[:7]}"
        table.add_row("Current branch:", current_branch)

        is_dirty = "Yes" if self.repo.is_dirty() else "No"
        table.add_row("Has changes:", f"[yellow]{is_dirty}[/yellow]" if is_dirty == "Yes" else is_dirty)

        # Show config file status
        config_path = self.root / ".worktreeflow.toml"
        table.add_row("Config file:", str(config_path) if config_path.exists() else "[dim]Not found[/dim]")

        console.print(table)

        issues = []
        if "origin" not in self.repo.remotes:
            issues.append("Missing 'origin' remote (your fork)")
        if "upstream" not in self.repo.remotes:
            issues.append("Missing 'upstream' remote. Run: wtf upstream-add")
        if not self.fork_owner:
            issues.append("Could not detect fork owner")
        if not shutil.which("gh"):
            issues.append("GitHub CLI not found. Install from: https://cli.github.com/")
        if not self.upstream_repo:
            issues.append("Upstream repo not configured. Run: wtf upstream-add --repo owner/repo")

        if issues:
            console.print("\n[yellow]Issues found:[/yellow]")
            for issue in issues:
                console.print(f"  • {issue}")
        else:
            console.print("\n[green]✓ Environment check passed[/green]")

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
            console.print("[red]ERROR: No upstream repo specified.[/red]")
            console.print("  Run: wtf upstream-add --repo owner/repo")
            sys.exit(1)

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
            except (OSError, KeyError) as e:
                console.print(f"[yellow]Warning: Could not set pull.ff config: {e}[/yellow]")
        console.print("[green]✓ Configured pull.ff=only[/green]")

        console.print("\nRemotes:")
        if not self.dry_run:
            for remote in self.repo.remotes:
                console.print(f"  {remote.name}: {remote.url}")

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
        if not shutil.which("gh"):
            console.print("[red]GitHub CLI required. Install from: https://cli.github.com/[/red]")
            sys.exit(1)

        if not self.upstream_repo:
            console.print("[red]ERROR: No upstream repo configured.[/red]")
            console.print("  Run: wtf upstream-add --repo owner/repo")
            sys.exit(1)

        console.print("[cyan]Setting up fork...[/cyan]")

        result = self.logger.execute("gh api user -q .login", "Get GitHub username")
        if self.dry_run:
            github_user = "YOUR_USERNAME"
        else:
            if result.returncode != 0:
                console.print("[red]Not authenticated. Run: gh auth login[/red]")
                sys.exit(1)
            github_user = result.stdout.strip()

        console.print(f"GitHub user: {github_user}")

        # B09 fix: safe repo name extraction
        parts = self.upstream_repo.split("/")
        if len(parts) != 2 or not parts[1]:
            console.print(f"[red]ERROR: Invalid upstream repo format: {self.upstream_repo}[/red]")
            console.print("  Expected format: owner/repo")
            sys.exit(1)
        repo_name = parts[1]

        fork_check_cmd = f"gh repo view {shlex.quote(f'{github_user}/{repo_name}')} --json name 2>/dev/null"
        result = self.logger.execute(fork_check_cmd, "Check if fork exists", check=False)

        if result.returncode != 0:
            console.print("Creating fork...")
            fork_cmd = f"gh repo fork {shlex.quote(self.upstream_repo)} --clone=false"
            self.logger.execute(fork_cmd, "Create fork")
            console.print(f"[green]Fork created: {github_user}/{repo_name}[/green]")
        else:
            console.print(f"[green]Fork already exists: {github_user}/{repo_name}[/green]")

        console.print("\nConfiguring remotes...")

        if "origin" in self.repo.remotes:
            origin_url = self.repo.remote("origin").url
            if self.upstream_repo in origin_url:
                if "upstream" not in self.repo.remotes:
                    console.print("Renaming origin to upstream...")
                    self.logger.log("git remote rename origin upstream")
                    if not self.dry_run:
                        self.repo.remote("origin").rename("upstream")
                else:
                    console.print("Removing duplicate origin...")
                    self.logger.log("git remote remove origin")
                    if not self.dry_run:
                        self.repo.delete_remote(self.repo.remote("origin"))

        fork_url = f"git@github.com:{github_user}/{repo_name}.git"
        if "origin" not in self.repo.remotes:
            console.print("Adding fork as origin...")
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
        console.print(f"[cyan]Syncing {base} with upstream...[/cyan]")

        self.validator.check_uncommitted_changes(self.repo, stash=False)

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch and current_branch != base:
            console.print(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")

        console.print("Fetching upstream...")
        self.logger.log("git fetch upstream")
        if not self.dry_run:
            self.repo.remote("upstream").fetch()

        # B07 fix: specific exception handling
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
            except GitCommandError as e:
                console.print(f"[yellow]Warning: Could not list new commits: {e}[/yellow]")

        # Switch to base branch
        self.logger.log(f"git switch {base}")
        if not self.dry_run:
            self.repo.heads[base].checkout()

        console.print(f"Fast-forwarding {base}...")
        self.logger.log(f"git merge --ff-only upstream/{base}")

        if not self.dry_run:
            try:
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(self.repo.head.commit, upstream_ref.commit)

                if not merge_base:
                    console.print(f"[red]ERROR: No common ancestor between {base} and upstream/{base}[/red]")
                    console.print("The repositories appear to have unrelated histories.")
                    console.print("To force-sync (DESTRUCTIVE): wtf sync-main-force --confirm")
                    sys.exit(1)

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
                console.print(f"[red]ERROR: {e.stderr}[/red]")
                sys.exit(1)

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
                except GitCommandError as e:
                    console.print(f"[yellow]Warning: Could not list commits: {e}[/yellow]")

            console.print("\nTo proceed, run:")
            console.print("  wtf sync-main-force --confirm")
            sys.exit(1)

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch != base:
            if current_branch:
                console.print(f"[yellow]WARNING: You're on branch '{current_branch}', switching to '{base}'[/yellow]")
            else:
                console.print(f"[yellow]WARNING: HEAD is detached, switching to '{base}'[/yellow]")
            self.logger.log(f"git switch {base}")
            if not self.dry_run:
                self.repo.heads[base].checkout()

        if self.repo.is_dirty() and not force:
            console.print("[red]ERROR: You have uncommitted changes that will be LOST![/red]")
            console.print("  To see changes: git status")
            console.print("  To force anyway: wtf sync-main-force --confirm --force")
            sys.exit(1)

        backup_branch = f"backup/{base}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        console.print(f"Creating backup branch: {backup_branch}")
        self.logger.log(f"git branch {backup_branch}")
        if not self.dry_run:
            self.repo.create_head(backup_branch)

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
            git rev-list origin/main..main
            git merge-base --is-ancestor origin/main upstream/main
            git push origin upstream/main:main

        Args:
            base: Base branch name
        """
        console.print(f"[cyan]Zero-checkout fast-forward sync of {base}...[/cyan]")

        console.print(f"Checking local {base} status...")
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
                except GitCommandError as e:
                    console.print(f"[yellow]Warning: Could not check unpushed commits: {e}[/yellow]")

        console.print(f"Checking if origin/{base} can fast-forward to upstream/{base}...")
        self.logger.log(f"git merge-base --is-ancestor origin/{base} upstream/{base}")

        if not self.dry_run:
            try:
                origin_ref = self.repo.remote("origin").refs[base]
                upstream_ref = self.repo.remote("upstream").refs[base]
                merge_base = self.repo.merge_base(origin_ref.commit, upstream_ref.commit)

                if not merge_base:
                    console.print(f"[red]ERROR: No common ancestor between origin/{base} and upstream/{base}[/red]")
                    console.print("The repositories appear to have unrelated histories.")
                    console.print("To force-sync (DESTRUCTIVE): wtf sync-main-force --confirm")
                    sys.exit(1)

                if merge_base[0] != origin_ref.commit:
                    console.print(f"[red]ERROR: Cannot fast-forward origin/{base} to upstream/{base}[/red]")
                    console.print(f"origin/{base} has diverged from upstream/{base}")
                    console.print("\nTo see the divergence:")
                    console.print(f"  git log --oneline --graph upstream/{base} origin/{base}")
                    console.print("\nTo force-sync (DESTRUCTIVE):")
                    console.print("  wtf sync-main-force --confirm")
                    sys.exit(1)

                new_commits = list(self.repo.iter_commits(f"{origin_ref.commit}..{upstream_ref.commit}"))
                if new_commits:
                    console.print("\nNew commits to be synced:")
                    for commit in new_commits[:10]:
                        console.print(f"  {commit.hexsha[:7]} {commit.summary}")
                else:
                    console.print("[green]Already up-to-date[/green]")
                    return

            except GitCommandError as e:
                console.print(f"[red]ERROR: {e}[/red]")
                sys.exit(1)

        console.print("Syncing...")
        self.logger.log(f"git push origin upstream/{base}:{base}")
        if not self.dry_run:
            try:
                self.repo.remote("origin").push(f"upstream/{base}:{base}")
                console.print(f"[green]✓ Successfully fast-forwarded origin/{base} to upstream/{base}[/green]")
            except GitCommandError:
                console.print("[red]ERROR: Push failed. This might happen if:[/red]")
                console.print(f"  - Someone else pushed to origin/{base} in the meantime")
                console.print("  - You don't have push permissions")
                console.print("  Try: wtf sync-main")
                sys.exit(1)

    # ========== Worktree Management ==========

    def wt_new(self, slug: str, base: str = "main", no_sync: bool = False) -> None:
        """
        Create worktree and new feature branch from fork/main.

        Bash equivalents:
            git worktree add {path} -b feat/{slug} {base}
            git worktree add {path} {branch}  # if branch exists

        Args:
            slug: Feature slug
            base: Base branch to branch from
            no_sync: Skip sync_main before creating worktree (B04 fix)
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"

        self.validator.validate_branch_name(branch_name)

        console.print(f"[cyan]Creating worktree for {branch_name}...[/cyan]")

        # B04 fix: sync is now optional
        if not no_sync:
            try:
                self.sync_main(base=base)
            except (GitCommandError, SystemExit):
                console.print("[yellow]Warning: Could not sync main. Continuing with worktree creation.[/yellow]")
        else:
            console.print("[dim]Skipping sync (--no-sync)[/dim]")

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
                    console.print(f"[green]✓ Worktree already exists at: {worktree_path}[/green]")
                    console.print(f"  Branch: {branch_name}")
                    console.print(f"  To use it: cd {worktree_path}")
                    console.print(f"  To remove it: wtf wt-clean {slug}")
                    return
            except (subprocess.SubprocessError, OSError):
                pass

            console.print(f"[red]ERROR: Directory exists but is not a git worktree: {worktree_path}[/red]")
            console.print("  Remove it manually or choose a different SLUG")
            sys.exit(1)

        # B05 fix: use shlex.quote for paths in shell commands
        quoted_path = shlex.quote(str(worktree_path))
        quoted_branch = shlex.quote(branch_name)
        quoted_base = shlex.quote(base)

        if branch_name in self.repo.heads:
            console.print(f"Branch {branch_name} already exists locally, using it for worktree")
            cmd = f"git worktree add {quoted_path} {quoted_branch}"
        else:
            console.print(f"Creating new branch {branch_name} from {base}")
            cmd = f"git worktree add {quoted_path} -b {quoted_branch} {quoted_base}"

        self.logger.execute(cmd, "Create worktree")

        if not self.dry_run:
            console.print(f"[green]✓ Created worktree: {worktree_path}[/green]")
            console.print(f"[green]✓ Branch: {branch_name}[/green]")
            console.print("\nNext steps:")
            console.print(f"  cd {worktree_path}")
            console.print("  # Make your changes")
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

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None

        if current_branch == branch_name:
            console.print(f"Running from worktree for branch {branch_name}")
            git_dir = "."
        elif worktree_path.exists():
            console.print(f"Running from parent repo, targeting worktree at {worktree_path}")
            git_dir = str(worktree_path)
        else:
            console.print("[red]ERROR: Worktree not found[/red]")
            console.print(f"  Expected worktree: {worktree_path}")
            console.print(f"  Current branch: {current_branch}")
            console.print(f"  Run 'wtf wt-new {slug}' first")
            sys.exit(1)

        # B05 fix: quote paths in shell commands
        cmd = f"git -C {shlex.quote(git_dir)} push -u origin {shlex.quote(branch_name)}"
        self.logger.execute(cmd, "Push branch to origin")

        if not self.dry_run:
            console.print(f"[green]✓ Published branch {branch_name} to origin and set upstream[/green]")

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
        branch_name = f"feat/{slug}"

        if not self.fork_owner:
            console.print("[red]Could not determine fork owner[/red]")
            sys.exit(1)

        if not self.upstream_repo:
            console.print("[red]No upstream repo configured. Run: wtf upstream-add --repo owner/repo[/red]")
            sys.exit(1)

        if not shutil.which("gh"):
            console.print("[red]GitHub CLI required. Install from: https://cli.github.com/[/red]")
            sys.exit(1)

        console.print(f"[cyan]Creating PR for {branch_name}...[/cyan]")

        console.print("Checking for existing PR...")
        check_cmd = (
            f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
            f"--head {shlex.quote(f'{self.fork_owner}:{branch_name}')} "
            f"--json number,url,state"
        )
        result = self.logger.execute(check_cmd, "Check for existing PR", check=False)

        if not self.dry_run and result.returncode == 0 and result.stdout.strip() != "[]":
            pr_data = json.loads(result.stdout)[0]
            console.print(f"[green]✓ PR already exists (#{pr_data['number']}) - State: {pr_data['state']}[/green]")
            console.print(f"  URL: {pr_data['url']}")
            console.print(f"  View: gh pr view {pr_data['number']} --repo {self.upstream_repo}")
            return

        console.print("Checking if branch needs to be pushed...")

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
            console.print("Branch not on origin, pushing first...")
            self.logger.execute(f"git -C {quoted_dir} push -u origin {quoted_branch}", "Push branch")
        else:
            unpushed_check = self.logger.execute(
                f'git -C {quoted_dir} rev-list --count "origin/{branch_name}..{branch_name}"',
                "Check unpushed commits",
                check=False,
            )
            if not self.dry_run and unpushed_check.stdout and int(unpushed_check.stdout.strip() or 0) > 0:
                console.print("Unpushed commits found, pushing...")
                self.logger.execute(f"git -C {quoted_dir} push origin {quoted_branch}", "Push commits")

        if not title or title == f"feat: {slug}":
            result = self.logger.execute(
                f'git -C {quoted_dir} log -1 --pretty=format:"%s"', "Get last commit message", check=False
            )
            title = result.stdout.strip() if not self.dry_run and result.stdout else f"feat: {slug}"

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
        console.print(f"Creating {create_type}...")

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
                console.print(f"[green]✓ {create_type.capitalize()} created successfully[/green]")
                if result.stdout:
                    console.print(f"  URL: {result.stdout.strip()}")
            else:
                console.print("[red]ERROR: Failed to create PR[/red]")
                if result.stderr:
                    console.print(result.stderr)
                sys.exit(1)

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
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)

        console.print(f"[cyan]Updating {branch_name} with upstream/{base}...[/cyan]")

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None
        if current_branch == branch_name:
            git_dir = "."
        elif worktree_path.exists():
            git_dir = str(worktree_path)
        else:
            console.print(f"[red]ERROR: Worktree not found. Run 'wtf wt-new {slug}' first[/red]")
            sys.exit(1)

        quoted_dir = shlex.quote(git_dir)

        console.print("Fetching latest from upstream...")
        self.logger.execute("git fetch upstream", "Fetch upstream")

        console.print("\n=== Current Status ===")
        behind_cmd = f'git -C {quoted_dir} rev-list --count "HEAD..upstream/{base}"'
        ahead_cmd = f'git -C {quoted_dir} rev-list --count "upstream/{base}..HEAD"'

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
                log_cmd = f'git -C {quoted_dir} log --oneline "upstream/{base}..HEAD"'
                self.logger.execute(log_cmd, "Show commits to rebase")
            return

        status_cmd = f"git -C {quoted_dir} status --porcelain"
        status_result = self.logger.execute(status_cmd, "Check for changes", check=False)
        has_uncommitted = bool(status_result.stdout.strip()) if (not self.dry_run and status_result.stdout) else False

        stashed = False
        if has_uncommitted:
            if stash:
                console.print("Stashing uncommitted changes...")
                stash_msg = shlex.quote(f"wt-update auto-stash for {branch_name}")
                stash_cmd = f"git -C {quoted_dir} stash push -m {stash_msg}"
                self.logger.execute(stash_cmd, "Stash changes")
                stashed = True
            else:
                console.print("[red]ERROR: You have uncommitted changes. Either:[/red]")
                console.print("  1. Commit your changes first")
                console.print("  2. Run with --stash to auto-stash")
                console.print("  3. Manually stash: git stash")
                sys.exit(1)

        backup_branch = None
        if not no_backup and commits_ahead > 0:
            backup_branch = f"backup/{branch_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            console.print(f"Creating backup branch: {backup_branch}")
            backup_cmd = f"git -C {quoted_dir} branch {shlex.quote(backup_branch)}"
            self.logger.execute(backup_cmd, "Create backup", check=False)

        if merge:
            console.print(f"\nMerging upstream/{base} into {branch_name}...")
            update_cmd = f'git -C {quoted_dir} merge "upstream/{base}"'
            result = self.logger.execute(update_cmd, "Merge upstream", check=False)
        else:
            console.print(f"\nRebasing {branch_name} onto upstream/{base}...")
            update_cmd = f'git -C {quoted_dir} rebase "upstream/{base}"'
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

        console.print("Pushing to origin...")
        if merge:
            push_cmd = f"git -C {quoted_dir} push origin {shlex.quote(branch_name)}"
        else:
            push_cmd = f"git -C {quoted_dir} push --force-with-lease origin {shlex.quote(branch_name)}"

        result = self.logger.execute(push_cmd, "Push to origin", check=False)

        if not self.dry_run and result.returncode != 0:
            console.print("[red]ERROR: Push failed. Remote may have been updated.[/red]")
            console.print(f"If you're sure, use: git push --force origin {branch_name}")
            sys.exit(1)

        if stashed:
            console.print("Restoring stashed changes...")
            pop_cmd = f"git -C {quoted_dir} stash pop"
            self.logger.execute(pop_cmd, "Restore stash", check=False)

        console.print(f"[green]✓ Successfully updated {branch_name} with upstream/{base}[/green]")

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
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)

        console.print("[cyan]=== Worktree Clean Summary ===[/cyan]")
        console.print(f"Branch:       {branch_name}")
        console.print(f"Worktree:     {worktree_path}")
        console.print("")

        has_worktree = worktree_path.exists()
        has_local_branch = branch_name in self.repo.heads
        has_remote_branch = False
        has_uncommitted = False
        has_pr = False

        if has_worktree:
            console.print(f"✓ Worktree exists at {worktree_path}")

            quoted_path = shlex.quote(str(worktree_path))
            status_cmd = f"git -C {quoted_path} status --porcelain"
            result = self.logger.execute(status_cmd, "Check for changes", check=False)
            if not self.dry_run and result.stdout:
                has_uncommitted = True
                console.print("[yellow]⚠️  Has uncommitted changes:[/yellow]")
                for line in result.stdout.strip().split("\n")[:5]:
                    console.print(f"  {line}")
        else:
            console.print(f"✗ No worktree at {worktree_path}")

        if has_local_branch:
            console.print(f"✓ Local branch {branch_name} exists")

        check_remote = self.logger.execute(
            f"git ls-remote --exit-code --heads origin {shlex.quote(branch_name)}", "Check remote branch", check=False
        )
        if check_remote.returncode == 0:
            has_remote_branch = True
            console.print(f"✓ Remote branch origin/{branch_name} exists")

        if shutil.which("gh") and self.fork_owner and self.upstream_repo:
            pr_check = self.logger.execute(
                f"gh pr list --repo {shlex.quote(self.upstream_repo)} "
                f"--head {shlex.quote(f'{self.fork_owner}:{branch_name}')} "
                f"--json number,state",
                "Check for PR",
                check=False,
            )
            if not self.dry_run and pr_check.returncode == 0 and pr_check.stdout.strip() != "[]":
                pr_data = json.loads(pr_check.stdout)[0]
                has_pr = True
                console.print(f"[yellow]⚠️  Has PR #{pr_data['number']} ({pr_data['state']})[/yellow]")

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

        if has_uncommitted and not wt_force:
            console.print("[red]ERROR: Worktree has uncommitted changes. Use --wt-force to force removal.[/red]")
            sys.exit(1)

        if has_pr and not confirm:
            console.print("[yellow]WARNING: This branch has an open PR. Are you sure you want to delete it?[/yellow]")
            console.print("Use --confirm to proceed anyway.")
            sys.exit(1)

        current_dir = Path.cwd()
        if current_dir == worktree_path or worktree_path in current_dir.parents:
            console.print("[red]ERROR: Cannot remove worktree while inside it.[/red]")
            console.print("Please cd to parent repo or another directory first.")
            sys.exit(1)

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

        console.print("\n[cyan]=== Cleaning ===[/cyan]")

        if has_worktree:
            console.print("Removing worktree...")
            force_flag = "--force" if wt_force else ""
            rm_cmd = f"git worktree remove {force_flag} {shlex.quote(str(worktree_path))}"
            self.logger.execute(rm_cmd, "Remove worktree")

        if has_local_branch:
            console.print("Deleting local branch...")
            delete_flag = "-D" if force_delete else "-d"
            del_cmd = f"git branch {delete_flag} {shlex.quote(branch_name)}"
            self.logger.execute(del_cmd, "Delete branch", check=False)

        if has_remote_branch:
            console.print("Deleting remote branch...")
            push_cmd = f"git push origin --delete {shlex.quote(branch_name)}"
            self.logger.execute(push_cmd, "Delete remote branch", check=False)

        console.print("Pruning remote references...")
        self.logger.execute("git remote prune origin", "Prune origin", check=False)
        self.logger.execute("git worktree prune", "Prune worktrees", check=False)

        console.print(f"[green]✓ Cleaned worktree and branches for {branch_name}[/green]")

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
        List all worktrees with their status.

        Bash equivalents:
            git worktree list --porcelain
        """
        console.print("[cyan]=== Git Worktrees ===[/cyan]\n")

        result = self.logger.execute("git worktree list --porcelain", "List worktrees")

        if not self.dry_run and result.stdout:
            worktrees = self._parse_worktree_porcelain(result.stdout)

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

        Args:
            slug: Feature slug
            base: Base branch name (default: main)
        """
        slug = self.validator.validate_slug(slug)
        branch_name = f"feat/{slug}"
        worktree_path = self._get_worktree_path(slug)

        console.print(Panel.fit(f"[bold cyan]Worktree Status: {branch_name}[/bold cyan]", style="cyan"))

        if not worktree_path.exists():
            console.print(f"[red]✗ Worktree not found at: {worktree_path}[/red]")
            console.print(f"  Run: wtf wt-new {slug}")
            sys.exit(1)

        try:
            current_branch = self.repo.active_branch.name
        except TypeError:
            current_branch = None

        git_dir = "." if current_branch == branch_name else str(worktree_path)

        quoted_dir = shlex.quote(git_dir)

        head_cmd = f'git -C {quoted_dir} log -1 --pretty=format:"%h %s"'
        head_result = self.logger.execute(head_cmd, "Get HEAD commit", check=False)
        head_info = head_result.stdout.strip() if (not self.dry_run and head_result.stdout) else "(unknown)"

        console.print("\n[dim]Fetching latest from remotes...[/dim]")
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

        # === Display Status ===

        info_table = Table(show_header=False, box=None, padding=(0, 2))
        info_table.add_column("Property", style="cyan")
        info_table.add_column("Value")

        info_table.add_row("Branch:", branch_name)
        info_table.add_row("Path:", str(worktree_path))
        info_table.add_row("HEAD:", head_info)

        console.print("\n")
        console.print(info_table)

        console.print("\n[bold cyan]Sync Status:[/bold cyan]")
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

        console.print(status_table)

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

        if pr_info:
            console.print("\n[bold cyan]Pull Request:[/bold cyan]")

            state_colors = {"OPEN": "green", "CLOSED": "red", "MERGED": "blue"}
            state_color = state_colors.get(pr_info["state"], "white")

            pr_table = Table(show_header=False, box=None, padding=(0, 2))
            pr_table.add_column("Property", style="cyan")
            pr_table.add_column("Value")

            pr_table.add_row("Number:", f"#{pr_info['number']}")
            pr_table.add_row("State:", f"[{state_color}]{pr_info['state']}[/{state_color}]")
            pr_table.add_row("Title:", pr_info["title"])
            pr_table.add_row("URL:", pr_info["url"])

            console.print(pr_table)
        else:
            console.print("\n[dim]No pull request found[/dim]")

        if recent_commits:
            console.print("\n[bold cyan]Recent Commits:[/bold cyan]")
            for commit in recent_commits:
                console.print(f"  {commit}")

        console.print("\n[bold cyan]Suggested Actions:[/bold cyan]")
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
        """
        console.print("[green]✓ Inside Git repository[/green]")
        console.print(f"  Root: {self.root}")
        console.print(f"  Name: {self.repo_name}")

    def check_origin(self) -> None:
        """
        Verify 'origin' remote exists.

        Bash equivalent:
            git remote get-url origin
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
        """
        if "upstream" not in self.repo.remotes:
            upstream_display = self.upstream_repo or "(not configured)"
            console.print(f"[red]✗ Missing 'upstream' remote ({upstream_display})[/red]")
            console.print("  Add it with: wtf upstream-add --repo owner/repo")
            sys.exit(1)

        upstream_url = self.repo.remote("upstream").url
        console.print("[green]✓ Upstream remote exists[/green]")
        console.print(f"  URL: {upstream_url}")
        console.print(f"  Repo: {self.upstream_repo}")
