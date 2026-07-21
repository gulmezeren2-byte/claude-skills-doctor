"""The discovery-token budget — skilldoctor's headline.

As of Claude Code 2.0.70 the combined skill + command descriptions injected into
the system prompt default to a 15,000-character budget (~4,000 tokens), overridable
with the SLASH_COMMAND_TOOL_CHAR_BUDGET environment variable. When the total goes
over, Claude Code simply stops listing some skills — with **no warning** — and is
told not to use skills it wasn't told about. That silent cliff is exactly what
skilldoctor measures.

We count each skill/command's `name` + `description` characters. This is an
estimate: the real budget also includes minor per-entry formatting, so treat the
number as "close, and on the right side of caution", not byte-exact.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Protocol

DEFAULT_BUDGET_CHARS = 15000
BUDGET_ENV_VAR = "SLASH_COMMAND_TOOL_CHAR_BUDGET"
# Warn when this fraction of the budget is used even if not yet over — going over
# is silent, so the useful moment to act is before you cross the line.
WARN_RATIO = 0.8


class _HasCost(Protocol):
    @property
    def discovery_cost(self) -> int: ...


def budget_limit(env: dict[str, str] | None = None) -> int:
    """The active budget: SLASH_COMMAND_TOOL_CHAR_BUDGET if set to a positive int,
    else the 15,000-char default. A malformed override falls back to the default
    rather than crashing."""
    source = env if env is not None else os.environ
    raw = source.get(BUDGET_ENV_VAR)
    if raw is not None:
        try:
            value = int(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return DEFAULT_BUDGET_CHARS


def total_discovery_cost(*groups: Sequence[_HasCost]) -> int:
    """Sum the discovery cost across any number of skill/command groups."""
    return sum(item.discovery_cost for group in groups for item in group)
