"""Sensitivity analysis (spec §10).

    one_way_tornado   +/- deltas on each scalar input, effect on a summary stat
    psa               probabilistic Monte-Carlo (gamma costs, beta ratios,
                      lognormal efficacy)
    dirichlet_weights  resample need-index dimension weights; report which
                      districts stay in the top decile "robustly"
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from scraper.allocation.need_index import compute_need_index
from scraper.allocation.scenarios import run_scenario
from scraper.core.config import Config
from scraper.core.seeds import rng


def one_way_tornado(
    base_inputs: dict[str, float],
    evaluate: Callable[[dict[str, float]], float],
    *,
    deltas: tuple[float, ...] = (0.10, 0.25, 0.50),
) -> pd.DataFrame:
    base_val = evaluate(base_inputs)
    rows = []
    for name, val in base_inputs.items():
        for d in deltas:
            lo = dict(base_inputs, **{name: val * (1 - d)})
            hi = dict(base_inputs, **{name: val * (1 + d)})
            rows.append(
                {
                    "input": name,
                    "delta": d,
                    "low": evaluate(lo),
                    "high": evaluate(hi),
                    "base": base_val,
                    "swing": abs(evaluate(hi) - evaluate(lo)),
                }
            )
    return pd.DataFrame(rows).sort_values(["delta", "swing"], ascending=[True, False])


def psa(
    config: Config,
    panel: pd.DataFrame,
    scenario_id: int,
    *,
    draws: int = 2000,
    budget: float | None = None,
    seed: int | None = None,
    cost_cv: float = 0.3,
    ratio_a: float = 8.0,
    ratio_b: float = 2.0,
) -> pd.DataFrame:
    """Perturb the cost column (gamma) and the modelled-incidence column (beta
    shape) per draw; return per-district aid mean / p2.5 / p97.5."""
    g = rng(seed if seed is not None else config.seed())
    base = panel.reset_index(drop=True).copy()
    cost_col = "expected_total_cost_huf_real_2025"
    inc_col = "expected_cases_per_1000_u5_modelled"

    stacks = np.zeros((draws, len(base)))
    for i in range(draws):
        p = base.copy()
        if cost_col in p.columns:
            mu = pd.to_numeric(p[cost_col], errors="coerce").fillna(0.0).to_numpy()
            shape = 1.0 / (cost_cv**2)
            scale = np.where(mu > 0, mu / shape, 0.0)
            p[cost_col] = g.gamma(shape, scale)
        if inc_col in p.columns:
            x = pd.to_numeric(p[inc_col], errors="coerce").fillna(0.0).to_numpy()
            mx = x.max() or 1.0
            frac = np.clip(x / mx, 1e-6, 1 - 1e-6)
            p[inc_col] = g.beta(ratio_a * frac, ratio_b * (1 - frac)) * mx
        res = run_scenario(config, p, scenario_id, budget=budget)
        stacks[i] = res["aid_amount_huf"].to_numpy()

    return pd.DataFrame(
        {
            "district_id": base.get("district_id", pd.Series(range(len(base)))),
            "aid_mean": stacks.mean(axis=0),
            "aid_p2_5": np.percentile(stacks, 2.5, axis=0),
            "aid_p97_5": np.percentile(stacks, 97.5, axis=0),
        }
    )


def dirichlet_weight_sampling(
    config: Config,
    panel: pd.DataFrame,
    scenario_id: int,
    *,
    draws: int = 2000,
    concentration: float = 20.0,
    budget: float | None = None,
    seed: int | None = None,
    top_q: float = 0.9,
) -> pd.DataFrame:
    """Resample the need-index dimension weights from a Dirichlet centred on the
    configured weights; report how often each district lands in the top decile."""
    g = rng(seed if seed is not None else config.seed())
    base = panel.reset_index(drop=True).copy()
    dims = list(config.need_index.dimensions)
    w0 = np.array([config.need_index.dimensions[d].weight for d in dims], dtype=float)
    w0 = w0 / w0.sum()

    counts = np.zeros(len(base))
    for _ in range(draws):
        w = g.dirichlet(concentration * w0)
        for d, wi in zip(dims, w):
            config.need_index.dimensions[d].weight = float(wi)
        nf = compute_need_index(base, config.need_index)
        res = run_scenario(config, base, scenario_id, budget=budget, need_frame=nf)
        aid = res["aid_amount_huf"].to_numpy()
        thr = np.quantile(aid, top_q)
        counts += aid >= thr

    # restore configured weights
    for d, wi in zip(dims, w0):
        config.need_index.dimensions[d].weight = float(wi)

    freq = counts / draws
    return pd.DataFrame(
        {
            "district_id": base.get("district_id", pd.Series(range(len(base)))),
            "top_decile_frequency": freq,
            "robust_top_decile": freq >= 0.8,
        }
    ).sort_values("top_decile_frequency", ascending=False)
