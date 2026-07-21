"""Render a Report for humans.

The budget bar leads, because "how close am I to the silent cliff?" is the
question skilldoctor exists to answer at a glance. Findings follow, worst-first.
JSON is produced from Report.to_dict() in the CLI; this module is the human view.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from skilldoctor.model import ERROR, INFO, WARNING, Report

_SEVERITY_STYLE = {ERROR: "bold red", WARNING: "yellow", INFO: "dim cyan"}
_SEVERITY_LABEL = {ERROR: "error", WARNING: "warn", INFO: "info"}
_BAR_WIDTH = 32


def _budget_bar(used: int, limit: int) -> Text:
    ratio = used / limit if limit else 0.0
    filled = min(_BAR_WIDTH, round(ratio * _BAR_WIDTH))
    if ratio > 1.0:
        color = "red"
    elif ratio >= 0.8:
        color = "yellow"
    else:
        color = "green"
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (_BAR_WIDTH - filled), style="dim")
    bar.append(f"  {used:,} / {limit:,} chars ({int(ratio * 100)}%)", style=color)
    return bar


def render(report: Report, console: Console | None = None) -> None:
    console = console or Console()

    console.print(Text("Discovery budget", style="bold"))
    console.print(_budget_bar(report.budget_used, report.budget_limit))
    if report.over_budget:
        console.print(
            Text(
                "  ⚠ over budget — Claude Code silently drops skills past this line",
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

    _print_summary(report, console)


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
    console.print(" · ".join(parts))
