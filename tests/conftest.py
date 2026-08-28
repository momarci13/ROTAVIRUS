"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper.core.config import load_config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def config():
    """The real project configuration (config/*.yaml)."""
    return load_config()


@pytest.fixture
def geo_config(config):
    """Project config with the county count relaxed for the tiny geo fixtures."""
    config.geography.canonical["county_count_expected"] = 2
    return config
