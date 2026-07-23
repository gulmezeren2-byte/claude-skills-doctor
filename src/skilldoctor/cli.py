"""skilldoctor command line.

`skilldoctor` runs the full health check and exits non-zero on any error, so it drops
straight into CI. `skilldoctor budget` is the focused, shareable view: the bar plus the
biggest contributors, so you can see exactly what to trim.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from skilldoctor import __version__
from skilldoctor import budget as _budget
from skilldoctor import report as _report
from skilldoctor.checks import check_all
from skilldoctor.discover import discover_commands, discover_skills

app = typer.Typer(
    add_completion=False,
    help="A doctor for your Claude agent skills — find the ones Claude silently can't see.",
    no_args_is_help=False,
)


def _limit(override: int | None) -> int:
    if override is not None and override > 0:
        return override
    return _budget.budget_limit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: Path | None = typer.Option(
        None, "--project", "-p", help="Project root to scan for .claude/skills (default: cwd)."
    ),
    home: Path | None = typer.Option(
        None, "--home", help="Override the home dir (~/.claude). Mainly for testing."
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit the report as JSON."),
    budget_override: int | None = typer.Option(
        None, "--budget", help="Override the discovery-char budget (default 15000 / env)."
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero on warnings too, not just errors."
    ),
    fix: bool = typer.Option(
        False, "--fix", help="Show concrete suggested fixes for each finding."
    ),
    show_version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    """Run the full check (the default when no subcommand is given)."""
    if show_version:
        typer.echo(f"skilldoctor {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return

    project = project or Path.cwd()
    skills = discover_skills(home=home, project_root=project)
    commands = discover_commands(home=home, project_root=project)
    report = check_all(skills, commands, _limit(budget_override))

    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _report.render(report, show_fixes=fix)
        if not skills and not commands:
            Console().print(
                "[dim]No skills or commands found. Point --project at a repo with "
                ".claude/skills, or check your ~/.claude.[/dim]"
            )

    fail = not report.ok or (strict and report.warnings > 0)
    raise typer.Exit(1 if fail else 0)


@app.command()
def budget(
    project: Path | None = typer.Option(None, "--project", "-p"),
    home: Path | None = typer.Option(None, "--home"),
    top: int = typer.Option(15, "--top", help="How many biggest contributors to list."),
    budget_override: int | None = typer.Option(None, "--budget"),
) -> None:
    """Show the discovery budget and the biggest contributors to it."""
    console = Console()
    project = project or Path.cwd()
    skills = discover_skills(home=home, project_root=project)
    commands = discover_commands(home=home, project_root=project)
    limit = _limit(budget_override)
    used = _budget.total_discovery_cost(skills, commands)

    console.print("[bold]Discovery budget[/bold]")
    console.print(_report._budget_bar(used, limit))
    console.print()

    items = [(s.name, "skill", s.discovery_cost) for s in skills]
    items += [(c.name, "command", c.discovery_cost) for c in commands]
    items.sort(key=lambda x: x[2], reverse=True)

    table = Table(show_header=True, header_style="bold")
    table.add_column("chars", justify="right")
    table.add_column("kind", style="dim")
    table.add_column("name", style="cyan")
    for name, kind, cost in items[: max(1, top)]:
        table.add_row(str(cost), kind, name)
    console.print(table)
    if len(items) > top:
        console.print(f"[dim]… and {len(items) - top} more[/dim]")

    raise typer.Exit(1 if used > limit else 0)


if __name__ == "__main__":
    app()
