"""End-to-end CLI tests via Typer's runner, against an isolated tmp home/project."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from skilldoctor.cli import app
from tests.helpers import write_skill

runner = CliRunner()
GOOD = "Parse a birim fiyat catalog PDF into structured rows for downstream use."


def _args(home: Path, project: Path, *extra: str) -> list[str]:
    return ["--home", str(home), "--project", str(project), *extra]


def test_clean_exits_zero(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    result = runner.invoke(app, _args(home, project))
    assert result.exit_code == 0
    assert "Discovery budget" in result.stdout


def test_error_exits_nonzero(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: mismatch\ndescription: {GOOD}")
    result = runner.invoke(app, _args(home, project))
    assert result.exit_code == 1


def test_json_output(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    result = runner.invoke(app, _args(home, project, "--json"))
    data = json.loads(result.stdout)
    assert data["counts"]["skills"] == 1
    assert data["budget"]["limit"] == 15000
    assert data["ok"] is True


def test_strict_fails_on_warning(home: Path, project: Path) -> None:
    # a too-short description is a warning; --strict turns it into a failure
    write_skill(project, "pdf", "name: pdf\ndescription: thin")
    assert runner.invoke(app, _args(home, project)).exit_code == 0
    assert runner.invoke(app, _args(home, project, "--strict")).exit_code == 1


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "skilldoctor" in result.stdout


def test_budget_subcommand(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    result = runner.invoke(app, ["budget", "--home", str(home), "--project", str(project)])
    assert result.exit_code == 0
    assert "Discovery budget" in result.stdout


def test_budget_override(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    # a tiny budget forces "over budget" → the budget command exits 1
    args = ["budget", "--home", str(home), "--project", str(project), "--budget", "5"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
