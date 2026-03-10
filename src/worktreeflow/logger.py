"""
Bash command logging and execution for worktreeflow.

Provides transparency by documenting all bash command equivalents.
"""

import json
import subprocess
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field

from rich.console import Console

console = Console()


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
            return subprocess.CompletedProcess(args=bash_cmd, returncode=0, stdout="", stderr="")

        if self.commands:
            self.commands[-1].executed = True

        result = subprocess.run(
            bash_cmd,
            shell=True,
            check=check,
            capture_output=capture_output,
            text=True
        )

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
