"""Allocation: budget constraint, scenario nesting, equity-metric properties."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scraper.allocation.equity import (
    concentration_index,
    gini,
    kakwani_index,
    lorenz_points,
)
from scraper.allocation.need_index import compute_need_index, standardise
from scraper.allocation.scenarios import (
    GenericParams,
    allocate_generic,
    run_all_scenarios,
    run_scenario,
)

BUDGET = 2_500_000_000.0


@pytest.fixture
def panel():
    rng = np.random.default_rng(20260101)
    n = 40
    df = pd.DataFrame(
        {
            "district_id": [f"{i:04d}" for i in range(n)],
            "district_name": [f"d{i}" for i in range(n)],
            "county_id": [f"{(i % 5) + 1:02d}" for i in range(n)],
            "population_0_4": rng.integers(300, 6000, n).astype(float),
            "population_total": rng.integers(15000, 300000, n).astype(float),
            "births": rng.integers(50, 800, n).astype(float),
            "rotavirus_cases_district_modelled": rng.gamma(3, 8, n),
            "expected_cases_per_1000_u5_modelled": rng.gamma(2, 5, n),
            "expected_total_cost_huf_real_2025": rng.gamma(3, 4_000_000, n),
            "jobseeker_rate": rng.uniform(0.02, 0.25, n),
            "pit_income_per_capita": rng.uniform(500_000, 2_000_000, n),
            "low_education_ratio": rng.uniform(0.05, 0.4, n),
            "komplex_mutato_inverse": rng.uniform(0, 1, n),
            "vacant_paediatric_practice_ratio": rng.uniform(0, 0.5, n),
            "travel_time_to_paed_hospital": rng.uniform(5, 90, n),
            "paed_beds_per_1000_u5_inverse": rng.uniform(0, 1, n),
            "municipal_own_revenue_per_capita": rng.uniform(20_000, 250_000, n),
            "existing_local_funding": rng.integers(0, 5_000_000, n).astype(float),
            "kedvezmenyezett_status": rng.integers(0, 2, n).astype(bool),
        }
    )
    return df


# --------------------------------------------------------------------------- #
# need index
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["zscore", "minmax", "rank"])
def test_standardise_methods(method):
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 100.0])
    z = standardise(s, method)
    assert len(z) == len(s)
    assert np.isfinite(z).all()


@pytest.mark.parametrize("agg", ["weighted_sum", "mpi", "pca", "entropy"])
def test_need_index_aggregations(panel, config, agg):
    config.need_index.aggregation = agg
    nf = compute_need_index(panel, config.need_index)
    assert list(nf["district_id"]) == list(panel["district_id"])
    assert nf["need_score"].between(0, 1).all()
    assert np.isfinite(nf["need_score"]).all()
    for dim in config.need_index.dimensions:
        assert f"need_{dim}" in nf.columns


# --------------------------------------------------------------------------- #
# budget constraint
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sid", [1, 2, 3, 4, 5, 7])
def test_budget_constraint_respected(panel, config, sid):
    out = run_scenario(config, panel, sid, budget=BUDGET)
    assert out["aid_amount_huf"].sum() == pytest.approx(BUDGET, rel=1e-9, abs=1e-3)
    assert (out["aid_amount_huf"] >= -1e-6).all()


def test_scenario0_is_passthrough_not_normalised(panel, config):
    out = run_scenario(config, panel, 0, budget=BUDGET)
    assert out["aid_amount_huf"].sum() == pytest.approx(panel["existing_local_funding"].sum())


def test_scenario6_cost_gap_reports_true_cost_not_budget(panel, config):
    out = run_scenario(config, panel, 6, budget=BUDGET)
    # not normalised -> total is the summed positive gap, generally != budget
    assert out["aid_amount_huf"].sum() != pytest.approx(BUDGET)
    assert (out["aid_amount_huf"] >= 0).all()


def test_scenario7_only_funds_eligible_districts(panel, config):
    out = run_scenario(config, panel, 7, budget=BUDGET).set_index("district_id")
    ineligible = panel.loc[~panel["kedvezmenyezett_status"], "district_id"]
    assert (out.loc[ineligible, "aid_amount_huf"] == 0).all()
    assert out["aid_amount_huf"].sum() == pytest.approx(BUDGET, abs=1e-3)


# --------------------------------------------------------------------------- #
# scenario nesting: scenario 2 == generic(5) with eta=kappa=0, L=0, cost=Lambda
# --------------------------------------------------------------------------- #


def test_scenario2_is_special_case_of_generic5(panel):
    idx = panel.index
    lam = pd.to_numeric(panel["expected_cases_per_1000_u5_modelled"])

    # scenario 2 form: aid ∝ Lambda
    p2 = GenericParams(budget=BUDGET, cost=lam, eta=0.0, kappa=0.0, normalise_to_budget=True)
    aid2 = allocate_generic(idx, p2)

    # scenario 5 form collapsed: cost=Lambda, need term off, no fiscal penalty,
    # no existing subtraction
    p5 = GenericParams(
        budget=BUDGET,
        cost=lam,
        need=pd.Series(np.zeros(len(idx)), index=idx),
        eta=0.0,
        kappa=0.0,
        fiscal_penalty=False,
        subtract_existing=False,
        normalise_to_budget=True,
    )
    aid5 = allocate_generic(idx, p5)

    assert np.allclose(aid2.to_numpy(), aid5.to_numpy())
    assert aid2.sum() == pytest.approx(BUDGET, abs=1e-3)


def test_equal_cost_gives_per_capita_when_base_is_pop(panel):
    idx = panel.index
    pop = pd.to_numeric(panel["population_0_4"])
    p = GenericParams(budget=BUDGET, per_capita=pop, eta=0.0, normalise_to_budget=True)
    aid = allocate_generic(idx, p)
    expected = BUDGET * pop / pop.sum()
    assert np.allclose(aid.to_numpy(), expected.to_numpy())


# --------------------------------------------------------------------------- #
# equity metrics
# --------------------------------------------------------------------------- #


def test_concentration_index_zero_for_uniform_allocation():
    n = 50
    aid = pd.Series(np.full(n, 100.0))
    need = pd.Series(np.linspace(0, 1, n))
    assert abs(concentration_index(aid, need)) < 1e-9


def test_concentration_index_positive_when_aid_tracks_need():
    need = pd.Series(np.linspace(0, 1, 50))
    aid = need * 1000 + 1
    assert concentration_index(aid, need) > 0.2


def test_gini_zero_for_equal_distribution():
    assert gini(np.full(30, 5.0)) == pytest.approx(0.0, abs=1e-9)
    assert gini(np.array([0, 0, 0, 100.0])) > 0.5


def test_lorenz_curve_is_monotone_nondecreasing():
    x = np.random.default_rng(1).gamma(2, 3, 100)
    p, curve = lorenz_points(x)
    assert np.all(np.diff(curve) >= -1e-12)
    assert curve[0] == pytest.approx(0.0)
    assert curve[-1] == pytest.approx(1.0)
    assert p[0] == 0.0 and p[-1] == pytest.approx(1.0)


def test_kakwani_positive_when_allocation_more_concentrated_than_need():
    need = pd.Series(np.linspace(0.1, 1.0, 40))
    aid = need**3
    assert kakwani_index(aid, need) > 0


# --------------------------------------------------------------------------- #
# run_all_scenarios integration
# --------------------------------------------------------------------------- #


def test_run_all_scenarios_shape_and_delta(panel, config):
    allf = run_all_scenarios(config, panel, budget=BUDGET)
    assert set(allf["scenario_id"]) == {s.id for s in config.scenarios.scenarios}
    assert "delta_vs_baseline" in allf.columns
    # every normalised scenario keeps to budget
    for sid, grp in allf.groupby("scenario_id"):
        scen = config.scenarios.by_id(int(sid))
        if scen.normalise_to_budget:
            assert grp["aid_amount_huf"].sum() == pytest.approx(BUDGET, abs=1e-2)
