"""Read the settings Claude Code actually uses, instead of assuming defaults.

Three settings change what the listing costs and what it is allowed to cost, and all
three are sitting on disk already:

* `skillListingBudgetFraction` — the share of the model's context window the listing
  may use (default 1%). Someone who raised it to 2% does not want to be told they are
  over a budget they already moved.
* `skillListingMaxDescChars` — the per-entry truncation point (default 1,536).
* `skillOverrides` — per-skill visibility. A skill set to `name-only` contributes only
  its name to the listing, and one set to `off` or `user-invocable-only` contributes
  nothing at all. Counting their descriptions anyway would overstate the total and
  raise an alarm about skills the user has already dealt with.

Precedence, highest last, per the settings documentation: user, then project, then
project-local. Command-line flags sit above all of these and are applied by the
caller. **Managed/enterprise settings are deliberately not read** — their location is
platform-specific and unverified here, and reading the wrong file is worse than
admitting the gap.

Source: <https://code.claude.com/docs/en/settings>, <https://code.claude.com/docs/en/skills>
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The four states a `skillOverrides` entry can take.
LISTING_ON = "on"  # name and description — the default when absent
LISTING_NAME_ONLY = "name-only"  # name listed, description withheld
LISTING_USER_ONLY = "user-invocable-only"  # hidden from Claude, still typable
LISTING_OFF = "off"  # hidden entirely
LISTING_STATES = frozenset({LISTING_ON, LISTING_NAME_ONLY, LISTING_USER_ONLY, LISTING_OFF})


@dataclass(frozen=True)
class Settings:
    """What the settings files say, plus which of them we actually read — so a
    report can show its work rather than assert a number from nowhere."""

    budget_fraction: float | None = None
    max_desc_chars: int | None = None
    skill_overrides: dict[str, str] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()

    def listing_state(self, skill_name: str) -> str:
        """A skill absent from `skillOverrides` is treated as `on`."""
        state = self.skill_overrides.get(skill_name, LISTING_ON)
        return state if state in LISTING_STATES else LISTING_ON


def _read(path: Path) -> dict[str, Any] | None:
    """One settings file, or None. A settings file that is missing, unreadable or
    malformed is not this tool's problem to fail on — it just has nothing to say."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def settings_paths(home: Path | None, project_root: Path | None) -> list[Path]:
    """Lowest precedence first, so a later file overrides an earlier one.

    `home` is the parent of `.claude`, matching what `discover` treats it as — the
    two have to agree, or the settings read would describe a different installation
    from the skills scanned.
    """
    paths = []
    if home is not None:
        paths.append(Path(home) / ".claude" / "settings.json")
    if project_root is not None:
        root = Path(project_root) / ".claude"
        paths.append(root / "settings.json")
        paths.append(root / "settings.local.json")
    return paths


def load_settings(home: Path | None, project_root: Path | None) -> Settings:
    fraction: float | None = None
    max_chars: int | None = None
    overrides: dict[str, str] = {}
    read_from: list[Path] = []

    for path in settings_paths(home, project_root):
        data = _read(path)
        if data is None:
            continue
        read_from.append(path)

        raw_fraction = data.get("skillListingBudgetFraction")
        if isinstance(raw_fraction, (int, float)) and 0 < float(raw_fraction) <= 1:
            fraction = float(raw_fraction)

        raw_cap = data.get("skillListingMaxDescChars")
        if isinstance(raw_cap, int) and raw_cap > 0:
            max_chars = raw_cap

        raw_overrides = data.get("skillOverrides")
        if isinstance(raw_overrides, dict):
            for name, state in raw_overrides.items():
                if isinstance(name, str) and state in LISTING_STATES:
                    overrides[name] = state

    return Settings(
        budget_fraction=fraction,
        max_desc_chars=max_chars,
        skill_overrides=overrides,
        sources=tuple(read_from),
    )
