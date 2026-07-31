"""Reading the settings Claude Code actually uses.

These three settings change what the listing costs and what it may cost, and all
three are on disk already. Assuming defaults when the user has configured otherwise
is how a measurement tool raises an alarm about a problem the user already solved.
"""

from __future__ import annotations

import json
from pathlib import Path

from skilldoctor.budget import budget_limit, total_discovery_cost
from skilldoctor.settings import (
    LISTING_NAME_ONLY,
    LISTING_OFF,
    LISTING_ON,
    load_settings,
)
from tests.helpers import make_skill


def write_settings(directory: Path, name: str, data: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# nothing configured
# --------------------------------------------------------------------------- #
def test_no_settings_files_means_no_opinions(tmp_path: Path) -> None:
    s = load_settings(home=tmp_path / "nope", project_root=tmp_path / "also-nope")
    assert s.budget_fraction is None
    assert s.max_desc_chars is None
    assert s.skill_overrides == {}
    assert s.sources == ()
    assert s.listing_state("anything") == LISTING_ON


def test_a_malformed_settings_file_is_ignored_not_fatal(tmp_path: Path) -> None:
    # someone else's broken JSON is not this tool's failure to have
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    assert load_settings(home=home, project_root=None).budget_fraction is None


def test_a_bom_does_not_hide_the_settings(tmp_path: Path) -> None:
    # a UTF-8 BOM is easy to introduce on Windows and would otherwise make the file
    # parse-fail silently, which is exactly the class of bug this tool exists to catch
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        '﻿{"skillListingBudgetFraction": 0.02}', encoding="utf-8"
    )
    assert load_settings(home=home, project_root=None).budget_fraction == 0.02


# --------------------------------------------------------------------------- #
# precedence
# --------------------------------------------------------------------------- #
def test_project_settings_beat_user_settings(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "proj"
    write_settings(home / ".claude", "settings.json", {"skillListingBudgetFraction": 0.01})
    write_settings(project / ".claude", "settings.json", {"skillListingBudgetFraction": 0.03})
    assert load_settings(home=home, project_root=project).budget_fraction == 0.03


def test_local_settings_beat_project_settings(tmp_path: Path) -> None:
    # `.claude/settings.local.json` is what the /skills menu writes, so it has to win
    home = tmp_path / "home"
    project = tmp_path / "proj"
    write_settings(project / ".claude", "settings.json", {"skillListingBudgetFraction": 0.03})
    write_settings(
        project / ".claude", "settings.local.json", {"skillListingBudgetFraction": 0.05}
    )
    s = load_settings(home=home, project_root=project)
    assert s.budget_fraction == 0.05
    assert len(s.sources) == 2  # and it says which files it read


# --------------------------------------------------------------------------- #
# what the settings change
# --------------------------------------------------------------------------- #
def test_a_configured_fraction_moves_the_budget_and_says_so(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_settings(home / ".claude", "settings.json", {"skillListingBudgetFraction": 0.02})
    s = load_settings(home=home, project_root=None)
    limit = budget_limit(env={}, fraction=s.budget_fraction, context_tokens=200_000)
    assert limit.chars == 16000
    # someone who doubled their own budget should not have to guess whether we saw it
    assert "skillListingBudgetFraction" in limit.source


def test_a_nonsense_fraction_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_settings(home / ".claude", "settings.json", {"skillListingBudgetFraction": 7})
    assert load_settings(home=home, project_root=None).budget_fraction is None


def test_skill_overrides_are_read_and_unknown_states_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_settings(
        home / ".claude", "settings.json",
        {"skillOverrides": {"quiet": "name-only", "gone": "off", "bogus": "nonsense"}},
    )
    s = load_settings(home=home, project_root=None)
    assert s.listing_state("quiet") == LISTING_NAME_ONLY
    assert s.listing_state("gone") == LISTING_OFF
    assert s.listing_state("bogus") == LISTING_ON  # unknown state falls back to listed
    assert s.listing_state("absent") == LISTING_ON


# --------------------------------------------------------------------------- #
# and the cost that follows from them
# --------------------------------------------------------------------------- #
def test_a_name_only_skill_costs_only_its_name() -> None:
    s = make_skill("quiet", name="quiet", description="x" * 500)
    s.listing_state = LISTING_NAME_ONLY
    assert total_discovery_cost([s]) == len("quiet")


def test_a_hidden_skill_costs_nothing() -> None:
    for state in (LISTING_OFF, "user-invocable-only"):
        s = make_skill("gone", name="gone", description="x" * 500)
        s.listing_state = state
        assert total_discovery_cost([s]) == 0


def test_a_configured_cap_replaces_the_default() -> None:
    s = make_skill("big", name="big", description="x" * 5000)
    s.listing_cap = 200
    assert total_discovery_cost([s]) == len("big") + 200
