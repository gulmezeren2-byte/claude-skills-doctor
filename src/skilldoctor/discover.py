"""Find every skill and slash-command Claude Code would load.

Locations mirror what Claude Code actually reads (verified on disk):
  * user skills      ~/.claude/skills/<name>/SKILL.md
  * project skills   <root>/.claude/skills/<name>/SKILL.md
  * plugin skills    ~/.claude/plugins/**/skills/<name>/SKILL.md
  * commands         ~/.claude/commands/**.md, <root>/.claude/commands/**.md,
                     and plugin commands under ~/.claude/plugins/**/commands/**.md

Skills and commands share one discovery-token budget, so commands are discovered
too — they count toward the budget even though skilldoctor lints skills in depth.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from skilldoctor.model import (
    SOURCE_EXPLICIT,
    SOURCE_PLUGIN,
    SOURCE_PROJECT,
    SOURCE_USER,
    Skill,
    SlashCommand,
)
from skilldoctor.parse import load_skill, split_frontmatter
from skilldoctor.parse import parse_frontmatter as _parse_fm


def _default_home() -> Path:
    return Path.home()


def discover_skills(
    home: Path | None = None,
    project_root: Path | None = None,
    extra_dirs: Sequence[Path] | None = None,
) -> list[Skill]:
    """All skills, de-duplicated by resolved path (so project == home doesn't
    double-count). Order: explicit `--skills` dirs, then user, project, plugins.

    `extra_dirs` are skills roots you name yourself — a plugin repo's `skills/`
    folder, say. They are checked first and in full, because they are the ones you
    are authoring: a skill author wants them linted in CI before publishing, which
    is not something the ~/.claude locations can express."""
    home = home or _default_home()
    project_root = project_root or Path.cwd()

    found: list[Skill] = []
    seen: set[Path] = set()

    def add(path: Path, source: str) -> None:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            return
        seen.add(key)
        found.append(load_skill(path, source))

    for extra in extra_dirs or ():
        extra = Path(extra)
        # Tolerant: accept either a skills root (skills/<name>/SKILL.md) or a single
        # skill folder pointed at directly.
        if (extra / "SKILL.md").is_file():
            add(extra / "SKILL.md", SOURCE_EXPLICIT)
        elif extra.is_dir():
            for p in sorted(extra.glob("*/SKILL.md")):
                add(p, SOURCE_EXPLICIT)

    user_dir = home / ".claude" / "skills"
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*/SKILL.md")):
            add(p, SOURCE_USER)

    project_dir = project_root / ".claude" / "skills"
    if project_dir.is_dir():
        for p in sorted(project_dir.glob("*/SKILL.md")):
            add(p, SOURCE_PROJECT)

    plugins_dir = home / ".claude" / "plugins"
    if plugins_dir.is_dir():
        for p in sorted(plugins_dir.glob("**/skills/*/SKILL.md")):
            add(p, SOURCE_PLUGIN)

    return found


def _command_description(text: str) -> str:
    """A command's description: frontmatter `description` if present, else the
    first non-empty, non-heading line of the body."""
    fm_text, body = split_frontmatter(text)
    if fm_text is not None:
        fm, _ = _parse_fm(fm_text)
        desc = fm.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s
    return ""


def _load_command(path: Path, source: str) -> SlashCommand:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    return SlashCommand(
        name=path.stem, path=path, source=source, description=_command_description(text)
    )


def discover_commands(
    home: Path | None = None, project_root: Path | None = None
) -> list[SlashCommand]:
    """All slash-commands that share the discovery budget."""
    home = home or _default_home()
    project_root = project_root or Path.cwd()

    found: list[SlashCommand] = []
    seen: set[Path] = set()

    def add(path: Path, source: str) -> None:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            return
        seen.add(key)
        found.append(_load_command(path, source))

    user_cmd = home / ".claude" / "commands"
    if user_cmd.is_dir():
        for p in sorted(user_cmd.rglob("*.md")):
            add(p, SOURCE_USER)

    project_cmd = project_root / ".claude" / "commands"
    if project_cmd.is_dir():
        for p in sorted(project_cmd.rglob("*.md")):
            add(p, SOURCE_PROJECT)

    plugins_dir = home / ".claude" / "plugins"
    if plugins_dir.is_dir():
        for p in sorted(plugins_dir.glob("**/commands/**/*.md")):
            add(p, SOURCE_PLUGIN)

    return found
