"""Parse a SKILL.md into frontmatter + body.

The spec is unforgiving in a way that matters here: *invalid YAML silently
prevents a skill from loading*. So the parser never raises on bad frontmatter —
it records the reason (`yaml_error`) and hands back a Skill the checks can flag.
That is the whole point: the failure is invisible in Claude Code, so skilldoctor has
to make it visible.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from skilldoctor.model import Skill

# Frontmatter is a leading `---` block. We tolerate trailing spaces on the fence
# lines and require the closing fence on its own line.
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_text, body). frontmatter_text is None when there is no
    parseable `---` block at all. Newlines are normalised so Windows CRLF files
    behave the same as LF."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---"):
        return None, normalized
    m = _FRONTMATTER_RE.match(normalized)
    if not m:
        return None, normalized
    return m.group(1), normalized[m.end() :]


def parse_frontmatter(fm_text: str) -> tuple[dict[str, Any], str | None]:
    """Parse frontmatter YAML. Returns (mapping, error). On any problem the mapping
    is empty and error explains why — never raises."""
    try:
        data = yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else "invalid YAML"
        return {}, f"invalid YAML in frontmatter: {detail}"
    if data is None:
        return {}, "frontmatter is empty"
    if not isinstance(data, dict):
        return {}, f"frontmatter must be a mapping, got {type(data).__name__}"
    return data, None


def load_skill(path: Path, source: str) -> Skill:
    """Load one SKILL.md from disk into a Skill. Unreadable files become a Skill
    carrying the read error, so a permission problem is surfaced, not swallowed."""
    folder_name = path.parent.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Skill(
            folder_name=folder_name, path=path, source=source,
            yaml_error=f"could not read file: {exc}",
        )

    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        return Skill(
            folder_name=folder_name, path=path, source=source, body=body,
            yaml_error="no YAML frontmatter (file must start with a '---' block)",
        )
    frontmatter, error = parse_frontmatter(fm_text)
    return Skill(
        folder_name=folder_name, path=path, source=source,
        frontmatter=frontmatter, body=body.strip(), yaml_error=error,
    )
