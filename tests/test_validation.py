"""Positive + negative cases for every validation rule (spec §8, rules 1-12)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from scraper.validation import checks as C
from scraper.validation.checks import ValidationContext, run_all
from scraper.validation.schemas import county_weekly_epi_schema, validate_schema


def _epi(**over):
    base = dict(
        geo_level="county",
        geo_name="Baranya",
        variable="rotavirus_cases",
        value=5.0,
        iso_year=2024,
        iso_week=7,
        period_start=date(2024, 2, 12),
        evidence_class="observed",
        source_id="nngyk",
    )
    base.update(over)
    return base


def ctx(rows, **kw):
    return ValidationContext(df=pd.DataFrame(rows), **kw)


# --------------------------------------------------------------------------- 1
def test_duplicates_positive():
    rows = [_epi(), _epi()]  # identical key
    found = C.check_duplicates(ctx(rows))
    assert found and found[0].severity == "error"


def test_duplicates_negative():
    rows = [_epi(geo_name="Baranya"), _epi(geo_name="Zala")]
    assert C.check_duplicates(ctx(rows)) == []


# --------------------------------------------------------------------------- 2/3
def test_valid_ids_positive():
    reg = pd.DataFrame({"county_id": ["01", "02"]})
    rows = [_epi(county_id="99")]
    found = C.check_valid_ids(ctx(rows, geo_counties=reg, resolution="county"))
    assert found and found[0].severity == "error"


def test_missing_units_positive():
    reg = pd.DataFrame({"county_id": ["01", "02", "03"]})
    rows = [_epi(county_id="01"), _epi(county_id="02", geo_name="X")]
    found = C.check_missing_units(ctx(rows, geo_counties=reg, resolution="county"))
    assert any(f.rule == "missing_units" for f in found)


# --------------------------------------------------------------------------- 4
def test_temporal_continuity_gap():
    rows = [_epi(iso_week=5), _epi(iso_week=9, geo_name="Z")]
    found = C.check_temporal_continuity(ctx(rows))
    assert found and "gap" in found[0].message.lower()


def test_temporal_continuity_no_gap():
    rows = [_epi(iso_week=5), _epi(iso_week=6, geo_name="Z"), _epi(iso_week=7, geo_name="Y")]
    assert C.check_temporal_continuity(ctx(rows)) == []


# --------------------------------------------------------------------------- 5
def test_ranges_negative_value():
    rows = [_epi(value=-3.0)]
    found = C.check_ranges(ctx(rows))
    assert found and found[0].severity == "error"


def test_ranges_ratio_out_of_bounds():
    df = pd.DataFrame({"jobseeker_rate": [0.2, 1.5]})
    found = C.check_ranges(ValidationContext(df=df))
    assert found and "jobseeker_rate" in found[0].message


# --------------------------------------------------------------------------- 6
def test_sum_agreement_mismatch():
    rows = [
        _epi(geo_level="county", geo_name="A", value=10.0),
        _epi(geo_level="county", geo_name="B", value=10.0),
        _epi(geo_level="country", geo_name="HU", value=25.0),
    ]
    found = C.check_sum_agreement(ctx(rows))
    assert found and found[0].severity == "error"


def test_sum_agreement_ok():
    rows = [
        _epi(geo_level="county", geo_name="A", value=10.0),
        _epi(geo_level="county", geo_name="B", value=15.0),
        _epi(geo_level="country", geo_name="HU", value=25.0),
    ]
    assert C.check_sum_agreement(ctx(rows)) == []


# --------------------------------------------------------------------------- 7
def test_outliers_flagged_not_deleted():
    rows = [_epi(value=float(v), geo_name=f"c{v}", iso_week=v) for v in range(1, 20)]
    rows.append(_epi(value=100000.0, geo_name="spike", iso_week=40))
    context = ctx(rows)
    n_before = len(context.df)
    found = C.check_outliers(context, threshold=5)
    assert found and found[0].severity == "flag"
    assert len(context.df) == n_before  # nothing deleted
    assert (context.df["quality_flag"] == "outlier").any()


# --------------------------------------------------------------------------- 8
def test_price_year_mix_error():
    df = pd.DataFrame(
        {
            "cost_per_case_huf_nominal": [100, 200],
            "price_year": [2019, 2024],
            "expected_total_cost_huf_real_2025": [110, 210],
        }
    )
    found = C.check_price_year_mix(ValidationContext(df=df))
    assert found and found[0].severity == "error"


def test_price_year_mix_ok_with_deflator():
    df = pd.DataFrame(
        {
            "cost_per_case_huf_nominal": [100, 200],
            "price_year": [2019, 2024],
            "expected_total_cost_huf_real_2025": [110, 210],
            "deflator_id": ["health_cpi", "health_cpi"],
        }
    )
    assert C.check_price_year_mix(ValidationContext(df=df)) == []


# --------------------------------------------------------------------------- 9
def test_evidence_class_district_observed_rotavirus_error():
    rows = [_epi(geo_level="district", variable="rotavirus_cases", evidence_class="observed", source_id="nngyk")]
    found = C.check_evidence_class(ctx(rows))
    assert found and found[0].severity == "error"


def test_evidence_class_foia_allowed():
    rows = [_epi(geo_level="district", variable="rotavirus_cases", evidence_class="observed", source_id="nngyk_foia")]
    assert C.check_evidence_class(ctx(rows)) == []


def test_evidence_class_modelled_allowed():
    rows = [_epi(geo_level="district", variable="rotavirus_cases_district_modelled", evidence_class="estimated", source_id="nngyk")]
    assert C.check_evidence_class(ctx(rows)) == []


# --------------------------------------------------------------------------- 10
def test_surveillance_break_error():
    rows = [_epi(period_start=date(2011, 2, 1))]
    found = C.check_surveillance_break(ctx(rows))
    assert found and found[0].severity == "error"


def test_surveillance_break_ok():
    rows = [_epi(period_start=date(2016, 2, 1))]
    assert C.check_surveillance_break(ctx(rows)) == []


# --------------------------------------------------------------------------- 11
def test_population_consistency_error():
    df = pd.DataFrame({"population_0_4": [500, 50], "population_total": [400, 1000]})
    found = C.check_population_consistency(ValidationContext(df=df))
    assert found and found[0].severity == "error"


def test_population_consistency_ok():
    df = pd.DataFrame({"population_0_4": [30, 50], "population_total": [400, 1000]})
    assert C.check_population_consistency(ValidationContext(df=df)) == []


# --------------------------------------------------------------------------- 12
def test_schema_drift_detected(tmp_path, monkeypatch):
    from scraper.validation import drift as D

    monkeypatch.setattr(D, "SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(D, "DRIFT_MD", tmp_path / "SCHEMA_DRIFT_REPORT.md")
    df1 = pd.DataFrame({"a": [1], "b": [2]})
    r1 = D.check_and_update("demo", df1)
    assert r1.first_seen and not r1.changed
    df2 = pd.DataFrame({"a": [1], "c": [3]})
    r2 = D.check_and_update("demo", df2)
    assert r2.changed and r2.added == ["c"] and r2.removed == ["b"]
    marked = D.mark_frame(df2.assign(quality_flag=""), r2)
    assert (marked["quality_flag"] == "schema_drift").all()


# --------------------------------------------------------------------------- orchestration + schema
def test_run_all_writes_report_and_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "VALIDATION_MD", tmp_path / "VALIDATION_REPORT.md")
    monkeypatch.setattr(C, "METADATA_DIR", tmp_path)
    rows = [_epi(period_start=date(2011, 1, 1))]  # triggers surveillance-break error
    with pytest.raises(Exception):
        run_all(ctx(rows), raise_on_error=True, label="unit")
    assert (tmp_path / "VALIDATION_REPORT.md").exists()


def test_pandera_schema_rejects_pre_break_and_negative():
    good = pd.DataFrame([_epi()])
    ok, errs = validate_schema(good, county_weekly_epi_schema)
    assert ok, errs

    bad = pd.DataFrame([_epi(value=-1.0)])
    ok2, _ = validate_schema(bad, county_weekly_epi_schema)
    assert not ok2
