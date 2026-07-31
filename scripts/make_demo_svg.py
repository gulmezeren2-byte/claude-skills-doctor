"""Regenerate docs/demo.svg from the committed example home.

The image in the README is not a mock-up: it is the full check running against
`examples/demo-home`, through the same `report.render` the CLI calls. If the
output changes, re-run me so the README never shows something the tool no longer
prints.

The example home is deliberately sabotaged, the way andon's example workbook is:
alongside 56 ordinary skills it carries a name that does not match its folder, a
description with an unquoted colon (invalid YAML), one past the per-entry cap,
and enough total text to push the listing over budget. Every finding in the image
is the tool reacting to one of those.

The fixture exists for two reasons. It makes the picture **reproducible** —
anyone can run the command below and get the same numbers. And it keeps the
screenshot free of whatever happens to be installed on the author's machine: a
real `~/.claude` listing is a list of what that person works on, which is not
something to publish for a demo.

    uv run python scripts/make_demo_svg.py

The equivalent CLI invocation, which prints exactly what the image shows:

    skilldoctor --home examples/demo-home --project examples/demo-home
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from skilldoctor import report as _report
from skilldoctor import settings as _settings
from skilldoctor.checks import check_all
from skilldoctor.cli import _apply_settings, _limit
from skilldoctor.discover import discover_commands, discover_skills

ROOT = Path(__file__).parent.parent
HOME = ROOT / "examples" / "demo-home"
WIDTH = 120


def main() -> None:
    skills = discover_skills(home=HOME, project_root=HOME)
    commands = discover_commands(home=HOME, project_root=HOME)
    settings = _settings.load_settings(home=HOME, project_root=HOME)
    _apply_settings(skills, settings)
    limit = _limit(None, None, settings)
    report = check_all(skills, commands, limit)

    console = Console(record=True, width=WIDTH, force_terminal=True)
    _report.render(report, console)

    svg = console.export_svg(title="skilldoctor")
    # Drop the CDN font-face so the SVG is self-contained on GitHub, which blocks
    # external fetches inside an SVG and would otherwise render empty boxes.
    svg = re.sub(r"@font-face\s*\{[^}]*?\}", "", svg, flags=re.DOTALL)

    out = ROOT / "docs" / "demo.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(svg, encoding="utf-8")

    print(
        f"wrote {out} ({len(skills)} skills, "
        f"{report.budget_used:,}/{report.budget_limit:,} chars, "
        f"{report.errors} error(s), {report.warnings} warning(s))"
    )


if __name__ == "__main__":
    main()
