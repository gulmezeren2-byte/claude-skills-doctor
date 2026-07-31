"""Tests for the listing budget — the headline number, and the one this tool has
to be most careful about, because it is the one a reader will act on."""

from __future__ import annotations

from skilldoctor.budget import (
    CHARS_PER_TOKEN,
    DEFAULT_BUDGET_FRACTION,
    DEFAULT_CONTEXT_TOKENS,
    PER_ENTRY_CAP,
    budget_limit,
    total_discovery_cost,
)
from tests.helpers import make_skill

ENV_VAR = "SLASH_COMMAND_TOOL_CHAR_BUDGET"


# --------------------------------------------------------------------------- #
# where the number comes from
# --------------------------------------------------------------------------- #
def test_the_default_is_derived_from_the_context_window() -> None:
    # Claude Code scales the listing budget at 1% of the model's context window —
    # it is not a fixed character count, so neither is ours
    limit = budget_limit(env={})
    expected = DEFAULT_CONTEXT_TOKENS * DEFAULT_BUDGET_FRACTION * CHARS_PER_TOKEN
    assert limit.chars == int(expected)
    assert limit.exact is False
    assert "context window" in limit.source


def test_a_bigger_context_window_means_a_bigger_budget() -> None:
    # 1% of 1M is five times 1% of 200k; a tool that reported one number for both
    # would be wrong for most users of the other
    small = budget_limit(env={}, context_tokens=200_000)
    large = budget_limit(env={}, context_tokens=1_000_000)
    assert large.chars == small.chars * 5


def test_a_custom_fraction_is_honoured() -> None:
    limit = budget_limit(env={}, fraction=0.02, context_tokens=200_000)
    assert limit.chars == int(200_000 * 0.02 * CHARS_PER_TOKEN)


def test_the_env_var_still_wins_and_is_exact() -> None:
    # Claude Code still reads SLASH_COMMAND_TOOL_CHAR_BUDGET as a fixed character
    # count, so when it is set there is nothing to estimate
    limit = budget_limit(env={ENV_VAR: "30000"})
    assert limit.chars == 30000
    assert limit.exact is True
    assert limit.source == ENV_VAR


def test_an_explicit_budget_beats_everything() -> None:
    limit = budget_limit(env={ENV_VAR: "30000"}, override=12345)
    assert limit.chars == 12345
    assert limit.exact is True


def test_a_malformed_env_var_falls_back_rather_than_crashing() -> None:
    for bad in ("notanumber", "-5", "0"):
        limit = budget_limit(env={ENV_VAR: bad})
        assert limit.exact is False  # fell through to the derived default
        assert limit.chars > 0


def test_a_limit_can_still_be_used_as_a_number() -> None:
    assert int(budget_limit(env={ENV_VAR: "500"})) == 500


# --------------------------------------------------------------------------- #
# what an entry costs
# --------------------------------------------------------------------------- #
def test_cost_counts_name_plus_description() -> None:
    s = make_skill("ab", name="ab", description="cdef")  # 2 + 4 = 6
    assert total_discovery_cost([s]) == 6


def test_when_to_use_is_part_of_the_cost() -> None:
    # the docs are explicit that when_to_use is appended to description in the
    # listing, so leaving it out understates every skill that uses it
    s = make_skill("ab", name="ab", description="cdef")
    s.frontmatter["when_to_use"] = "xy"
    assert total_discovery_cost([s]) == 8


def test_an_over_long_entry_costs_only_the_cap() -> None:
    # the listing truncates each entry at the cap, so a 4,000-char description does
    # not consume 4,000 of the shared budget — counting it raw would overstate the
    # total and send someone trimming a skill that was not the problem
    s = make_skill("ab", name="ab", description="x" * 4000)
    assert total_discovery_cost([s]) == 2 + PER_ENTRY_CAP


def test_total_cost_across_groups() -> None:
    a = make_skill("a", name="a", description="xy")  # 3
    b = make_skill("bb", name="bb", description="z")  # 3
    assert total_discovery_cost([a], [b]) == 6
