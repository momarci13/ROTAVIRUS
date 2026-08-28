"""Allocation scenarios 0-7 as parameterisations of ONE generic function.

``allocate_generic`` is the whole model. ``run_scenario`` reads
config/scenarios.yaml, maps a scenario's fields onto ``allocate_generic``'s
arguments, and returns a long frame. A new scenario is a new YAML block — no
code change (spec §10, §18).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from scraper.allocation.need_index import _minmax01, compute_need_index
from scraper.core.config import Config, Scenario
from scraper.core.errors import AllocationError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.allocation.scenarios")


@dataclass(slots=True)
class GenericParams:
    budget: float
    cost: pd.Series | None = None          # Chat_i (HUF) or None -> 1
    need: pd.Series | None = None          # Ntilde_i in [0,1] or None -> 0
    fiscal_tilde: pd.Series | None = None  # Ftilde_i in [0,1] or None -> 0
    fiscal_capacity_huf: pd.Series | None = None
    existing: pd.Series | None = None      # L_i (HUF)
    per_capita: pd.Series | None = None    # P_u5_i or None -> 1
    eta: float = 0.0
    kappa: float = 0.0
    alpha: float = 1.0
    phi: float = 0.0
    subtract_existing: bool = False
    fiscal_penalty: bool = False
    fiscal_capacity_subtraction: bool = False
    eligibility_mask: pd.Series | None = None
    passthrough: pd.Series | None = None
    normalise_to_budget: bool = True
    floor: float = 0.0


def allocate_generic(index: pd.Index, p: GenericParams) -> pd.Series:
    """Return the aid vector (HUF) indexed like ``index``.

    raw_i = base_i * cost_i * (1 + eta*need_i^alpha) * (1 - kappa*Ftilde_i)
            - [subtract_existing] L_i
            - [fiscal_capacity_subtraction] phi * FiscCap_i
    raw_i = max(raw_i, floor); raw_i = 0 where not eligible
    aid_i = B * raw_i / sum_j raw_j          (if normalise_to_budget)
          = raw_i                            (otherwise, e.g. cost-gap)
    """
    n = len(index)
    ones = pd.Series(np.ones(n), index=index)

    if p.passthrough is not None:
        aid = p.passthrough.reindex(index).fillna(0.0).astype(float)
        return _normalise(aid, p) if p.normalise_to_budget else aid

    base = _s(p.per_capita, index, default=ones)
    cost = _s(p.cost, index, default=ones)
    need = _s(p.need, index, default=pd.Series(np.zeros(n), index=index))
    fisc = _s(p.fiscal_tilde, index, default=pd.Series(np.zeros(n), index=index))

    need_term = 1.0 + p.eta * np.power(need.clip(lower=0), p.alpha)
    fisc_term = (1.0 - p.kappa * fisc) if p.fiscal_penalty else 1.0

    raw = base * cost * need_term * fisc_term

    if p.subtract_existing and p.existing is not None:
        raw = raw - _s(p.existing, index, default=pd.Series(np.zeros(n), index=index))
    if p.fiscal_capacity_subtraction and p.fiscal_capacity_huf is not None:
        raw = raw - p.phi * _s(p.fiscal_capacity_huf, index, default=pd.Series(np.zeros(n), index=index))

    raw = raw.clip(lower=p.floor)
    if p.eligibility_mask is not None:
        raw = raw.where(p.eligibility_mask.reindex(index).fillna(False), 0.0)

    if not p.normalise_to_budget:
        return raw.astype(float)
    return _normalise(raw, p)


def _normalise(raw: pd.Series, p: GenericParams) -> pd.Series:
    total = raw.sum()
    if total <= 0:
        raise AllocationError("allocation weights sum to <= 0; cannot normalise to the budget")
    return (p.budget * raw / total).astype(float)


def _s(series: pd.Series | None, index: pd.Index, *, default: pd.Series) -> pd.Series:
    if series is None:
        return default
    return pd.to_numeric(series.reindex(index), errors="coerce").fillna(0.0)


# --------------------------------------------------------------------------- #
# config -> params
# --------------------------------------------------------------------------- #

_NEED_COL = {
    "full": "need_score",
    "socioeconomic": "need_socioeconomic",
    "healthcare": "need_healthcare",
    "fiscal_capacity": "need_fiscal_capacity",
}


def build_params(
    config: Config,
    panel: pd.DataFrame,
    scenario: Scenario,
    *,
    budget: float,
    need_frame: pd.DataFrame | None = None,
) -> GenericParams:
    idx = panel.index

    if need_frame is None:
        need_frame = compute_need_index(panel, config.need_index)
    need_frame = need_frame.set_index(panel.index)

    def col(name: str) -> pd.Series | None:
        return panel[name] if name in panel.columns else None

    # need term
    need_series: pd.Series | None = None
    if scenario.need_term == "epidemiological":
        for c in ("expected_cases_per_1000_u5_modelled", "rotavirus_cases_district_modelled"):
            if c in panel.columns:
                need_series = _minmax01(pd.to_numeric(panel[c], errors="coerce").fillna(0.0))
                break
    elif scenario.need_term in _NEED_COL:
        nc = _NEED_COL[scenario.need_term]
        if nc in need_frame.columns:
            need_series = need_frame[nc]

    cost_series = col("expected_total_cost_huf_real_2025") if scenario.cost_term == "expected_total_cost" else None

    pc_series = col(scenario.per_capita_base) if scenario.per_capita_base != "none" else None

    fisc_raw = col("municipal_own_revenue_per_capita")
    fisc_tilde = _minmax01(pd.to_numeric(fisc_raw, errors="coerce").fillna(0.0)) if fisc_raw is not None else None
    fisc_huf = col("municipal_own_revenue_per_capita")

    existing = col("existing_local_funding")

    mask = None
    if scenario.eligibility_filter == "kedvezmenyezett_jaras_290_2014":
        for c in ("kedvezmenyezett_status", "kedvezmenyezett_jaras_290_2014"):
            if c in panel.columns:
                mask = panel[c].astype("boolean").fillna(False)
                break
        if mask is None:
            log.warning("scenario.eligibility_column_missing", scenario=scenario.id)
            mask = pd.Series(True, index=idx)

    passthrough = col(scenario.passthrough_variable) if scenario.passthrough_variable else None

    return GenericParams(
        budget=budget,
        cost=cost_series,
        need=need_series,
        fiscal_tilde=fisc_tilde,
        fiscal_capacity_huf=fisc_huf,
        existing=existing,
        per_capita=pc_series,
        eta=scenario.eta,
        kappa=scenario.kappa,
        alpha=scenario.alpha,
        phi=scenario.phi,
        subtract_existing=scenario.subtract_existing,
        fiscal_penalty=scenario.fiscal_penalty,
        fiscal_capacity_subtraction=scenario.fiscal_capacity_subtraction,
        eligibility_mask=mask,
        passthrough=passthrough,
        normalise_to_budget=scenario.normalise_to_budget,
        floor=scenario.floor,
    )


def run_scenario(
    config: Config,
    panel: pd.DataFrame,
    scenario_id: int,
    *,
    budget: float | None = None,
    year: int | None = None,
    need_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    scen = config.scenarios.by_id(scenario_id)
    budget = float(budget if budget is not None else config.scenarios.default_budget_huf)
    year = year or config.scenarios.default_year

    panel = panel.reset_index(drop=True)
    params = build_params(config, panel, scen, budget=budget, need_frame=need_frame)
    aid = allocate_generic(panel.index, params)

    if need_frame is None:
        need_frame = compute_need_index(panel, config.need_index)
    out = pd.DataFrame(
        {
            "district_id": panel["district_id"].to_numpy() if "district_id" in panel.columns else panel.index,
            "scenario_id": scenario_id,
            "scenario_name": scen.name,
            "year": year,
            "aid_amount_huf": aid.to_numpy(),
            "need_score": need_frame["need_score"].to_numpy(),
        }
    )
    log.info(
        "scenario.run",
        scenario=scenario_id,
        budget=budget,
        total_allocated=float(out["aid_amount_huf"].sum()),
        normalised=scen.normalise_to_budget,
    )
    return out


def run_all_scenarios(
    config: Config, panel: pd.DataFrame, *, budget: float | None = None, year: int | None = None
) -> pd.DataFrame:
    panel = panel.reset_index(drop=True)
    need_frame = compute_need_index(panel, config.need_index)
    frames = []
    baseline_id = 0
    baseline = None
    for scen in config.scenarios.scenarios:
        f = run_scenario(config, panel, scen.id, budget=budget, year=year, need_frame=need_frame)
        if scen.id == baseline_id:
            baseline = f.set_index("district_id")["aid_amount_huf"]
        frames.append(f)
    allf = pd.concat(frames, ignore_index=True)
    if baseline is not None:
        allf["delta_vs_baseline"] = allf["aid_amount_huf"] - allf["district_id"].map(baseline).fillna(0.0)
    return allf
