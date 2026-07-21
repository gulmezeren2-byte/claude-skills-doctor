"""Shared test helpers. Kept out of conftest.py so they are imported explicitly
(conftest is auto-loaded by pytest; importing from it risks a double load)."""

from __future__ import annotations

from pathlib import Path

from skilldoctor.model import SOURCE_USER, Skill


def write_skill(root: Path, folder: str, frontmatter: str, body: str = "# body\n") -> Path:
    """Create <root>/.claude/skills/<folder>/SKILL.md with raw (possibly malformed)
    frontmatter, so tests can craft broken YAML on purpose."""
    d = root / ".claude" / "skills" / folder
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return p


def write_command(root: Path, name: str, text: str) -> Path:
    d = root / ".claude" / "commands"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def make_skill(
    folder: str, *, name: str | None = None, description: str = "",
    body: str = "", source: str = SOURCE_USER, extra: dict | None = None,
) -> Skill:
    """Build a Skill directly (no disk) for unit-testing checks. `name` defaults
    to `folder`; pass "__omit__" to leave a field out of the frontmatter."""
    fm: dict = {}
    if name is None:
        name = folder
    if name != "__omit__":
        fm["name"] = name
    if description != "__omit__":
        fm["description"] = description
    if extra:
        fm.update(extra)
    return Skill(
        folder_name=folder, path=Path(f"/x/{folder}/SKILL.md"),
        source=source, frontmatter=fm, body=body,
    )
