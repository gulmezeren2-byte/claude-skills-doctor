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
    assert "Skill listing budget" in result.stdout
    # the report must say whether the number is measured or derived
    assert "budget from" in result.stdout


def test_error_exits_nonzero(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: mismatch\ndescription: {GOOD}")
    result = runner.invoke(app, _args(home, project))
    assert result.exit_code == 1


def test_json_output(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    result = runner.invoke(app, _args(home, project, "--json"))
    data = json.loads(result.stdout)
    assert data["counts"]["skills"] == 1
    # 1% of a 200k-token context window at ~4 chars/token — not a fixed 15,000
    assert data["budget"]["limit"] == 8000
    assert data["budget"]["exact"] is False
    assert data["budget"]["per_entry_cap"] == 1536
    assert data["ok"] is True


def test_strict_fails_on_warning(home: Path, project: Path) -> None:
    # a too-short description is a warning; --strict turns it into a failure
    write_skill(project, "pdf", "name: pdf\ndescription: thin")
    assert runner.invoke(app, _args(home, project)).exit_code == 0
    assert runner.invoke(app, _args(home, project, "--strict")).exit_code == 1


def test_our_own_shipped_skill_passes_our_own_checks(tmp_path: Path) -> None:
    """Dogfood, enforced: the skill this project ships must survive --strict.

    If we ship a skill that our own tool flags, the tool is not credible. This runs
    against the real `skills/` folder in the repo, so it fails the build if that
    ever stops being true."""
    shipped = Path(__file__).resolve().parents[1] / "skills"
    assert shipped.is_dir(), "the repo should ship a skills/ folder"
    result = runner.invoke(
        app,
        [
            "--home", str(tmp_path / "nohome"),
            "--project", str(tmp_path / "noproject"),
            "--skills", str(shipped),
            "--strict",
        ],
    )
    assert result.exit_code == 0, result.stdout


def test_skills_flag_is_repeatable(tmp_path: Path) -> None:
    for name in ("one", "two"):
        d = tmp_path / name / "s"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: s\ndescription: {GOOD}\n---\nbody", "utf-8")
    result = runner.invoke(
        app,
        ["--home", str(tmp_path / "nohome"), "--project", str(tmp_path / "nope"),
         "--skills", str(tmp_path / "one"), "--skills", str(tmp_path / "two"), "--json"],
    )
    data = json.loads(result.stdout)
    assert data["counts"]["skills"] == 2
    # two skills both named `s` — the duplicate must be caught
    assert "duplicate-name" in {f["check"] for f in data["findings"]}


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "skilldoctor" in result.stdout


def test_budget_subcommand(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    result = runner.invoke(app, ["budget", "--home", str(home), "--project", str(project)])
    assert result.exit_code == 0
    assert "Skill listing budget" in result.stdout
    # the report must say whether the number is measured or derived
    assert "budget from" in result.stdout


def test_budget_override(home: Path, project: Path) -> None:
    write_skill(project, "pdf", f"name: pdf\ndescription: {GOOD}")
    # a tiny budget forces "over budget" → the budget command exits 1
    args = ["budget", "--home", str(home), "--project", str(project), "--budget", "5"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
