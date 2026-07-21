"""Fixtures only. Shared helper functions live in tests/helpers.py."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "project"
