"""Geography registry: internal consistency, KTE partition, interval validity."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scraper.geography.build_registry import build_registry, check_consistency
from scraper.geography.crosswalk import Crosswalk, normalise_name
from scraper.geography.harmonise import apportion_extensive, build_kte_partition

FIX = "tests/fixtures/geography"


@pytest.fixture
def built(geo_config):
    return build_registry(geo_config, registry_dir=__import__("pathlib").Path(FIX))


# --------------------------------------------------------------------------- #
# internal consistency
# --------------------------------------------------------------------------- #


def test_every_settlement_in_exactly_one_district_per_year(built):
    # settlements frame: no settlement_id has overlapping validity intervals
    s = built.settlements
    for sid, grp in s.groupby("settlement_id"):
        spans = sorted(
            (r.valid_from, r.valid_to or date(9999, 1, 1)) for r in grp.itertuples()
        )
        for (a_start, a_end), (b_start, _b_end) in zip(spans, spans[1:]):
            assert a_end <= b_start, f"overlapping intervals for settlement {sid}"


def test_every_district_in_exactly_one_county(built):
    d = built.districts
    per_district_counties = d.groupby("district_id")["county_id"].nunique()
    assert (per_district_counties == 1).all()


def test_consistency_checker_flags_multi_county_district():
    frame = pd.DataFrame(
        {
            "settlement_id": ["10001", "10002"],
            "settlement_name": ["A", "B"],
            "district_id": ["0101", "0101"],
            "county_id": ["01", "02"],  # same district, two counties -> error
            "postal_codes": ["", ""],
        }
    )
    errs = check_consistency(frame, county_count_expected=2)
    assert any("multiple counties" in e for e in errs)


def test_consistency_checker_flags_duplicate_settlement():
    frame = pd.DataFrame(
        {
            "settlement_id": ["10001", "10001"],
            "settlement_name": ["A", "A"],
            "district_id": ["0101", "0102"],
            "county_id": ["01", "01"],
            "postal_codes": ["", ""],
        }
    )
    errs = check_consistency(frame, county_count_expected=1)
    assert any("more than one row" in e for e in errs)


# --------------------------------------------------------------------------- #
# boundary change / KTE
# --------------------------------------------------------------------------- #


def test_boundary_change_detected(built):
    changes = built.boundary_changes
    moved = [c for c in changes if c["type"] == "settlement_reassigned"]
    assert len(moved) == 1
    assert moved[0]["settlement_id"] == "20003"
    assert moved[0]["from_district"] == "0511"
    assert moved[0]["to_district"] == "0512"
    assert moved[0]["year"] == 2014


def test_kte_partition_on_synthetic_change():
    year_maps = {
        2013: {"a": "D1", "b": "D1", "c": "D1", "d": "D2"},
        2014: {"a": "D1", "b": "D1", "c": "D2", "d": "D2"},  # c moved
    }
    kte = build_kte_partition(year_maps)
    # a and b are always together -> same KTE
    assert kte["a"] == kte["b"]
    # c changed district -> its own KTE, distinct from both a/b and d
    assert kte["c"] != kte["a"]
    assert kte["c"] != kte["d"]
    # exactly 3 KTE units: {a,b}, {c}, {d}
    assert len(set(kte.values())) == 3


def test_interval_valid_to_set_on_change(built):
    s = built.settlements
    onga = s[s["settlement_id"] == "20003"].sort_values("valid_from")
    assert len(onga) == 2
    assert onga.iloc[0]["valid_to"] == date(2014, 1, 1)
    assert onga.iloc[0]["district_id"] == "0511"
    assert onga.iloc[1]["district_id"] == "0512"
    assert onga.iloc[1]["valid_to"] is None


# --------------------------------------------------------------------------- #
# apportionment
# --------------------------------------------------------------------------- #


def test_apportion_extensive_conserves_mass():
    # source unit S1 -> split into T1, T2 by population
    source_values = {"S1": 100.0}
    pop = {"s1": 30.0, "s2": 70.0}
    src = {"s1": "S1", "s2": "S1"}
    tgt = {"s1": "T1", "s2": "T2"}
    out = apportion_extensive(source_values, pop, src, tgt, variable="cases")
    assert out["T1"] == pytest.approx(30.0)
    assert out["T2"] == pytest.approx(70.0)
    assert sum(out.values()) == pytest.approx(100.0)


# --------------------------------------------------------------------------- #
# crosswalk
# --------------------------------------------------------------------------- #


def test_normalise_name_drops_tokens(config):
    assert normalise_name("Forró község", config) == "forró"


def test_crosswalk_exact_and_postal(built, config, tmp_path, monkeypatch):
    # isolate the manual-review csv so the test never writes into config/
    from scraper.geography import crosswalk as cw

    monkeypatch.setattr(cw, "MANUAL_CSV", tmp_path / "crosswalk_manual.csv")
    xw = Crosswalk(built.settlements, built.districts, config)

    r_name = xw.match("Miskolc", kind="name", source_id="test")
    assert r_name.district_id == "0511"
    assert r_name.method == "exact_name"

    r_post = xw.match("3860", kind="postal", source_id="test")
    assert r_post.district_id == "0512"
    assert r_post.method == "postal"

    r_none = xw.match("Nincs Ilyen Település", kind="name", source_id="test")
    assert r_none.district_id is None
    assert r_none.status == "pending"
    assert (tmp_path / "crosswalk_manual.csv").exists()  # unmatched row recorded, not dropped
