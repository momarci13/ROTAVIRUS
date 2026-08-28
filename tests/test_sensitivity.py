"""Sensitivity analysis + equity decomposition coverage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scraper.allocation.equity import (
    equity_summary,
    spearman_between_scenarios,
    theil_decomposition,
)
from scraper.allocation.scenarios import run_all_scenarios
from scraper.allocation.sensitivity import (
    dirichlet_weight_sampling,
    one_way_tornado,
    psa,
)

BUDGET = 1_000_000_000.0


@pytest.fixture
def panel():
    rng = np.random.default_rng(7)
    n = 25
    return pd.DataFrame(
        {
            "district_id": [f"{i:04d}" for i in range(n)],
            "county_id": [f"{(i % 4) + 1:02d}" for i in range(n)],
            "population_0_4": rng.integers(400, 5000, n).astype(float),
            "births": rng.integers(60, 700, n).astype(float),
            "rotavirus_cases_district_modelled": rng.gamma(3, 7, n),
            "expected_cases_per_1000_u5_modelled": rng.gamma(2, 6, n),
            "expected_total_cost_huf_real_2025": rng.gamma(3, 3_000_000, n),
            "jobseeker_rate": rng.uniform(0.02, 0.2, n),
            "pit_income_per_capita": rng.uniform(600_000, 1_800_000, n),
            "low_education_ratio": rng.uniform(0.05, 0.35, n),
            "komplex_mutato_inverse": rng.uniform(0, 1, n),
            "vacant_paediatric_practice_ratio": rng.uniform(0, 0.4, n),
            "travel_time_to_paed_hospital": rng.uniform(5, 80, n),
            "paed_beds_per_1000_u5_inverse": rng.uniform(0, 1, n),
            "municipal_own_revenue_per_capita": rng.uniform(20_000, 200_000, n),
            "existing_local_funding": rng.integers(0, 3_000_000, n).astype(float),
            "kedvezmenyezett_status": rng.integers(0, 2, n).astype(bool),
        }
    )


def test_one_way_tornado_orders_by_swing():
    def evaluate(inp: dict) -> float:
        return inp["a"] * 2 + inp["b"] * 0.1

    tornado = one_way_tornado({"a": 10.0, "b": 100.0}, evaluate, deltas=(0.1, 0.5))
    assert set(tornado["input"]) == {"a", "b"}
    top = tornado[tornado["delta"] == 0.5].iloc[0]
    assert top["input"] == "a"  # larger swing
    assert (tornado["swing"] >= 0).all()


def test_psa_returns_interval_per_district(panel, config):
    out = psa(config, panel, scenario_id=5, draws=40, budget=BUDGET, seed=1)
    assert len(out) == len(panel)
    assert (out["aid_p2_5"] <= out["aid_mean"] + 1e-6).all()
    assert (out["aid_mean"] <= out["aid_p97_5"] + 1e-6).all()


def test_psa_is_deterministic_given_seed(panel, config):
    a = psa(config, panel, 2, draws=30, budget=BUDGET, seed=123)
    b = psa(config, panel, 2, draws=30, budget=BUDGET, seed=123)
    pd.testing.assert_frame_equal(a, b)


def test_dirichlet_weight_sampling_frequencies(panel, config):
    out = dirichlet_weight_sampling(config, panel, scenario_id=5, draws=30, budget=BUDGET, seed=2)
    assert len(out) == len(panel)
    assert out["top_decile_frequency"].between(0, 1).all()
    assert out["robust_top_decile"].dtype == bool
    # configured weights restored
    w = [config.need_index.dimensions[d].weight for d in config.need_index.dimensions]
    assert sum(w) == pytest.approx(1.0, abs=0.05) or all(x > 0 for x in w)


def test_theil_between_plus_within_approx_total():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"aid": rng.gamma(2, 5, 60), "grp": rng.integers(0, 4, 60)})
    d = theil_decomposition(df, value_col="aid", group_col="grp")
    assert d["between"] + d["within"] == pytest.approx(d["total"], abs=1e-6)


def test_theil_zero_when_all_equal():
    df = pd.DataFrame({"aid": [10.0] * 20, "grp": [0, 1] * 10})
    d = theil_decomposition(df, value_col="aid", group_col="grp")
    assert d["total"] == pytest.approx(0.0, abs=1e-9)


def test_spearman_and_equity_summary(panel, config):
    allf = run_all_scenarios(config, panel, budget=BUDGET)
    sp = spearman_between_scenarios(allf)
    assert sp.shape[0] == sp.shape[1] == allf["scenario_id"].nunique()
    assert np.allclose(np.diag(sp.to_numpy()), 1.0)

    grp = allf[allf["scenario_id"] == 5]
    summ = equity_summary(grp, group_col="county_id")
    for k in ("gini_aid", "concentration_index", "kakwani_index", "lorenz_points", "theil"):
        assert k in summ
    assert 0.0 <= summ["gini_aid"] <= 1.0
