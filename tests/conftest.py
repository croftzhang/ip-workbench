"""Shared fixtures. Tests run against the repository's own config/ and data/."""

from pathlib import Path

import pytest

from ipw import Workbench

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def wb() -> Workbench:
    return Workbench.load(ROOT)
