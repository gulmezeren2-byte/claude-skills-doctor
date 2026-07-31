"""Data model for skilldoctor.

A `Skill` is one parsed SKILL.md (frontmatter + body) plus where it came from.
A `SlashCommand` is a command markdown file — it shares the same discovery-token
budget as skills, so it counts toward the budget even though it is linted less.
A `Finding` is one thing worth surfacing about a skill; a `Report` collects them
with the coverage that stands behind them.

The discipline is the one carried from andon/ihalent/acikpoz: never invent, always
surface, and report the denominator next to every number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from skilldoctor import budget as _budget

# Severity levels, ordered worst-first for sorting.
ERROR = "error"
WARNING = "warning"
INFO = "info"
_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}

# Where a skill/command was discovered.
SOURCE_USER = "user"  # ~/.claude/skills
SOURCE_PROJECT = "project"  # <cwd>/.claude/skills
SOURCE_PLUGIN = "plugin"  # ~/.claude/plugins/.../skills
SOURCE_EXPLICIT = "explicit"  # a --skills path: a skills/ dir you are authoring


@dataclass
class Skill:
    """One SKILL.md. `folder_name` is the on-disk parent folder, which the spec
    requires to equal the frontmatter `name`; keeping both lets us check it."""

    folder_name: str
    path: Path
    source: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    yaml_error: str | None = None  # set when frontmatter YAML failed to parse
    # What `skillOverrides` in settings says about this skill, and the per-entry
    # truncation point in force. Both are set by the caller after reading settings;
    # the defaults are what Claude Code does when nothing is configured.
    listing_state: str = "on"
    listing_cap: int | None = None

    @property
    def name(self) -> str:
        """Frontmatter name, falling back to the folder name when absent — so a
        skill with no `name` is still reportable by a stable identifier."""
        n = self.frontmatter.get("name")
        return n if isinstance(n, str) and n.strip() else self.folder_name

    @property
    def description(self) -> str:
        d = self.frontmatter.get("description")
        return d if isinstance(d, str) else ""

    @property
    def when_to_use(self) -> str:
        """Appended to `description` in the listing, and counted against the same
        per-entry cap — so for every budget purpose the two are one string."""
        w = self.frontmatter.get("when_to_use")
        return w if isinstance(w, str) else ""

    @property
    def listing_text(self) -> str:
        """What the listing actually carries for this skill, before truncation."""
        return f"{self.description}{self.when_to_use}"

    @property
    def cap(self) -> int:
        """The per-entry truncation point in force — `skillListingMaxDescChars` when
        it is configured, otherwise Claude Code's default."""
        return self.listing_cap or _budget.PER_ENTRY_CAP

    @property
    def listed_with_description(self) -> bool:
        """Whether Claude sees this skill's description at all. `off` and
        `user-invocable-only` hide it entirely; `name-only` lists just the name."""
        return self.listing_state == "on"

    @property
    def discovery_cost(self) -> int:
        """Characters this skill contributes to the shared listing budget.

        Three things make this less than the raw text, and getting any of them wrong
        overstates the total and points people at the wrong skill to trim:

        * `skillOverrides` — a skill set to `off` or `user-invocable-only` is not
          listed to Claude and costs nothing; `name-only` costs just its name.
        * The per-entry cap — a 4,000-character description costs the cap, because
          the cap is all that gets listed.
        """
        if self.listing_state in ("off", "user-invocable-only"):
            return 0
        if self.listing_state == "name-only":
            return len(self.name)
        return len(self.name) + min(len(self.listing_text), self.cap)


@dataclass
class SlashCommand:
    """A slash-command markdown file. Counted for the shared budget only."""

    name: str
    path: Path
    source: str
    description: str = ""

    @property
    def discovery_cost(self) -> int:
        return len(self.name) + min(len(self.description), _budget.PER_ENTRY_CAP)


@dataclass
class Finding:
    """One surfaced issue. `check` is a stable kebab-case id; `target` names the
    skill (or "budget" for the system-wide check)."""

    check: str
    severity: str
    target: str
    message: str
    path: Path | None = None
    suggestion: str | None = None  # a concrete fix, shown with --fix

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "target": self.target,
            "message": self.message,
            "path": str(self.path) if self.path else None,
            "suggestion": self.suggestion,
        }


@dataclass
class Report:
    """Findings plus the coverage: how many skills/commands were scanned and what
    the budget looks like. `ok` is false only when there is at least one error."""

    findings: list[Finding] = field(default_factory=list)
    skills_scanned: int = 0
    commands_scanned: int = 0
    budget_used: int = 0
    budget_limit: int = 0
    budget_source: str = ""
    budget_exact: bool = True

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.severity == WARNING)

    @property
    def infos(self) -> int:
        return sum(1 for f in self.findings if f.severity == INFO)

    @property
    def ok(self) -> bool:
        return self.errors == 0

    @property
    def over_budget(self) -> bool:
        return self.budget_used > self.budget_limit

    def sorted_findings(self) -> list[Finding]:
        """Errors first, then by check, then by target — stable and glanceable."""
        return sorted(
            self.findings,
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.check, f.target),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": {
                "skills": self.skills_scanned,
                "commands": self.commands_scanned,
                "errors": self.errors,
                "warnings": self.warnings,
                "infos": self.infos,
            },
            "budget": {
                "used": self.budget_used,
                "limit": self.budget_limit,
                "over": self.over_budget,
                # where the limit came from, and whether it is measured or derived —
                # a consumer of this JSON deserves to know which it is looking at
                "source": self.budget_source,
                "exact": self.budget_exact,
                "per_entry_cap": _budget.PER_ENTRY_CAP,
            },
            "findings": [f.to_dict() for f in self.sorted_findings()],
        }
