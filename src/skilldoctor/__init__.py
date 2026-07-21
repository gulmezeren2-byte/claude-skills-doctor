"""skilldoctor — a doctor for your Claude agent skills.

Finds the skills Claude silently can't see (over the discovery-char budget),
plus the frontmatter, naming, routing, and hygiene problems that keep a skill
from loading or triggering — deterministically, across every installed skill,
with no model calls.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from skilldoctor.budget import budget_limit, total_discovery_cost
from skilldoctor.checks import check_all
from skilldoctor.discover import discover_commands, discover_skills
from skilldoctor.model import Finding, Report, Skill, SlashCommand
from skilldoctor.parse import load_skill, parse_frontmatter, split_frontmatter

try:
    # distribution name on PyPI; the import package is `skilldoctor`
    __version__ = version("claude-skills-doctor")
except PackageNotFoundError:  # pragma: no cover - only during local dev before install
    __version__ = "0.0.0"

__all__ = [
    "Skill",
    "SlashCommand",
    "Finding",
    "Report",
    "load_skill",
    "split_frontmatter",
    "parse_frontmatter",
    "discover_skills",
    "discover_commands",
    "check_all",
    "budget_limit",
    "total_discovery_cost",
    "__version__",
]
