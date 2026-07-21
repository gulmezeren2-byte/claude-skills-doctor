"""Tests for the model helpers: coverage counts, ordering, serialisation."""

from __future__ import annotations

from skilldoctor.model import ERROR, INFO, WARNING, Finding, Report
from tests.helpers import make_skill


def test_skill_name_and_cost() -> None:
    s = make_skill("folder", name="folder", description="abcd")
    assert s.name == "folder"
    assert s.discovery_cost == len("folder") + 4


def test_skill_name_falls_back_to_folder() -> None:
    s = make_skill("folder", name="__omit__", description="x")
    assert s.name == "folder"  # no frontmatter name → folder name


def test_report_counts_and_ok() -> None:
    r = Report(
        findings=[
            Finding("a", ERROR, "x", "m"),
            Finding("b", WARNING, "y", "m"),
            Finding("c", INFO, "z", "m"),
        ],
        skills_scanned=3, budget_used=100, budget_limit=15000,
    )
    assert r.errors == 1 and r.warnings == 1 and r.infos == 1
    assert r.ok is False
    assert r.over_budget is False


def test_report_ok_when_no_errors() -> None:
    r = Report(findings=[Finding("b", WARNING, "y", "m")])
    assert r.ok is True


def test_sorted_findings_errors_first() -> None:
    r = Report(findings=[Finding("z", WARNING, "y", "m"), Finding("a", ERROR, "x", "m")])
    order = [f.severity for f in r.sorted_findings()]
    assert order == [ERROR, WARNING]


def test_to_dict_shape() -> None:
    r = Report(findings=[Finding("a", ERROR, "x", "m")], skills_scanned=1,
               budget_used=20000, budget_limit=15000)
    d = r.to_dict()
    assert d["ok"] is False
    assert d["budget"]["over"] is True
    assert d["counts"]["errors"] == 1
    assert d["findings"][0]["check"] == "a"
