"""Render a Report for humans.

The budget bar leads, because "how close am I to the silent cliff?" is the
question skilldoctor exists to answer at a glance. Findings follow, worst-first.
JSON is produced from Report.to_dict() in the CLI; this module is the human view.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from skilldoctor.budget import Budget
from skilldoctor.model import ERROR, INFO, WARNING, Report, Skill, SlashCommand

_SEVERITY_STYLE = {ERROR: "bold red", WARNING: "yellow", INFO: "dim cyan"}
_SEVERITY_LABEL = {ERROR: "error", WARNING: "warn", INFO: "info"}
_BAR_WIDTH = 32

# Glyphs used in the report. On Windows, a piped stdout gets the legacy code page
# (cp1252 and friends) rather than UTF-8, and printing a block character there raises
# UnicodeEncodeError — so `skilldoctor | some-parser` would crash outright. Pick the
# drawing characters the actual stream can encode.
_FANCY = {"full": "█", "empty": "░", "warn": "⚠", "arrow": "→", "sep": "·", "dots": "…"}
_PLAIN = {"full": "#", "empty": ".", "warn": "!", "arrow": "->", "sep": "|", "dots": "..."}


def glyphs() -> dict[str, str]:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "".join(_FANCY.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _PLAIN
    return _FANCY


def _budget_bar(used: int, limit: int) -> Text:
    ratio = used / limit if limit else 0.0
    filled = min(_BAR_WIDTH, round(ratio * _BAR_WIDTH))
    if ratio > 1.0:
        color = "red"
    elif ratio >= 0.8:
        color = "yellow"
    else:
        color = "green"
    g = glyphs()
    bar = Text()
    bar.append(g["full"] * filled, style=color)
    bar.append(g["empty"] * (_BAR_WIDTH - filled), style="dim")
    bar.append(f"  {used:,} / {limit:,} chars ({int(ratio * 100)}%)", style=color)
    return bar


def render(report: Report, console: Console | None = None, show_fixes: bool = False) -> None:
    console = console or Console()

    console.print(Text("Skill listing budget", style="bold"))
    console.print(_budget_bar(report.budget_used, report.budget_limit))
    if report.budget_source:
        # an estimate quoted like a measurement is how a reader trusts the wrong digit
        suffix = "" if report.budget_exact else " (estimated)"
        console.print(Text(f"  budget from {report.budget_source}{suffix}", style="dim"))
    if report.over_budget:
        console.print(
            Text(
                f"  {glyphs()['warn']} over budget - names still list, but Claude Code "
                "drops descriptions to fit, least-used first",
                style="red",
            )
        )
    console.print()

    findings = report.sorted_findings()
    if findings:
        table = Table(show_header=True, header_style="bold", expand=False, pad_edge=False)
        table.add_column("severity", no_wrap=True)
        table.add_column("check", no_wrap=True, style="cyan")
        table.add_column("target", no_wrap=True, overflow="ellipsis", max_width=26)
        table.add_column("detail", overflow="fold", max_width=64)
        for f in findings:
            table.add_row(
                Text(_SEVERITY_LABEL.get(f.severity, f.severity),
                     style=_SEVERITY_STYLE.get(f.severity, "")),
                f.check,
                f.target,
                f.message,
            )
        console.print(table)
        console.print()

    if show_fixes:
        _print_fixes(report, console)

    _print_summary(report, console)


def _print_fixes(report: Report, console: Console) -> None:
    fixable = [f for f in report.sorted_findings() if f.suggestion]
    if not fixable:
        return
    arrow = glyphs()["arrow"]
    console.print(Text("Suggested fixes", style="bold"))
    for f in fixable:
        console.print(f"  [cyan]{f.target}[/cyan]  {f.check}")
        console.print(f"    {arrow} {f.suggestion}")
    console.print()


def _print_summary(report: Report, console: Console) -> None:
    parts = [
        f"{report.skills_scanned} skill(s)",
        f"{report.commands_scanned} command(s)",
    ]
    if report.errors:
        parts.append(f"[bold red]{report.errors} error(s)[/bold red]")
    if report.warnings:
        parts.append(f"[yellow]{report.warnings} warning(s)[/yellow]")
    if report.ok and not report.warnings:
        parts.append("[green]all clear[/green]")
    console.print(f" {glyphs()['sep']} ".join(parts))


def render_budget(
    skills: list[Skill],
    commands: list[SlashCommand],
    used: int,
    limit: Budget,
    top: int,
    console: Console,
) -> None:
    """The `budget` view: the bar, where the number came from, and who is eating it.

    Lives here rather than in the CLI so the demo image in the README is produced
    by the same code path the CLI prints — a screenshot that can drift from the
    tool is worse than no screenshot.
    """
    console.print("[bold]Skill listing budget[/bold]")
    console.print(_budget_bar(used, limit.chars))
    # say where the number came from: an estimate quoted like a measurement is how
    # a reader ends up trusting the wrong digit
    console.print(f"[dim]budget from {limit.source}[/dim]")
    if not limit.exact:
        console.print(
            "[dim]estimated — pass --context-window for your model, or --budget to "
            "pin it exactly.[/dim]"
        )
    console.print()

    # carry the listing state so a 0-char row reads as "you hid this", not as a bug
    items = [(s.name, "skill", s.discovery_cost, s.listing_state) for s in skills]
    items += [(c.name, "command", c.discovery_cost, "on") for c in commands]
    items.sort(key=lambda x: x[2], reverse=True)

    table = Table(show_header=True, header_style="bold")
    table.add_column("chars", justify="right")
    table.add_column("kind", style="dim")
    table.add_column("name", style="cyan")
    table.add_column("listed", style="dim")
    for name, kind, cost, state in items[: max(1, top)]:
        table.add_row(str(cost), kind, name, "" if state == "on" else state)
    console.print(table)
    if len(items) > top:
        console.print(f"[dim]{glyphs()['dots']} and {len(items) - top} more[/dim]")
