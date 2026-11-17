"""Find every skill and slash-command Claude Code would load.

Locations mirror what Claude Code actually reads (verified on disk):
  * user skills      ~/.claude/skills/<name>/SKILL.md
  * project skills   <root>/.claude/skills/<name>/SKILL.md
  * plugin skills    <plugin>/skills/<name>/SKILL.md, for each plugin that is
                     installed and enabled (see `plugin_roots`)
  * synced skills    ~/.claude/skills/synced/<bucket>/<name>/SKILL.md, the skills
                     enabled on a claude.ai account (see `synced_skill_files`)
  * commands         ~/.claude/commands/**.md, <root>/.claude/commands/**.md,
                     and <plugin>/commands/**.md for the same plugins

Skills and commands share one discovery-token budget, so commands are discovered
too — they count toward the budget even though skilldoctor lints skills in depth.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from skilldoctor.model import (
    SOURCE_EXPLICIT,
    SOURCE_PLUGIN,
    SOURCE_PROJECT,
    SOURCE_SYNCED,
    SOURCE_USER,
    Skill,
    SlashCommand,
)
from skilldoctor.parse import load_skill, split_frontmatter
from skilldoctor.parse import parse_frontmatter as _parse_fm
from skilldoctor.settings import load_settings


def _default_home() -> Path:
    return Path.home()


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _manifest(root: Path) -> dict[str, Any]:
    data = _json(root / ".claude-plugin" / "plugin.json")
    return data if isinstance(data, dict) else {}


def _is_enabled(key: str, root: Path, enabled: dict[str, bool]) -> bool:
    """An `enabledPlugins` entry decides; without one, the plugin's own
    `defaultEnabled` does, and that defaults to true."""
    if key in enabled:
        return enabled[key]
    return _manifest(root).get("defaultEnabled") is not False


def _same_dir(a: str, b: Path) -> bool:
    try:
        return Path(a).resolve() == b.resolve()
    except (OSError, ValueError):
        return False


def plugin_roots(home: Path, project_root: Path) -> list[Path]:
    """The folders of the plugins Claude Code loads: installed and enabled.

    `~/.claude/plugins/` also holds what Claude Code does *not* load: each added
    marketplace's catalog clone (`marketplaces/`), earlier versions of installed
    plugins (`cache/<marketplace>/<plugin>/<old version>/`), and plugins that are
    switched off. Scanning the whole tree counted those too, so one installed
    plugin showed up as a duplicate of its own catalog entry (issue #1).

    Installed plugins come from `installed_plugins.json`, each at its
    `installPath`; a project- or local-scope install counts only in its own
    project. Plugins synced from a claude.ai account sit in
    `synced/<account>/<name>[~gN]/` and are keyed `<name>@synced`; where one name
    has several folders, the one marked `.in_use` is taken (observed on Claude
    Code 2.1.325). A plugin is skipped when `enabledPlugins` turns it off, in user,
    project or local settings.

    Without a readable `installed_plugins.json` (an older Claude Code), every
    plugin under `cache/` is taken, which can still include earlier versions."""
    plugins = home / ".claude" / "plugins"
    enabled = load_settings(home, project_root).enabled_plugins
    found: list[tuple[str, Path]] = []

    registry = _json(plugins / "installed_plugins.json")
    installed = registry.get("plugins") if isinstance(registry, dict) else None
    if isinstance(installed, dict):
        for key, entries in installed.items():
            for entry in entries if isinstance(entries, list) else [entries]:
                if not isinstance(entry, dict) or not isinstance(entry.get("installPath"), str):
                    continue
                where = entry.get("projectPath")
                if isinstance(where, str) and not _same_dir(where, project_root):
                    continue
                found.append((str(key), Path(entry["installPath"])))
    elif (plugins / "cache").is_dir():
        for root in sorted(d for d in (plugins / "cache").glob("*/*/*") if d.is_dir()):
            found.append((f"{root.parent.name}@{root.parent.parent.name}", root))

    synced: dict[str, list[Path]] = {}
    if (plugins / "synced").is_dir():
        for folder in sorted(d for d in (plugins / "synced").glob("*/*") if d.is_dir()):
            synced.setdefault(folder.name.split("~")[0], []).append(folder)
    for name, folders in synced.items():
        in_use = [f for f in folders if (f / ".in_use").exists()]
        found.append((f"{name}@synced", (in_use or folders)[-1]))

    roots: list[Path] = []
    for key, root in found:
        if root.is_dir() and _is_enabled(key, root, enabled) and root not in roots:
            roots.append(root)
    return roots


def _paths(root: Path, value: Any) -> list[Path]:
    """A manifest path field: one string or a list of them, relative to the plugin."""
    items = value if isinstance(value, list) else [value]
    return [root / v for v in items if isinstance(v, str)]


def _plugin_skill_files(root: Path) -> list[Path]:
    """`skills/` plus any folders the manifest's `skills` field adds to it."""
    dirs = [root / "skills", *_paths(root, _manifest(root).get("skills"))]
    return sorted({p for d in dirs if d.is_dir() for p in d.glob("*/SKILL.md")})


def _plugin_command_files(root: Path) -> list[Path]:
    """`commands/`, unless the manifest's `commands` field replaces it."""
    field_value = _manifest(root).get("commands")
    targets = _paths(root, field_value) if field_value is not None else [root / "commands"]
    out: set[Path] = set()
    for t in targets:
        if t.is_file() and t.suffix == ".md":
            out.add(t)
        elif t.is_dir():
            out.update(t.rglob("*.md"))
    return sorted(out)


def synced_skill_files(home: Path, project_root: Path) -> list[Path]:
    """Skills synced from a claude.ai account, unless `syncClaudeAiSkills` is off.

    Claude Code downloads them into `~/.claude/skills/synced/` (documented), one
    folder per account and then one per skill: `synced/<bucket>/<name>/SKILL.md`
    (that inner layout is observed on Claude Code 2.1.325). They sit two levels
    below the user skills folder, so the user scan never reached them. Hidden
    folders hold syncs in progress and are skipped."""
    if not load_settings(home, project_root).sync_claude_ai_skills:
        return []
    synced = home / ".claude" / "skills" / "synced"
    if not synced.is_dir():
        return []
    return sorted(
        p for p in synced.glob("*/*/SKILL.md")
        if not p.parent.name.startswith(".") and not p.parent.parent.name.startswith(".")
    )


def discover_skills(
    home: Path | None = None,
    project_root: Path | None = None,
    extra_dirs: Sequence[Path] | None = None,
) -> list[Skill]:
    """All skills, de-duplicated by resolved path (so project == home doesn't
    double-count). Order: explicit `--skills` dirs, then user, project, plugins,
    synced.

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

    for root in plugin_roots(home, project_root):
        for p in _plugin_skill_files(root):
            add(p, SOURCE_PLUGIN)

    for p in synced_skill_files(home, project_root):
        add(p, SOURCE_SYNCED)

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

    for root in plugin_roots(home, project_root):
        for p in _plugin_command_files(root):
            add(p, SOURCE_PLUGIN)

    return found
