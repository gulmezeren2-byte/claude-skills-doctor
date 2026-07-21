"""Tests for the deterministic checks — the core value of skilldoctor."""

from __future__ import annotations

from pathlib import Path

from skilldoctor.checks import (
    check_all,
    check_budget,
    check_collisions,
    check_duplicates,
    check_skill,
)
from skilldoctor.model import ERROR, INFO, SOURCE_PLUGIN, WARNING, Skill
from skilldoctor.parse import load_skill
from tests.helpers import make_skill, write_skill

GOOD_DESC = "Parse a catalog PDF into rows. Use when the user mentions a birim fiyat PDF."


def _checks(skill: Skill) -> set[str]:
    return {f.check for f in check_skill(skill)}


def test_clean_skill_has_no_findings() -> None:
    s = make_skill("pdf-tools", description=GOOD_DESC, body="# PDF\nDo the thing.")
    assert check_skill(s) == []


def test_frontmatter_invalid_short_circuits() -> None:
    s = Skill(folder_name="x", path=Path("/x/SKILL.md"), source="user",
              yaml_error="invalid YAML in frontmatter: bad")
    findings = check_skill(s)
    assert len(findings) == 1
    assert findings[0].check == "frontmatter-invalid" and findings[0].severity == ERROR


def test_missing_name_and_description() -> None:
    s = make_skill("x", name="__omit__", description="__omit__")
    checks = _checks(s)
    assert "missing-name" in checks
    assert "missing-description" in checks


def test_name_folder_mismatch() -> None:
    s = make_skill("pdf-tools", name="pdf", description=GOOD_DESC)
    assert "name-folder-mismatch" in _checks(s)


def test_name_format_uppercase_and_length() -> None:
    assert "name-format" in _checks(make_skill("Bad", name="Bad", description=GOOD_DESC))
    long = "a" * 70
    assert "name-format" in _checks(make_skill(long, name=long, description=GOOD_DESC))


def test_description_too_long_and_angle_brackets() -> None:
    assert "description-too-long" in _checks(make_skill("x", description="d" * 1100))
    assert "description-angle-brackets" in _checks(
        make_skill("x", description=GOOD_DESC + " use <tag>")
    )


def test_description_vague_when_thin() -> None:
    assert "description-vague" in _checks(make_skill("x", description="does stuff"))
    # a long, specific description (no literal "when") is NOT flagged
    assert "description-vague" not in _checks(make_skill("x", description=GOOD_DESC))


def test_description_workflow_pattern() -> None:
    d = "Do it. Step 1 open the file. Step 2 parse. Then write output back to disk now."
    assert "description-is-workflow" in _checks(make_skill("x", description=d))


def test_body_empty_and_large() -> None:
    assert "body-empty" in _checks(make_skill("x", description=GOOD_DESC, body="   "))
    big = make_skill("x", description=GOOD_DESC, body="x" * 21000)
    assert "body-too-large" in _checks(big)


def test_absolute_path_in_body() -> None:
    s = make_skill("x", description=GOOD_DESC, body="Read /Users/me/secret.txt now")
    assert "absolute-path" in _checks(s)


def test_allowed_tools_vs_body() -> None:
    s = make_skill("x", description=GOOD_DESC, body="Then run Bash to build.",
                   extra={"allowed-tools": ["Read", "Write"]})
    assert "allowed-tools-body" in _checks(s)
    ok = make_skill("x", description=GOOD_DESC, body="Then run Bash.",
                    extra={"allowed-tools": ["Bash"]})
    assert "allowed-tools-body" not in _checks(ok)


def test_unexpected_key_is_info() -> None:
    s = make_skill("x", description=GOOD_DESC, extra={"typoo": 1})
    hit = [f for f in check_skill(s) if f.check == "unexpected-frontmatter-key"]
    assert len(hit) == 1 and hit[0].severity == INFO


def test_known_extra_keys_are_allowed() -> None:
    s = make_skill("x", description=GOOD_DESC,
                   extra={"version": "0.1.0", "argument-hint": "[x]", "model": "sonnet"})
    assert "unexpected-frontmatter-key" not in _checks(s)


def test_full_false_skips_quality_checks() -> None:
    # check_skill itself is source-agnostic; `full=False` runs only load-breakers.
    s = make_skill("folder", name="different-name", description="x")
    assert "name-folder-mismatch" not in {f.check for f in check_skill(s, full=False)}
    assert "name-folder-mismatch" in {f.check for f in check_skill(s, full=True)}


def test_check_all_scopes_plugin_skills() -> None:
    # the plugin policy is applied by check_all: plugins get load-breakers only.
    mism = dict(name="different-name", description="a solid description for routing here")
    plugin = make_skill("folder", source=SOURCE_PLUGIN, **mism)
    user = make_skill("folder", source="user", **mism)
    plugin_checks = {f.check for f in check_all([plugin], [], 15000).findings}
    user_checks = {f.check for f in check_all([user], [], 15000).findings}
    assert "name-folder-mismatch" not in plugin_checks
    assert "name-folder-mismatch" in user_checks


def test_human_docs_on_disk(tmp_path: Path) -> None:
    p = write_skill(tmp_path, "mine", f"name: mine\ndescription: {GOOD_DESC}")
    (p.parent / "README.md").write_text("hi", encoding="utf-8")
    skill = load_skill(p, "user")
    assert "human-docs" in _checks(skill)


def test_duplicate_names() -> None:
    a = make_skill("a", name="dup", description=GOOD_DESC)
    b = make_skill("b", name="dup", description=GOOD_DESC)
    findings = check_duplicates([a, b])
    assert len(findings) == 1 and findings[0].check == "duplicate-name"
    assert findings[0].severity == ERROR


def test_description_collisions() -> None:
    d = "Review the code changes carefully and report bugs, issues, and risky edits found"
    a = make_skill("a", description=d)
    b = make_skill("b", description=d + " today")
    findings = check_collisions([a, b])
    assert findings and findings[0].check == "description-collision"


def test_budget_over_and_near() -> None:
    big = [make_skill(f"s{i}", description="d" * 200) for i in range(100)]
    over = check_budget(big, [], limit=1000)
    assert over and over[0].check == "budget-exceeded" and over[0].severity == ERROR

    near = check_budget([make_skill("s", description="d" * 850)], [], limit=1000)
    assert near and near[0].check == "budget-near" and near[0].severity == WARNING


def test_check_all_coverage_counts() -> None:
    skills = [
        make_skill("good", description=GOOD_DESC),
        make_skill("bad", name="mismatch", description=GOOD_DESC),
    ]
    report = check_all(skills, [], limit=15000)
    assert report.skills_scanned == 2
    assert report.errors >= 1  # the mismatch
    assert report.budget_used > 0
