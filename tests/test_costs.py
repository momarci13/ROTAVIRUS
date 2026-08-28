"""Cost module: deflation correctness + hard-fail on missing required parameters."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pandas as pd
import pytest

from scraper import CONFIG_DIR
from scraper.core.config import load_config
from scraper.core.errors import MissingParameterError
from scraper.costs.deflate import DeflatorSet, deflate_value
from scraper.costs.parameters import ParameterBook, resolve_all

# --------------------------------------------------------------------------- #
# a fully-filled config directory
# --------------------------------------------------------------------------- #

FILLED_COST_YAML = textwrap.dedent(
    """
    meta:
      base_price_year: 2025
      currency: HUF
    deflators:
      - id: health_cpi
        description: test
        base_year: 2025
        series: {2019: 100.0, 2024: 130.0, 2025: 140.0}
      - id: earnings_index
        description: test
        base_year: 2025
        series: {2019: 100.0, 2024: 160.0, 2025: 175.0}
      - id: headline_cpi
        description: test
        base_year: 2025
        series: {2019: 100.0, 2024: 145.0, 2025: 155.0}
    parameters:
      - id: hbcs_base_rate
        required: true
        unit: huf_per_weight
        values: [{year: 2025, value_huf_nominal: 300000, price_year: 2025, evidence_class: observed, confidence: high}]
      - id: outpatient_point_value
        required: true
        unit: huf_per_point
        values: [{year: 2025, value_huf_nominal: 2.5, price_year: 2025, evidence_class: observed, confidence: high}]
      - id: hbcs_weight_paed_gastroenteritis
        required: true
        unit: weight
        values: [{year: 2025, weight: 0.65, price_year: 2025, evidence_class: observed, confidence: high}]
      - id: outpatient_points_per_case
        required: false
        unit: point
        values: [{year: 2025, points: 1200, price_year: 2025, evidence_class: estimated, confidence: medium}]
      - id: gp_visit_cost
        required: false
        unit: huf
        values: [{year: 2025, value_huf_nominal: 4000, price_year: 2025, evidence_class: estimated, confidence: low}]
      - id: hospitalisation_rate_u5
        required: true
        unit: ratio
        values: [{year: 2025, ratio: 0.20, evidence_class: assumed, confidence: low, source_citation: test, source_url: http://x, source_year: 2020}]
      - id: underreporting_multiplier
        required: true
        unit: multiplier
        values: [{year: 2025, multiplier: 10.0, evidence_class: assumed, confidence: low, source_citation: test, source_url: http://x, source_year: 2020}]
      - id: parental_work_loss_probability
        required: true
        unit: probability
        values: [{year: 2025, probability: 0.8, evidence_class: assumed, confidence: low, source_citation: test, source_url: http://x, source_year: 2020}]
      - id: mean_illness_duration_days
        required: true
        unit: days
        values: [{year: 2025, days: 4.0, evidence_class: assumed, confidence: low, source_citation: test, source_url: http://x, source_year: 2020}]
      - id: daily_gross_wage
        required: true
        unit: huf_per_day
        values: [{year: 2024, value_huf_nominal: 20000, price_year: 2024, evidence_class: observed, confidence: high}]
      - id: employer_contribution_rate
        required: true
        unit: rate
        values: [{year: 2025, rate: 0.13, evidence_class: observed, confidence: high}]
      - id: working_days_per_year
        required: true
        unit: days
        values: [{year: 2024, days: 251, evidence_class: observed, confidence: high}]
      - id: vaccine_course_price
        required: true
        unit: huf
        values: [{year: 2025, value_huf_nominal: 30000, price_year: 2025, evidence_class: observed, confidence: medium}]
      - id: vaccine_administration_cost
        required: false
        unit: huf
        values: [{year: 2025, value_huf_nominal: 2000, price_year: 2025, evidence_class: estimated, confidence: low}]
      - id: vaccine_efficacy
        required: false
        unit: ratio
        values: [{year: 2025, ratio: 0.85, evidence_class: assumed, confidence: low, source_citation: test, source_url: http://x, source_year: 2020}]
    """
)


@pytest.fixture
def filled_config(tmp_path: Path):
    cfg_dir = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, cfg_dir)
    (cfg_dir / "cost_parameters.yaml").write_text(FILLED_COST_YAML, encoding="utf-8")
    return load_config(cfg_dir)


# --------------------------------------------------------------------------- #
# deflation
# --------------------------------------------------------------------------- #


def test_deflator_factor_is_base_over_year(filled_config):
    ds = DeflatorSet(filled_config)
    d = ds.for_class("medical_costs")  # -> health_cpi
    assert d.factor(2025) == pytest.approx(1.0)
    assert d.factor(2019) == pytest.approx(140.0 / 100.0)
    assert d.factor(2024) == pytest.approx(140.0 / 130.0)


def test_deflate_value_uses_right_index_per_class(filled_config):
    real_med, did_med, base = deflate_value(filled_config, 1000.0, from_year=2019, cost_class="medical_costs")
    real_prod, did_prod, _ = deflate_value(filled_config, 1000.0, from_year=2019, cost_class="productivity_costs")
    assert base == 2025
    assert did_med == "health_cpi" and real_med == pytest.approx(1400.0)
    assert did_prod == "earnings_index" and real_prod == pytest.approx(1750.0)


def test_deflate_same_year_is_identity(filled_config):
    real, _, _ = deflate_value(filled_config, 555.0, from_year=2025, cost_class="medical_costs")
    assert real == pytest.approx(555.0)


# --------------------------------------------------------------------------- #
# missing required parameter -> informative exception, never a default
# --------------------------------------------------------------------------- #


def test_missing_required_parameter_raises_informative(config):
    # the shipped config/cost_parameters.yaml has nulls on purpose
    with pytest.raises(MissingParameterError) as ei:
        resolve_all(config, year=2025, strict=True)
    msg = str(ei.value)
    assert "hbcs_base_rate" in msg
    assert "no default" in msg.lower()
    # source URL surfaced so the researcher knows where to look
    assert "neak.gov.hu" in msg


def test_non_strict_returns_missing_flags(config):
    resolved = resolve_all(config, year=2025, strict=False)
    by_id = {r.parameter_id: r for r in resolved}
    assert by_id["hbcs_base_rate"].missing is True
    assert by_id["hbcs_base_rate"].value is None  # NOT defaulted to a number


def test_parameter_book_get_raises_for_unset(config):
    book = ParameterBook(resolve_all(config, year=2025, strict=False))
    with pytest.raises(MissingParameterError):
        book.get("underreporting_multiplier")


# --------------------------------------------------------------------------- #
# cost model end-to-end on the filled config
# --------------------------------------------------------------------------- #


def test_unit_costs_and_panel_costs(filled_config):
    from scraper.costs.cost_model import expected_cost_panel, unit_costs

    uc = unit_costs(filled_config, year=2025)
    assert uc.c_inpatient_nominal == pytest.approx(0.65 * 300000)
    assert uc.c_outpatient_nominal == pytest.approx(1200 * 2.5)

    panel = pd.DataFrame(
        {
            "district_id": ["0101", "0102"],
            "rotavirus_cases_district_modelled": [100.0, 0.0],
            "births": [500.0, 300.0],
        }
    )
    out = expected_cost_panel(filled_config, panel, year=2025)
    for col in (
        "cost_per_case_huf_nominal",
        "cost_per_case_huf_real_2025",
        "expected_total_cost_huf_nominal",
        "expected_total_cost_huf_real_2025",
        "vaccination_cost_huf_nominal",
        "productivity_cost_huf_real_2025",
        "price_year",
    ):
        assert col in out.columns
    # real == nominal * health_cpi factor for the base price year 2025 -> factor 1
    assert out["cost_per_case_huf_real_2025"].iloc[0] == pytest.approx(
        out["cost_per_case_huf_nominal"].iloc[0]
    )
    # vaccination cost = births * (30000 + 2000)
    assert out["vaccination_cost_huf_nominal"].iloc[0] == pytest.approx(500 * 32000)
    assert (out["expected_total_cost_huf_real_2025"] >= 0).all()
