"""Tests for the discovery budget — the headline number."""

from __future__ import annotations

from skilldoctor.budget import DEFAULT_BUDGET_CHARS, budget_limit, total_discovery_cost
from tests.helpers import make_skill


def test_default_budget() -> None:
    assert budget_limit(env={}) == DEFAULT_BUDGET_CHARS


def test_env_override() -> None:
    assert budget_limit(env={"SLASH_COMMAND_TOOL_CHAR_BUDGET": "30000"}) == 30000


def test_malformed_env_falls_back() -> None:
    var = "SLASH_COMMAND_TOOL_CHAR_BUDGET"
    assert budget_limit(env={var: "notanumber"}) == DEFAULT_BUDGET_CHARS
    assert budget_limit(env={var: "-5"}) == DEFAULT_BUDGET_CHARS
    assert budget_limit(env={var: "0"}) == DEFAULT_BUDGET_CHARS


def test_total_cost_counts_name_plus_description() -> None:
    s = make_skill("ab", name="ab", description="cdef")  # 2 + 4 = 6
    assert total_discovery_cost([s]) == 6


def test_total_cost_across_groups() -> None:
    a = make_skill("a", name="a", description="xy")  # 3
    b = make_skill("bb", name="bb", description="z")  # 3
    assert total_discovery_cost([a], [b]) == 6
