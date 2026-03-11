"""
CLI interface for worktreeflow.

All Click commands and the main entry point.
"""

import click
from rich.console import Console

from worktreeflow.manager import GitWorkflowManager

console = Console()


# ========== CLI Interface ==========


@click.group(invoke_without_command=True)
@click.option("--debug", "-d", is_flag=True, help="Enable debug output (shows bash commands)")
@click.option("--dry-run", "-n", is_flag=True, help="Preview commands without execution")
@click.option("--save-history", is_flag=True, help="Save command history to .wtf_history.json")
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
    ctx.obj = GitWorkflowManager(debug=debug, dry_run=dry_run, save_history=save_history)

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())

    if save_history and ctx.invoked_subcommand:
        import atexit

        atexit.register(lambda: ctx.obj.logger.save_history())


# ========== Repository Setup Commands ==========


@cli.command()
@click.pass_obj
def doctor(manager):
    """Print detected settings and sanity-check environment."""
    manager.doctor()


@cli.command("upstream-add")
@click.option("--repo", "repo_upstream", help="Override upstream repo (format: owner/repo)")
@click.option("--update", is_flag=True, help="Force update existing upstream")
@click.pass_obj
def upstream_add(manager, repo_upstream, update):
    """Add or update upstream remote (auto-detects SSH/HTTPS)."""
    manager.upstream_add(repo_upstream, update)


@cli.command("fork-setup")
@click.pass_obj
def fork_setup(manager):
    """Create fork if needed and set up remotes (requires gh CLI)."""
    manager.fork_setup()


# ========== Sync Commands ==========


@cli.command("sync-main")
@click.option("--base", default="main", help="Base branch name")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompts")
@click.pass_obj
def sync_main(manager, base, confirm):
    """FF-only: update fork's main from upstream/main."""
    manager.sync_main(base, confirm)


@cli.command("sync-main-force")
@click.option("--base", default="main", help="Base branch name")
@click.option("--confirm", is_flag=True, help="Confirm destructive operation")
@click.option("--force", is_flag=True, help="Force even with uncommitted changes")
@click.pass_obj
def sync_main_force(manager, base, confirm, force):
    """RECOVERY: reset fork main to upstream and force-push (creates backup)."""
    manager.sync_main_force(base, confirm, force)


@cli.command("zero-ffsync")
@click.option("--base", default="main", help="Base branch name")
@click.pass_obj
def zero_ffsync(manager, base):
    """FF-only push (no checkout): origin/main <- upstream/main."""
    manager.zero_ffsync(base)


# ========== Worktree Commands ==========


@cli.command("wt-new")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch to branch from")
@click.option("--no-sync", is_flag=True, help="Skip syncing main before creating worktree")
@click.pass_obj
def wt_new(manager, slug, base, no_sync):
    """Create worktree + new feature branch from fork/main."""
    manager.wt_new(slug, base, no_sync=no_sync)


@cli.command("wt-publish")
@click.argument("slug")
@click.pass_obj
def wt_publish(manager, slug):
    """Push worktree feature branch to origin and set upstream."""
    manager.wt_publish(slug)


@cli.command("wt-pr")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch for PR (default: main)")
@click.option("--title", help="PR title (auto-generated if not provided)")
@click.option("--body", help="PR body (auto-generated if not provided)")
@click.option("--draft", is_flag=True, help="Create as draft PR")
@click.pass_obj
def wt_pr(manager, slug, base, title, body, draft):
    """Open PR from fork feature to upstream/main (requires gh CLI)."""
    manager.wt_pr(slug, base, title, body, draft)


@cli.command("wt-update")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch name")
@click.option("--stash", is_flag=True, help="Auto-stash uncommitted changes")
@click.option("--dry-run-preview", is_flag=True, help="Preview what would happen")
@click.option("--merge", is_flag=True, help="Use merge instead of rebase")
@click.option("--no-backup", is_flag=True, help="Skip backup branch creation")
@click.pass_obj
def wt_update(manager, slug, base, stash, dry_run_preview, merge, no_backup):
    """Rebase worktree feature on upstream/main and push."""
    manager.wt_update(slug, base, stash, dry_run_preview, merge, no_backup)


@cli.command("wt-clean")
@click.argument("slug")
@click.option("--force-delete", is_flag=True, help="Force delete branch even if not merged")
@click.option("--wt-force", is_flag=True, help="Force remove worktree with uncommitted changes")
@click.option("--dry-run-preview", is_flag=True, help="Preview what would be deleted")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompts")
@click.pass_obj
def wt_clean(manager, slug, force_delete, wt_force, dry_run_preview, confirm):
    """Remove worktree and prune branches."""
    manager.wt_clean(slug, force_delete, wt_force, dry_run_preview, confirm)


@cli.command("wt-list")
@click.pass_obj
def wt_list(manager):
    """List all worktrees with their status."""
    manager.wt_list()


@cli.command("wt-status")
@click.argument("slug")
@click.option("--base", default="main", help="Base branch name")
@click.pass_obj
def wt_status(manager, slug, base):
    """Show comprehensive status for a worktree."""
    manager.wt_status(slug, base)


# ========== Check Commands ==========


@cli.command("check-repo")
@click.pass_obj
def check_repo(manager):
    """Verify we're inside a Git repository."""
    manager.check_repo()


@cli.command("check-origin")
@click.pass_obj
def check_origin(manager):
    """Verify 'origin' remote exists."""
    manager.check_origin()


@cli.command("check-upstream")
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
  • Add upstream: [green]wtf upstream-add --repo owner/repo[/green]
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

[bold]3) Options[/bold]
  • Skip sync: [green]wtf wt-new issue-199 --no-sync[/green]
  • Debug mode: [green]wtf --debug <command>[/green]
  • Dry run: [green]wtf --dry-run <command>[/green]
  • Save history: [green]wtf --save-history <command>[/green]

[bold]4) Shell completion[/bold]
  • Bash: [green]eval "$(_WTF_COMPLETE=bash_source wtf)"[/green]
  • Zsh:  [green]eval "$(_WTF_COMPLETE=zsh_source wtf)"[/green]
  • Fish: [green]_WTF_COMPLETE=fish_source wtf | source[/green]

  To install permanently, add the above to your shell profile.
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
  --debug     Show bash commands
  --dry-run   Preview without execution
  --no-sync   Skip sync in wt-new
  --help      Show help for any command

[bold]Shell completion:[/bold]
  eval "$(_WTF_COMPLETE=bash_source wtf)"
"""
    console.print(quickstart_text)
