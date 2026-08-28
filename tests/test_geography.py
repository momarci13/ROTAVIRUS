"""Geography registry: internal consistency, KTE partition, interval validity."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scraper.geography.build_registry import (
    build_registry,
    check_consistency,
    parse_canonical_csv,
    parse_tszj_workbook,
    write_registry,
)
from scraper.geography.crosswalk import Crosswalk, normalise_name
from scraper.geography.harmonise import (
    HarmonisationLog,
    apportion_extensive,
    apportion_intensive,
    build_kte_partition,
    harmonise_frame,
)

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


def test_crosswalk_fuzzy_goes_to_pending_not_panel(built, config, tmp_path, monkeypatch):
    from scraper.geography import crosswalk as cw

    monkeypatch.setattr(cw, "MANUAL_CSV", tmp_path / "cwm.csv")
    xw = Crosswalk(built.settlements, built.districts, config)
    # near-miss spelling of "Miskolc"
    r = xw.match("Miskolcz", kind="name", source_id="test")
    assert r.status == "pending"
    assert r.method in {"fuzzy", "none"}
    assert (tmp_path / "cwm.csv").exists()


def test_crosswalk_match_frame_keeps_unmatched_rows(built, config, tmp_path, monkeypatch):
    from scraper.geography import crosswalk as cw

    monkeypatch.setattr(cw, "MANUAL_CSV", tmp_path / "cwm2.csv")
    xw = Crosswalk(built.settlements, built.districts, config)
    df = pd.DataFrame({"name": ["Encs", "Ismeretlen Hely"]})
    out = xw.match_frame(df, column="name", kind="name", source_id="okfo")
    assert len(out) == 2  # nothing dropped
    assert out.loc[0, "district_id"] == "0512"
    assert pd.isna(out.loc[1, "district_id"])
    assert set(out["crosswalk_status"]) <= {"confirmed", "pending"}


# --------------------------------------------------------------------------- #
# harmonise
# --------------------------------------------------------------------------- #


def test_apportion_intensive_numerator_denominator_split():
    num = {"S1": 20.0}
    den = {"S1": 100.0}
    pop = {"s1": 40.0, "s2": 60.0}
    src = {"s1": "S1", "s2": "S1"}
    tgt = {"s1": "T1", "s2": "T2"}
    out = apportion_intensive(num, den, pop, src, tgt, variable="rate")
    # rate preserved at 0.2 in both targets (uniform split of num and den)
    assert out["T1"] == pytest.approx(0.2)
    assert out["T2"] == pytest.approx(0.2)


def test_harmonise_frame_extensive_and_intensive():
    src_frame = pd.DataFrame({"unit_id": ["S1", "S2"], "cases": [100.0, 40.0], "rate": [0.1, 0.2]})
    pop = {"a": 30.0, "b": 70.0, "c": 40.0}
    src = {"a": "S1", "b": "S1", "c": "S2"}
    tgt = {"a": "T1", "b": "T2", "c": "T2"}
    hlog = HarmonisationLog()
    out = harmonise_frame(
        src_frame,
        value_columns=["cases", "rate"],
        extensive_flags={"cases": True, "rate": False},
        settlement_pop=pop,
        settlement_source=src,
        settlement_target=tgt,
        hlog=hlog,
    )
    assert set(out["unit_id"]) == {"T1", "T2"}
    assert out.set_index("unit_id").loc["T1", "cases"] == pytest.approx(30.0)
    assert out["cases"].sum() == pytest.approx(140.0)
    assert len(hlog.entries) > 0


def test_harmonisation_log_flush(tmp_path):
    hlog = HarmonisationLog()
    hlog.add("x", "test_method", detail=1)
    p = hlog.flush(tmp_path / "hlog.json")
    assert p.exists()
    import json

    assert json.loads(p.read_text())["entries"][0]["variable"] == "x"


# --------------------------------------------------------------------------- #
# build_registry parsing + writing
# --------------------------------------------------------------------------- #


def test_parse_canonical_csv_zero_pads(tmp_path):
    p = tmp_path / "registry_2020.csv"
    p.write_text(
        "settlement_id,settlement_name,district_id,county_id\n"
        "5,Egy,101,1\n"
        "12345,Ketto,0511,05\n",
        encoding="utf-8",
    )
    df = parse_canonical_csv(p)
    assert list(df["settlement_id"]) == ["00005", "12345"]


def test_parse_tszj_workbook_heuristic(tmp_path):
    xlsx = tmp_path / "tszj_2021_megnevezesekkel.xlsx"
    pd.DataFrame(
        {
            "Település törzsszáma": ["10001", "10002"],
            "Település megnevezése": ["A", "B"],
            "Járás kódja": ["0101", "0101"],
            "Megye kódja": ["01", "01"],
            "Megye megnevezése": ["Budapest", "Budapest"],
        }
    ).to_excel(xlsx, index=False)
    out = parse_tszj_workbook(xlsx)
    assert list(out["settlement_id"]) == ["10001", "10002"]
    assert set(out["district_id"]) == {"0101"}


def test_write_registry_emits_parquets(built, tmp_path, monkeypatch):
    from scraper.geography import build_registry as br

    monkeypatch.setattr(br, "DISTRICTS_OUT", tmp_path / "d.parquet")
    monkeypatch.setattr(br, "SETTLEMENTS_OUT", tmp_path / "s.parquet")
    monkeypatch.setattr(br, "BOUNDARY_CHANGES_OUT", tmp_path / "bc.json")
    write_registry(built)
    assert (tmp_path / "d.parquet").exists()
    assert (tmp_path / "s.parquet").exists()
    assert (tmp_path / "bc.json").exists()


def test_check_consistency_flags_orphan_settlement():
    frame = pd.DataFrame(
        {
            "settlement_id": ["10001", "10002"],
            "settlement_name": ["A", "B"],
            "district_id": ["0101", ""],
            "county_id": ["01", "01"],
            "postal_codes": ["", ""],
        }
    )
    errs = check_consistency(frame, county_count_expected=1)
    assert any("no district_id" in e for e in errs)
