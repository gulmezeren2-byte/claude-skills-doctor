"""skilldoctor command line.

`skilldoctor` runs the full health check and exits non-zero on any error, so it drops
straight into CI. `skilldoctor budget` is the focused, shareable view: the bar plus the
biggest contributors, so you can see exactly what to trim.
"""

from __future__ import annotations

import contextlib
import json
import sys
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


def _use_utf8_output() -> None:
    """Make stdout/stderr able to carry non-ASCII.

    Findings quote whatever is on disk — a skill named `ölçü`, an em dash in a
    message — and on Windows a *piped* stdout gets the legacy code page, where that
    raises UnicodeEncodeError and takes the whole run down. `skilldoctor | jq` must
    not crash, so ask for UTF-8 and never fail if the stream won't take it."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


def _limit(override: int | None, context_tokens: int | None = None) -> _budget.Budget:
    return _budget.budget_limit(override=override, context_tokens=context_tokens)


_CONTEXT_HELP = (
    "Your model's context window in tokens. The listing budget is 1% of it, so "
    f"1M and {_budget.DEFAULT_CONTEXT_TOKENS:,} give very different answers "
    f"(default: {_budget.DEFAULT_CONTEXT_TOKENS:,})."
)
_BUDGET_HELP = (
    "Pin the listing budget to a fixed character count, skipping the estimate."
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: Path | None = typer.Option(
        None, "--project", "-p", help="Project root to scan for .claude/skills (default: cwd)."
    ),
    home: Path | None = typer.Option(
        None, "--home", help="Override the home dir (~/.claude). Mainly for testing."
    ),
    skills: list[Path] = typer.Option(
        [], "--skills", help="Also check this skills/ directory (repeatable). For "
        "skill and plugin authors: lint the skills you ship, in CI.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit the report as JSON."),
    budget_override: int | None = typer.Option(None, "--budget", help=_BUDGET_HELP),
    context_window: int | None = typer.Option(
        None, "--context-window", help=_CONTEXT_HELP
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
    _use_utf8_output()
    if show_version:
        typer.echo(f"skilldoctor {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return

    project = project or Path.cwd()
    try:
        found = discover_skills(home=home, project_root=project, extra_dirs=skills)
        commands = discover_commands(home=home, project_root=project)
        report = check_all(found, commands, _limit(budget_override, context_window))
    except Exception as exc:  # noqa: BLE001 - last resort: never dump a traceback
        # A consumer piping --json into a parser must always get JSON back, even
        # when something on disk defeats us.
        if json_out:
            typer.echo(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        else:
            Console(stderr=True).print(f"[red]skilldoctor failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_out:
        typer.echo(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        _report.render(report, show_fixes=fix)
        if not found and not commands:
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
    skills_dirs: list[Path] = typer.Option(
        [], "--skills", help="Also count this skills/ directory (repeatable)."
    ),
    top: int = typer.Option(15, "--top", help="How many biggest contributors to list."),
    budget_override: int | None = typer.Option(None, "--budget", help=_BUDGET_HELP),
    context_window: int | None = typer.Option(None, "--context-window", help=_CONTEXT_HELP),
) -> None:
    """Show the listing budget and the biggest contributors to it."""
    _use_utf8_output()
    console = Console()
    project = project or Path.cwd()
    skills = discover_skills(home=home, project_root=project, extra_dirs=skills_dirs)
    commands = discover_commands(home=home, project_root=project)
    limit = _limit(budget_override, context_window)
    used = _budget.total_discovery_cost(skills, commands)

    console.print("[bold]Skill listing budget[/bold]")
    console.print(_report._budget_bar(used, limit.chars))
    # say where the number came from: an estimate quoted like a measurement is how
    # a reader ends up trusting the wrong digit
    console.print(f"[dim]budget from {limit.source}[/dim]")
    if not limit.exact:
        console.print(
            "[dim]estimated — pass --context-window for your model, or --budget to "
            "pin it exactly.[/dim]"
        )
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
        console.print(f"[dim]{_report.glyphs()['dots']} and {len(items) - top} more[/dim]")

    raise typer.Exit(1 if used > limit.chars else 0)


if __name__ == "__main__":
    app()
