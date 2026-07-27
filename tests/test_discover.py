"""Tests for discovery across user / project / plugin locations."""

from __future__ import annotations

from pathlib import Path

from skilldoctor.checks import check_all
from skilldoctor.discover import discover_commands, discover_skills
from skilldoctor.model import SOURCE_EXPLICIT, SOURCE_PLUGIN, SOURCE_PROJECT, SOURCE_USER
from tests.helpers import write_command, write_skill


def _plugin_skill(home: Path, plugin: str, folder: str) -> Path:
    base = home / ".claude" / "plugins" / "marketplaces" / "m" / "plugins"
    d = base / plugin / "skills" / folder
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text("---\nname: pl\ndescription: a plugin skill here\n---\nbody", "utf-8")
    return p


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
