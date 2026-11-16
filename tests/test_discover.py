"""Tests for discovery across user / project / plugin locations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skilldoctor.checks import check_all, check_duplicates
from skilldoctor.discover import discover_commands, discover_skills
from skilldoctor.model import SOURCE_EXPLICIT, SOURCE_PLUGIN, SOURCE_PROJECT, SOURCE_USER
from tests.helpers import write_command, write_skill


def _skill_in(root: Path, folder: str) -> Path:
    d = root / "skills" / folder
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(f"---\nname: {folder}\ndescription: a plugin skill here\n---\nbody", "utf-8")
    return p


def _install(home: Path, plugin: str, version: str = "1.0.0", mp: str = "m",
             registry: dict | None = None, **entry: object) -> Path:
    """An installed plugin as Claude Code lays it out: the files under
    cache/<marketplace>/<plugin>/<version>/, recorded in installed_plugins.json."""
    plugins = home / ".claude" / "plugins"
    root = plugins / "cache" / mp / plugin / version
    root.mkdir(parents=True, exist_ok=True)
    reg = registry if registry is not None else _read_registry(plugins)
    reg.setdefault("version", 2)
    reg.setdefault("plugins", {})[f"{plugin}@{mp}"] = [
        {"scope": "user", "installPath": str(root), "version": version, **entry}
    ]
    (plugins / "installed_plugins.json").write_text(json.dumps(reg), "utf-8")
    return root


def _read_registry(plugins: Path) -> dict:
    path = plugins / "installed_plugins.json"
    return json.loads(path.read_text("utf-8")) if path.is_file() else {}


def _settings(home: Path, enabled: dict[str, bool]) -> None:
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": enabled}), "utf-8"
    )


def _plugin_skill(home: Path, plugin: str, folder: str) -> Path:
    return _skill_in(_install(home, plugin), folder)


def _plugin_names(home: Path, project: Path) -> list[str]:
    return sorted(s.name for s in discover_skills(home=home, project_root=project)
                  if s.source == SOURCE_PLUGIN)


def test_discovers_user_project_and_plugin(home: Path, project: Path) -> None:
    write_skill(home, "u1", "name: u1\ndescription: user skill one here")
    write_skill(project, "p1", "name: p1\ndescription: project skill one here")
    _plugin_skill(home, "plug", "pk1")

    skills = discover_skills(home=home, project_root=project)
    by_source = {s.source for s in skills}
    assert by_source == {SOURCE_USER, SOURCE_PROJECT, SOURCE_PLUGIN}
    assert len(skills) == 3


def test_dedup_when_project_equals_home(home: Path) -> None:
    write_skill(home, "u1", "name: u1\ndescription: only one copy expected here")
    skills = discover_skills(home=home, project_root=home)
    assert len(skills) == 1  # not double-counted


def test_discovers_commands(home: Path, project: Path) -> None:
    write_command(home, "greet", "---\ndescription: say hello to the user\n---\nrun")
    write_command(project, "build", "# Build\nCompile the project now")
    cmds = discover_commands(home=home, project_root=project)
    names = {c.name for c in cmds}
    assert names == {"greet", "build"}
    greet = next(c for c in cmds if c.name == "greet")
    assert greet.description == "say hello to the user"
    build = next(c for c in cmds if c.name == "build")
    assert build.description == "Compile the project now"  # first non-heading line


def test_extra_dirs_finds_a_skills_root(tmp_path: Path, home: Path, project: Path) -> None:
    # a plugin repo's skills/ folder — the case ~/.claude paths can't express
    d = tmp_path / "skills" / "mine"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: mine\ndescription: a shipped skill\n---\nbody", "utf-8"
    )
    found = discover_skills(
        home=home, project_root=project, extra_dirs=[tmp_path / "skills"]
    )
    assert [s.name for s in found] == ["mine"]
    assert found[0].source == SOURCE_EXPLICIT


def test_extra_dirs_accepts_one_skill_folder(tmp_path: Path, home: Path, project: Path) -> None:
    d = tmp_path / "just-one"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: just-one\ndescription: one skill\n---\nbody", "utf-8"
    )
    found = discover_skills(home=home, project_root=project, extra_dirs=[d])
    assert [s.name for s in found] == ["just-one"]


def test_extra_dirs_are_linted_in_full(tmp_path: Path, home: Path, project: Path) -> None:
    # explicit skills are yours, so they get the full lint (unlike plugin skills)
    d = tmp_path / "skills" / "folder-name"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: different\ndescription: a name that does not match its folder\n---\nb",
        "utf-8",
    )
    found = discover_skills(home=home, project_root=project, extra_dirs=[tmp_path / "skills"])
    report = check_all(found, [], 15000)
    assert "name-folder-mismatch" in {f.check for f in report.findings}


def test_empty_when_nothing_present(home: Path, project: Path) -> None:
    assert discover_skills(home=home, project_root=project) == []
    assert discover_commands(home=home, project_root=project) == []


def test_a_marketplace_catalog_is_not_an_installed_plugin(home: Path, project: Path) -> None:
    # Issue #1: adding a marketplace clones its catalog into plugins/marketplaces/;
    # installing a plugin copies it into plugins/cache/. Claude Code loads only the
    # second, so the first must neither count nor clash with it.
    catalog = home / ".claude" / "plugins" / "marketplaces" / "m" / "plugins" / "playground"
    _skill_in(catalog, "playground")
    _skill_in(catalog.parent / "never-installed", "access")
    _skill_in(_install(home, "playground"), "playground")

    skills = discover_skills(home=home, project_root=project)
    assert [s.name for s in skills] == ["playground"]
    assert check_duplicates(skills) == []


def test_only_the_installed_version_counts(home: Path, project: Path) -> None:
    _skill_in(_install(home, "superpowers", "6.3.0"), "old-only")
    root = _install(home, "superpowers", "7.0.2")  # the registry now points here
    _skill_in(root, "brainstorming")
    assert _plugin_names(home, project) == ["brainstorming"]


def test_a_switched_off_plugin_is_not_loaded(home: Path, project: Path) -> None:
    _skill_in(_install(home, "on"), "kept")
    _skill_in(_install(home, "off"), "dropped")
    _settings(home, {"off@m": False})
    assert _plugin_names(home, project) == ["kept"]

    # project-local settings sit above the user's and can switch it back on
    local = project / ".claude"
    local.mkdir(parents=True)
    (local / "settings.local.json").write_text(json.dumps({"enabledPlugins": {"off@m": True}}))
    assert _plugin_names(home, project) == ["dropped", "kept"]


def test_a_plugin_off_by_default_needs_an_entry(home: Path, project: Path) -> None:
    root = _install(home, "opt-in")
    _skill_in(root, "quiet")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text('{"defaultEnabled": false}')
    assert _plugin_names(home, project) == []
    _settings(home, {"opt-in@m": True})
    assert _plugin_names(home, project) == ["quiet"]


def test_a_project_install_counts_only_in_its_project(
    tmp_path: Path, home: Path, project: Path
) -> None:
    project.mkdir(parents=True)
    _skill_in(_install(home, "here", scope="project", projectPath=str(project)), "here")
    _skill_in(_install(home, "elsewhere", scope="project",
                       projectPath=str(tmp_path / "other")), "elsewhere")
    assert _plugin_names(home, project) == ["here"]


def test_synced_plugins_are_on_unless_switched_off(home: Path, project: Path) -> None:
    synced = home / ".claude" / "plugins" / "synced" / "account"
    _skill_in(synced / "design", "ux-copy")
    _skill_in(synced / "sales~g2", "pitch")
    _skill_in(synced / "legal~g1", "old-generation")
    current = synced / "legal~g2"
    _skill_in(current, "contracts")
    (current / ".in_use").write_text("")
    _settings(home, {"sales@synced": False})
    assert _plugin_names(home, project) == ["contracts", "ux-copy"]


def test_plugin_manifest_paths_add_skills_and_replace_commands(
    home: Path, project: Path
) -> None:
    root = _install(home, "custom")
    _skill_in(root, "default-place")
    _skill_in(root / "more", "extra-place")
    (root / "commands").mkdir()
    (root / "commands" / "ignored.md").write_text("ignored", "utf-8")
    (root / "cmd").mkdir()
    (root / "cmd" / "used.md").write_text("---\ndescription: the one in use\n---\n", "utf-8")
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"skills": "./more/skills/", "commands": ["./cmd/"]})
    )
    assert _plugin_names(home, project) == ["default-place", "extra-place"]
    assert [c.name for c in discover_commands(home=home, project_root=project)] == ["used"]


def test_plugin_commands_come_from_installed_plugins_only(home: Path, project: Path) -> None:
    catalog = home / ".claude" / "plugins" / "marketplaces" / "m" / "plugins" / "dev"
    (catalog / "commands").mkdir(parents=True)
    (catalog / "commands" / "create.md").write_text("catalog copy", "utf-8")
    root = _install(home, "dev")
    (root / "commands").mkdir()
    (root / "commands" / "create.md").write_text("installed copy", "utf-8")
    cmds = discover_commands(home=home, project_root=project)
    assert [(c.name, c.description) for c in cmds] == [("create", "installed copy")]


def test_without_a_registry_the_cache_is_used(home: Path, project: Path) -> None:
    # an older Claude Code with no installed_plugins.json: cache/, never the catalog
    root = home / ".claude" / "plugins" / "cache" / "m" / "p" / "1.0.0"
    _skill_in(root, "cached")
    _skill_in(home / ".claude" / "plugins" / "marketplaces" / "m" / "plugins" / "p", "catalog")
    assert _plugin_names(home, project) == ["cached"]


@pytest.mark.parametrize("registry", [
    "{not json",
    "[]",
    '{"plugins": []}',
    '{"plugins": {"x@m": [{"installPath": 7}, "junk", {"scope": "user"}]}}',
    '{"plugins": {"x@m": [{"installPath": "no/such/folder"}]}}',
])
def test_a_broken_registry_does_not_break_discovery(
    home: Path, project: Path, registry: str
) -> None:
    plugins = home / ".claude" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "installed_plugins.json").write_text(registry, "utf-8")
    write_skill(home, "u1", "name: u1\ndescription: user skill one here")
    assert [s.name for s in discover_skills(home=home, project_root=project)] == ["u1"]
