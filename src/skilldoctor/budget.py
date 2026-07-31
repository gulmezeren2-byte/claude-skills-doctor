"""The skill-listing budget — skilldoctor's headline, and the number it must be
most careful about.

Claude Code loads a listing of skill names and descriptions into context so Claude
knows what is available. Two separate limits squeeze it, and they fail differently:

* **Per entry** — the combined `description` + `when_to_use` text is truncated at
  **1,536 characters**, "regardless of budget". This one is exact, model-independent
  and documented, so it can be asserted without qualification.
* **Across the listing** — the total scales at **1% of the model's context window**,
  raised with the `skillListingBudgetFraction` setting or pinned to a fixed character
  count with the `SLASH_COMMAND_TOOL_CHAR_BUDGET` environment variable.

What overflow does is worth stating precisely, because a tool that describes the
failure wrongly teaches the wrong fix: *the listing always contains every skill
name.* What gets dropped is the **description**, starting with the skills you invoke
least. So nothing disappears from the menu — but the text Claude routes on does, and
a skill Claude cannot match is a skill Claude will not choose.

The honesty problem this module has to solve: the per-entry cap is in characters, but
the listing budget is a fraction of a context window measured in tokens. Claude Code
converts internally and does not publish the ratio. Rather than pick one silently,
the derived limit carries `exact=False` and the assumption travels with it to the
report, so a reader can always see whether they are looking at a measured limit or an
estimated one.

Source: <https://code.claude.com/docs/en/skills>
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# Exact, documented, and independent of the model: the combined `description` and
# `when_to_use` of one entry is truncated at this many characters in the listing.
# Configurable in Claude Code with `skillListingMaxDescChars`.
PER_ENTRY_CAP = 1536

# The listing budget defaults to 1% of the model's context window; raised with the
# `skillListingBudgetFraction` setting.
DEFAULT_BUDGET_FRACTION = 0.01
# The context window we assume when nobody says otherwise. Stated rather than hidden,
# and overridable, because 1% of 200k and 1% of 1M are very different budgets.
DEFAULT_CONTEXT_TOKENS = 200_000
# Turning a token budget into the character budget we measure against. English prose
# runs about four characters to the token; this is the one estimate in the chain, and
# it is why a derived limit is never reported as exact.
CHARS_PER_TOKEN = 4

BUDGET_ENV_VAR = "SLASH_COMMAND_TOOL_CHAR_BUDGET"
# Warn when this fraction of the budget is used even if not yet over — losing a
# description is quiet, so the useful moment to act is before you cross the line.
WARN_RATIO = 0.8


class _HasCost(Protocol):
    @property
    def discovery_cost(self) -> int: ...


@dataclass(frozen=True)
class Budget:
    """A character limit and, just as importantly, where it came from.

    `exact` is the difference between "Claude Code will use this number" and "this is
    our arithmetic on your context window". Both are useful; conflating them is how a
    measurement tool starts lying.
    """

    chars: int
    source: str
    exact: bool

    def __int__(self) -> int:  # lets callers keep treating it as a limit
        return self.chars


def budget_limit(
    env: dict[str, str] | None = None,
    *,
    override: int | None = None,
    fraction: float | None = None,
    context_tokens: int | None = None,
) -> Budget:
    """The listing budget, in characters, in precedence order.

    `--budget` wins because the user said so. Then `SLASH_COMMAND_TOOL_CHAR_BUDGET`,
    which Claude Code reads as a fixed character count — the only environment-derived
    number here that is exact. Otherwise it is derived from the context window, and
    says so.
    """
    if override is not None and override > 0:
        return Budget(override, "--budget", exact=True)

    source = env if env is not None else os.environ
    raw = source.get(BUDGET_ENV_VAR)
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return Budget(value, BUDGET_ENV_VAR, exact=True)
        except (TypeError, ValueError):
            pass  # a malformed override falls through rather than crashing

    configured = fraction is not None and fraction > 0
    used_fraction = fraction if configured and fraction else DEFAULT_BUDGET_FRACTION
    tokens = context_tokens if context_tokens and context_tokens > 0 else DEFAULT_CONTEXT_TOKENS
    chars = int(tokens * used_fraction * CHARS_PER_TOKEN)
    pct = used_fraction * 100
    # say whether the share is the user's own setting or our default, so nobody has
    # to wonder whether their skillListingBudgetFraction was picked up
    whose = "your skillListingBudgetFraction" if configured else "the default"
    return Budget(
        chars,
        f"{pct:g}% ({whose}) of a {tokens:,}-token context window, "
        f"at ~{CHARS_PER_TOKEN} chars/token",
        exact=False,
    )


def total_discovery_cost(*groups: Sequence[_HasCost]) -> int:
    """Sum the discovery cost across any number of skill/command groups."""
    return sum(item.discovery_cost for group in groups for item in group)
