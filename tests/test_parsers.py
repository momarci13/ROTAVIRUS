"""Parser tests against real (small) NNGYK sample PDFs."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scraper.collectors.nngyk import NNGYKCollector, parse_cell
from scraper.parsers.pdf_tables import extract_tables

FIX = Path("tests/fixtures/nngyk")
WEEKLY = FIX / "weekly_2024_07_p2-3.pdf"

pytestmark = pytest.mark.skipif(not WEEKLY.exists(), reason="NNGYK sample fixture missing")


@pytest.fixture
def collector(config):
    return NNGYKCollector(config, http=None)


@pytest.fixture
def weekly_pdf(tmp_path: Path) -> Path:
    dst = tmp_path / "weekly_2024_07.pdf"
    shutil.copyfile(WEEKLY, dst)
    return dst


# --------------------------------------------------------------------------- #
# number parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-", 0),
        ("–", 0),
        ("", None),
        ("●", None),
        ("12", 12),
        ("1 233", 1233),
        (" 8 ", 8),
        ("n.a.", None),
    ],
)
def test_parse_cell(raw, expected):
    assert parse_cell(raw) == expected


# --------------------------------------------------------------------------- #
# disease-name dictionary
# --------------------------------------------------------------------------- #


def test_disease_alias_lookup_handles_spelling_variants(config):
    lut = config.disease_names.alias_lookup()
    for variant in [
        "rotavírus-gastroenteritis",
        "rotavírus gastroenteritis",
        "rotavirus-gastroenteritis",
        "rotavírus gastro-enteritis",
    ]:
        assert lut[variant] == "rotavirus_gastroenteritis"
    assert lut["enteritis infectiosa"] == "enteritis_infectiosa"


def test_county_table_rows_are_twenty(config):
    assert len(config.disease_names.county_table_rows) == 20


# --------------------------------------------------------------------------- #
# weekly county table extraction
# --------------------------------------------------------------------------- #


def test_weekly_pdf_yields_20_county_rows_with_rotavirus(collector, weekly_pdf):
    df = collector._parse_weekly(weekly_pdf)
    assert len(df) == 20
    assert set(df["geo_level"]) == {"county"}
    assert set(df["variable"]) == {"rotavirus_cases"}
    assert set(df["evidence_class"]) == {"observed"}
    # canonical (non-abbreviated) county names
    assert "Borsod-Abaúj-Zemplén" in set(df["geo_name"])
    assert "Szabolcs-Szatmár-Bereg" in set(df["geo_name"])
    assert (df["value"] >= 0).all()


def test_weekly_pdf_sum_check_passes(collector, weekly_pdf):
    # 2024 wk07: county rows sum == national current-week value == 182
    df = collector._parse_weekly(weekly_pdf)
    assert int(df["value"].sum()) == 182
    assert collector._national_current_week_rotavirus(weekly_pdf) == 182


def test_structure_check_rejects_wrong_table(collector, weekly_pdf):
    # page 2 (national disease list) must NOT pass the county structure check
    cands = extract_tables(weekly_pdf, structure_check=collector._county_structure_check)
    passing = [c for c in cands if c.structure_ok]
    assert passing, "expected at least one page to pass"
    assert all(c.checks.get("county_row_hits", 0) >= 18 for c in passing)


def test_weekly_pre_2014_is_archived_not_emitted(collector, tmp_path):
    # a file dated before the surveillance break yields no rows and writes the
    # surveillance_breaks.json marker
    fake = tmp_path / "weekly_2011_07.pdf"
    shutil.copyfile(WEEKLY, fake)
    df = collector._parse_weekly(fake)
    assert df.empty
    from scraper.collectors.nngyk import SURVEILLANCE_BREAKS

    assert SURVEILLANCE_BREAKS.exists()


def test_weekly_validate_flags_district_and_pre_break(collector, weekly_pdf):
    df = collector._parse_weekly(weekly_pdf)
    rep = collector.validate(df)
    assert rep.ok

    bad = df.copy()
    bad.loc[bad.index[0], "geo_level"] = "district"
    rep2 = collector.validate(bad)
    assert not rep2.ok
    assert any("district-level observed rotavirus" in e for e in rep2.errors)
