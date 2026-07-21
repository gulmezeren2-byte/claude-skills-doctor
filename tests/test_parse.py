"""Tests for frontmatter parsing — especially the failure modes that matter:
invalid YAML must be captured, never raised, because it silently breaks loading."""

from __future__ import annotations

from pathlib import Path

from skilldoctor.parse import load_skill, parse_frontmatter, split_frontmatter


def test_split_valid_frontmatter() -> None:
    fm, body = split_frontmatter("---\nname: x\n---\n\n# Title\nbody")
    assert fm == "name: x"
    assert body.strip() == "# Title\nbody"


def test_split_no_frontmatter() -> None:
    fm, body = split_frontmatter("# just a doc\nno frontmatter")
    assert fm is None
    assert body.startswith("# just a doc")


def test_split_normalises_crlf() -> None:
    fm, _ = split_frontmatter("---\r\nname: x\r\n---\r\n\r\nbody")
    assert fm == "name: x"


def test_parse_valid_mapping() -> None:
    data, err = parse_frontmatter("name: x\ndescription: y")
    assert err is None
    assert data == {"name": "x", "description": "y"}


def test_parse_invalid_yaml_returns_error_not_raise() -> None:
    data, err = parse_frontmatter("name: : : bad\n  - broken")
    assert data == {}
    assert err is not None and "YAML" in err


def test_parse_non_mapping() -> None:
    data, err = parse_frontmatter("- a\n- b")
    assert data == {}
    assert err is not None and "mapping" in err


def test_parse_empty() -> None:
    data, err = parse_frontmatter("")
    assert data == {} and err is not None


def test_load_skill_valid(tmp_path: Path) -> None:
    d = tmp_path / "mine"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: mine\ndescription: does a thing\n---\n\nbody", "utf-8"
    )
    s = load_skill(d / "SKILL.md", "user")
    assert s.name == "mine"
    assert s.description == "does a thing"
    assert s.yaml_error is None
    assert s.folder_name == "mine"


def test_load_skill_no_frontmatter(tmp_path: Path) -> None:
    d = tmp_path / "x"
    d.mkdir()
    (d / "SKILL.md").write_text("# no frontmatter here", "utf-8")
    s = load_skill(d / "SKILL.md", "user")
    assert s.yaml_error is not None and "frontmatter" in s.yaml_error


def test_load_skill_invalid_yaml(tmp_path: Path) -> None:
    d = tmp_path / "x"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: : bad :\n---\nbody", "utf-8")
    s = load_skill(d / "SKILL.md", "user")
    assert s.yaml_error is not None


def test_load_skill_missing_file(tmp_path: Path) -> None:
    s = load_skill(tmp_path / "nope" / "SKILL.md", "user")
    assert s.yaml_error is not None and "could not read" in s.yaml_error
