"""
CLI interface for worktreeflow.

All Click commands and the main entry point.
"""

import functools
import sys
from collections.abc import Callable
from typing import Any

import click
from rich.console import Console

from worktreeflow import __version__
from worktreeflow.errors import WorktreeFlowError
from worktreeflow.manager import GitWorkflowManager

console = Console()


# ========== Alias Support ==========

# Maps short alias -> canonical command name
_ALIASES = {
    "new": "wt-new",
    "pub": "wt-publish",
    "pr": "wt-pr",
    "up": "wt-update",
    "clean": "wt-clean",
    "ls": "wt-list",
    "st": "wt-status",
    "cd": "wt-cd",
    "open": "wt-open",
    "reopen": "wt-reopen",
}


class AliasGroup(click.Group):
    """Click group subclass that supports command aliases."""

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        # Try exact match first
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            return rv
        # Try alias lookup
        canonical = _ALIASES.get(cmd_name)
        if canonical is not None:
            return click.Group.get_command(self, ctx, canonical)
        return None

    def format_usage(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        super().format_usage(ctx, formatter)

    def format_help_text(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        super().format_help_text(ctx, formatter)
        # Append alias section
        alias_lines = []
        for alias, target in sorted(_ALIASES.items()):
            alias_lines.append(f"  {alias:<10} -> {target}")
        if alias_lines:
            formatter.write("\n")
            formatter.write("Aliases:\n")
            for line in alias_lines:
                formatter.write(f"{line}\n")


# ========== CLI Interface ==========


@click.group(cls=AliasGroup, invoke_without_command=True)
@click.option("--debug", "-d", is_flag=True, help="Enable debug output (shows bash commands)", envvar="WTF_DEBUG")
@click.option("--dry-run", "-n", is_flag=True, help="Preview commands without execution", envvar="WTF_DRY_RUN")
@click.option("--save-history", is_flag=True, help="Save command history to .wtf_history.json")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output", envvar="WTF_QUIET")
@click.option("--verbose", "-v", is_flag=True, help="Show extra detail beyond default output", envvar="WTF_VERBOSE")
@click.option("--json", "json_output", is_flag=True, help="Output machine-readable JSON")
@click.pass_context
def cli(ctx, debug, dry_run, save_history, quiet, verbose, json_output):
    """
    Git workflow manager - Python port of hl + hl.mk

    This tool merges the capabilities of the hl bash wrapper and hl.mk makefile
    into a single Python script using GitPython for Git operations.

    Every Git operation documents its bash equivalent for transparency.

    Common workflow:

        wtf sync-main              # Update fork's main

        wtf new issue-123          # Create worktree (alias for wt-new)

        # ... make changes ...

        wtf pub issue-123          # Push to fork (alias for wt-publish)

        wtf pr issue-123           # Create PR (alias for wt-pr)

        wtf up issue-123           # Rebase on upstream (alias for wt-update)

        wtf clean issue-123        # Clean up after merge (alias for wt-clean)
    """
    if quiet and verbose:
        raise click.UsageError("Cannot use --quiet and --verbose together")
    if json_output and verbose:
        raise click.UsageError("Cannot use --json and --verbose together")

    # Store json_output flag on context for commands that don't need the manager
    ctx.ensure_object(dict)
    ctx.obj = {"json_output": json_output}

    # Some commands (version, tutorial, quickstart, init) don't need the manager
    no_manager_commands = {"version", "tutorial", "quickstart", "init"}
    if ctx.invoked_subcommand in no_manager_commands:
        return

    try:
        manager = GitWorkflowManager(
            debug=debug,
            dry_run=dry_run,
            save_history=save_history,
            quiet=quiet,
            verbose=verbose,
            json_output=json_output,
        )
        ctx.obj = manager
    except WorktreeFlowError as e:
        console.print(f"[red]ERROR: {e}[/red]")
        sys.exit(1)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())

    if save_history and ctx.invoked_subcommand:
        import atexit

        atexit.register(lambda: manager.logger.save_history())


def _handle_error(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that catches WorktreeFlowError and exits cleanly."""

    @click.pass_obj
    @functools.wraps(func)
    def wrapper(manager: GitWorkflowManager, *args: Any, **kwargs: Any) -> None:
        try:
            func(manager, *args, **kwargs)
        except WorktreeFlowError as e:
            console.print(f"[red]ERROR: {e}[/red]")
            sys.exit(1)

    return wrapper


# ========== Version Command ==========


@cli.command()
def version() -> None:
    """Show worktreeflow version."""
    click.echo(f"worktreeflow {__version__}")


# ========== Repository Setup Commands ==========


@cli.command()
@_handle_error
def doctor(manager):
    """Print detected settings and sanity-check environment."""
    manager.doctor()


@cli.command("upstream-add")
@click.option("--repo", "repo_upstream", help="Override upstream repo (format: owner/repo)")
@click.option("--update", is_flag=True, help="Force update existing upstream")
@_handle_error
def upstream_add(manager, repo_upstream, update):
    """Add or update upstream remote (auto-detects SSH/HTTPS)."""
    manager.upstream_add(repo_upstream, update)


@cli.command("fork-setup")
@_handle_error
def fork_setup(manager):
    """Create fork if needed and set up remotes (requires gh CLI)."""
    manager.fork_setup()


@cli.command()
@_handle_error
def init(manager):
    """Interactive configuration wizard — creates .worktreeflow.toml."""
    manager.init_config()


# ========== Sync Commands ==========


@cli.command("sync-main")
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompts")
@_handle_error
def sync_main(manager, base, confirm):
    """FF-only: update fork's main from upstream/main."""
    manager.sync_main(base, confirm)


@cli.command("sync-main-force")
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@click.option("--confirm", is_flag=True, help="Confirm destructive operation")
@click.option("--force", is_flag=True, help="Force even with uncommitted changes")
@_handle_error
def sync_main_force(manager, base, confirm, force):
    """RECOVERY: reset fork main to upstream and force-push (creates backup)."""
    manager.sync_main_force(base, confirm, force)


@cli.command("zero-ffsync")
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@_handle_error
def zero_ffsync(manager, base):
    """FF-only push (no checkout): origin/main <- upstream/main."""
    manager.zero_ffsync(base)


# ========== Worktree Commands ==========


@cli.command("wt-new")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch to branch from", envvar="WTF_BASE_BRANCH")
@click.option("--no-sync", is_flag=True, help="Skip syncing main before creating worktree")
@click.option("--open", "open_editor", is_flag=True, help="Open worktree in editor after creation")
@_handle_error
def wt_new(manager, slug, base, no_sync, open_editor):
    """Create worktree + new feature branch from fork/main."""
    manager.wt_new(slug, base, no_sync=no_sync)
    if open_editor:
        manager.wt_open(slug)


@cli.command("wt-publish")
@click.argument("slug", required=False, default=None)
@_handle_error
def wt_publish(manager, slug):
    """Push worktree feature branch to origin and set upstream.

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_publish(slug)


@cli.command("wt-pr")
@click.argument("slug", required=False, default=None)
@click.option("--base", default="main", help="Base branch for PR (default: main)", envvar="WTF_BASE_BRANCH")
@click.option("--title", help="PR title (auto-generated if not provided)")
@click.option("--body", help="PR body (auto-generated if not provided)")
@click.option("--draft", is_flag=True, help="Create as draft PR")
@_handle_error
def wt_pr(manager, slug, base, title, body, draft):
    """Open PR from fork feature to upstream/main (requires gh CLI).

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_pr(slug, base, title, body, draft)


@cli.command("wt-update")
@click.argument("slug", required=False, default=None)
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@click.option("--stash", is_flag=True, help="Auto-stash uncommitted changes")
@click.option("--dry-run-preview", is_flag=True, help="Preview what would happen")
@click.option("--merge", is_flag=True, help="Use merge instead of rebase")
@click.option("--no-backup", is_flag=True, help="Skip backup branch creation")
@_handle_error
def wt_update(manager, slug, base, stash, dry_run_preview, merge, no_backup):
    """Rebase worktree feature on upstream/main and push.

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_update(slug, base, stash, dry_run_preview, merge, no_backup)


@cli.command("wt-clean")
@click.argument("slug", required=False, default=None)
@click.option("--force-delete", is_flag=True, help="Force delete branch even if not merged")
@click.option("--wt-force", is_flag=True, help="Force remove worktree with uncommitted changes")
@click.option("--dry-run-preview", is_flag=True, help="Preview what would be deleted")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompts")
@_handle_error
def wt_clean(manager, slug, force_delete, wt_force, dry_run_preview, confirm):
    """Remove worktree and prune branches.

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_clean(slug, force_delete, wt_force, dry_run_preview, confirm)


@cli.command("wt-list")
@_handle_error
def wt_list(manager):
    """List all worktrees with their status, PR info, and last activity."""
    manager.wt_list()


@cli.command("wt-status")
@click.argument("slug", required=False, default=None)
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@_handle_error
def wt_status(manager, slug, base):
    """Show comprehensive status for a worktree.

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_status(slug, base)


@cli.command("wt-cd")
@click.argument("slug", required=False, default=None)
@_handle_error
def wt_cd(manager, slug):
    """Print the absolute path to a worktree directory.

    Usage with shell:  cd $(wtf wt-cd my-feature)

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_cd(slug)


@cli.command("wt-open")
@click.argument("slug", required=False, default=None)
@click.option("--editor", help="Editor command to use (default: $EDITOR or auto-detect)")
@_handle_error
def wt_open(manager, slug, editor):
    """Open a worktree directory in your editor.

    Auto-detects editor from $EDITOR, or tries code/vim/nano.

    SLUG is auto-detected if you are inside a worktree.
    """
    slug = manager.resolve_slug(slug)
    manager.wt_open(slug, editor=editor)


@cli.command("wt-reopen")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch name", envvar="WTF_BASE_BRANCH")
@_handle_error
def wt_reopen(manager, slug, base):
    """Recreate a worktree from an existing remote branch.

    Useful when a worktree was cleaned up but the branch still exists
    on the remote, or when resuming work on another machine.
    """
    manager.wt_reopen(slug, base)


# ========== Check Commands ==========


@cli.command("check-repo")
@_handle_error
def check_repo(manager):
    """Verify we're inside a Git repository."""
    manager.check_repo()


@cli.command("check-origin")
@_handle_error
def check_origin(manager):
    """Verify 'origin' remote exists."""
    manager.check_origin()


@cli.command("check-upstream")
@_handle_error
def check_upstream(manager):
    """Verify 'upstream' remote exists."""
    manager.check_upstream()


# ========== Tutorial Commands ==========


@cli.command()
def tutorial() -> None:
    """Show detailed tutorial for all workflows."""
    tutorial_text = """
[bold cyan]Git Workflow Tutorial[/bold cyan]
=====================

[bold]0) First-time setup (fork & clone)[/bold]
If you do NOT have a fork locally yet:
  \u2022 Create your fork: [green]wtf fork-setup[/green]
    (Requires GitHub CLI and login: gh auth login)

If you ALREADY have the fork cloned:
  \u2022 Add upstream: [green]wtf upstream-add --repo owner/repo[/green]
  \u2022 Generate config: [green]wtf init[/green]
  \u2022 Check setup: [green]wtf doctor[/green]

[bold]1) Keep your fork's main synced[/bold]
  \u2022 Full sync: [green]wtf sync-main[/green]
  \u2022 Quick sync: [green]wtf zero-ffsync[/green]
  \u2022 Recovery: [green]wtf sync-main-force --confirm[/green]

[bold]2) Worktree-based feature branches[/bold]
  A. Create:  [green]wtf wt-new issue-199[/green]      (alias: [green]wtf new[/green])
  B. Go to:   [green]cd $(wtf wt-cd issue-199)[/green]  (alias: [green]wtf cd[/green])
  C. Open:    [green]wtf wt-open issue-199[/green]      (alias: [green]wtf open[/green])
  D. Publish: [green]wtf wt-publish issue-199[/green]   (alias: [green]wtf pub[/green])
  E. Open PR: [green]wtf wt-pr issue-199[/green]        (alias: [green]wtf pr[/green])
  F. Update:  [green]wtf wt-update issue-199[/green]    (alias: [green]wtf up[/green])
  G. Status:  [green]wtf wt-status issue-199[/green]    (alias: [green]wtf st[/green])
  H. Clean:   [green]wtf wt-clean issue-199[/green]     (alias: [green]wtf clean[/green])
  I. Reopen:  [green]wtf wt-reopen issue-199[/green]    (alias: [green]wtf reopen[/green])

[bold]3) Auto-detection[/bold]
  When inside a worktree, SLUG is auto-detected:
  \u2022 [green]cd $(wtf wt-cd issue-199)[/green]
  \u2022 [green]wtf wt-publish[/green]  (no SLUG needed!)
  \u2022 [green]wtf wt-pr[/green]
  \u2022 [green]wtf wt-update[/green]
  \u2022 [green]wtf wt-status[/green]

[bold]4) Options[/bold]
  \u2022 Skip sync: [green]wtf wt-new issue-199 --no-sync[/green]
  \u2022 Open in editor: [green]wtf wt-new issue-199 --open[/green]
  \u2022 Debug mode: [green]wtf --debug <command>[/green]
  \u2022 Dry run: [green]wtf --dry-run <command>[/green]
  \u2022 Quiet mode: [green]wtf --quiet <command>[/green]
  \u2022 Verbose: [green]wtf --verbose <command>[/green]
  \u2022 JSON output: [green]wtf --json wt-list[/green]
  \u2022 Save history: [green]wtf --save-history <command>[/green]

[bold]5) Environment variables[/bold]
  \u2022 WTF_BASE_BRANCH  Override base branch (default: main)
  \u2022 WTF_DEBUG        Enable debug mode
  \u2022 WTF_DRY_RUN      Enable dry-run mode
  \u2022 WTF_QUIET        Enable quiet mode
  \u2022 WTF_VERBOSE      Enable verbose mode

[bold]6) Shell completion[/bold]
  \u2022 Bash: [green]eval "$(_WTF_COMPLETE=bash_source wtf)"[/green]
  \u2022 Zsh:  [green]eval "$(_WTF_COMPLETE=zsh_source wtf)"[/green]
  \u2022 Fish: [green]_WTF_COMPLETE=fish_source wtf | source[/green]

  To install permanently, add the above to your shell profile.
"""
    console.print(tutorial_text)


@cli.command()
def quickstart() -> None:
    """Show quickstart guide."""
    quickstart_text = """
[bold cyan]Quickstart Guide[/bold cyan]
================

[bold]First time:[/bold]
  [green]wtf fork-setup[/green]         # Create fork and setup remotes
  [green]wtf init[/green]               # Generate .worktreeflow.toml config

[bold]Daily workflow:[/bold]
  [green]wtf sync-main[/green]          # Update fork's main
  [green]wtf new feat-x[/green]         # Create worktree (short alias)
  [green]cd $(wtf cd feat-x)[/green]    # Navigate to worktree
  # ... make changes ...
  [green]wtf pub[/green]                # Push to fork (auto-detects slug)
  [green]wtf pr[/green]                 # Create PR (auto-detects slug)
  [green]wtf up[/green]                 # Rebase on upstream
  [green]wtf clean feat-x[/green]       # Clean up after merge

[bold]Aliases:[/bold]
  new -> wt-new      pub -> wt-publish   pr -> wt-pr
  up  -> wt-update   clean -> wt-clean   ls -> wt-list
  st  -> wt-status   cd -> wt-cd         open -> wt-open

[bold]Options:[/bold]
  --debug     Show bash commands         (env: WTF_DEBUG)
  --dry-run   Preview without execution  (env: WTF_DRY_RUN)
  --quiet     Suppress non-error output  (env: WTF_QUIET)
  --verbose   Show extra detail          (env: WTF_VERBOSE)
  --json      Machine-readable output
  --no-sync   Skip sync in wt-new
  --open      Open editor after wt-new
  --help      Show help for any command

[bold]Shell completion:[/bold]
  eval "$(_WTF_COMPLETE=bash_source wtf)"
"""
    console.print(quickstart_text)
