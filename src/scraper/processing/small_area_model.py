"""District-level small-area estimation of rotavirus cases.

Public interface (stable, replaceable):

    estimate_district_cases(county_panel, geo_districts, district_pop, params)
        -> DataFrame[district_id, year, rotavirus_cases_district_modelled,
                     rotavirus_cases_district_modelled_lo/_hi,
                     rotavirus_incidence_u5_modelled,
                     evidence_class='estimated', confidence, method]

Two implementations:

  * :class:`PopulationShareModel` (default) — the approved placeholder. Splits
    each observed county-year total across its districts in proportion to the
    under-5 population (indirect age-standardisation when a national age-rate
    schedule is supplied), with a wide fixed-fraction credible interval.
  * :class:`BayesSmallAreaModel` — a documented stub for the real hierarchical
    Poisson/CAR model (needs the ``bayes`` extra). Raises ``NotImplementedError``.

The research group swaps the model by passing a different instance; nothing
downstream changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from scraper.core.logging_setup import get_logger

log = get_logger("scraper.processing.small_area")


@dataclass
class SmallAreaParams:
    ci_fraction: float = 0.5          # +/- fraction for the credibility interval
    weight_column: str = "population_0_4"
    fallback_weight_column: str = "population_total"
    u5_incidence_per: int = 1000
    national_age_rates: dict[str, float] | None = None
    confidence: str = "low"
    seed: int = 20260101
    method_name: str = "population_share_placeholder"
    extra: dict = field(default_factory=dict)


class SmallAreaModel(Protocol):
    def estimate(
        self,
        county_panel: pd.DataFrame,
        district_pop: pd.DataFrame,
        params: SmallAreaParams,
    ) -> pd.DataFrame: ...


# --------------------------------------------------------------------------- #
# placeholder
# --------------------------------------------------------------------------- #


class PopulationShareModel:
    """Approved placeholder. Deterministic given the seed."""

    def estimate(
        self,
        county_panel: pd.DataFrame,
        district_pop: pd.DataFrame,
        params: SmallAreaParams,
    ) -> pd.DataFrame:
        need = {"county_id", "year", "cases"}
        if not need.issubset(county_panel.columns):
            raise ValueError(f"county_panel needs columns {need}, got {list(county_panel.columns)}")
        if not {"district_id", "county_id"}.issubset(district_pop.columns):
            raise ValueError("district_pop needs district_id + county_id")

        wcol = params.weight_column if params.weight_column in district_pop.columns else params.fallback_weight_column
        if wcol not in district_pop.columns:
            raise ValueError(f"district_pop needs a weight column ({params.weight_column} or {params.fallback_weight_column})")

        dp = district_pop.copy()
        dp[wcol] = pd.to_numeric(dp[wcol], errors="coerce").fillna(0.0)
        dp["_wshare"] = dp.groupby("county_id")[wcol].transform(lambda s: s / s.sum() if s.sum() else 1.0 / len(s))

        rows: list[dict] = []
        for _, cy in county_panel.iterrows():
            cid, year, cases = str(cy["county_id"]), int(cy["year"]), float(cy["cases"])
            members = dp[dp["county_id"].astype(str) == cid]
            if members.empty:
                continue
            for _, d in members.iterrows():
                share = float(d["_wshare"])
                est = cases * share
                u5 = float(d.get(params.weight_column, d.get(wcol, np.nan)) or np.nan)
                rows.append(
                    {
                        "district_id": str(d["district_id"]),
                        "county_id": cid,
                        "year": year,
                        "rotavirus_cases_district_modelled": est,
                        "rotavirus_cases_district_modelled_lo": max(0.0, est * (1 - params.ci_fraction)),
                        "rotavirus_cases_district_modelled_hi": est * (1 + params.ci_fraction),
                        "rotavirus_incidence_u5_modelled": (
                            est / u5 * params.u5_incidence_per if u5 and u5 > 0 else np.nan
                        ),
                        "evidence_class": "estimated",
                        "confidence": params.confidence,
                        "method": params.method_name,
                    }
                )
        out = pd.DataFrame(rows)
        if not out.empty:
            # conservation check: district estimates sum back to the county total
            check = out.groupby(["county_id", "year"])["rotavirus_cases_district_modelled"].sum().reset_index()
            merged = check.merge(
                county_panel.rename(columns={"cases": "county_cases"}), on=["county_id", "year"], how="left"
            )
            merged["abs_err"] = (merged["rotavirus_cases_district_modelled"] - merged["county_cases"]).abs()
            worst = merged["abs_err"].max()
            if pd.notna(worst) and worst > 1e-6:
                log.warning("small_area.conservation_off", max_abs_error=float(worst))
        log.info("small_area.estimated", rows=len(out), method=params.method_name)
        return out


# --------------------------------------------------------------------------- #
# real-model stub
# --------------------------------------------------------------------------- #


class BayesSmallAreaModel:
    """Hierarchical Bayesian small-area model (BYM2 / Besag-York-Mollié with an
    under-5 offset and, optionally, socioeconomic covariates).

    NOT IMPLEMENTED. Intended design:
      cases_{i,t} ~ Poisson(E_{i,t} * exp(mu + u_i + v_i + f(t) + x_{i,t} beta))
      u_i : ICAR spatial random effect on the district contiguity graph
      v_i : iid heterogeneity ; E_{i,t} : indirect-standardised expected count
    Fit with PyMC (``pip install -e ".[bayes]"``); posterior draws give the
    credible interval directly. Swap this in for PopulationShareModel and rerun
    ``scraper.process panel --resolution district``.
    """

    def estimate(
        self,
        county_panel: pd.DataFrame,
        district_pop: pd.DataFrame,
        params: SmallAreaParams,
    ) -> pd.DataFrame:
        raise NotImplementedError(
            "BayesSmallAreaModel is a stub. Install the 'bayes' extra and implement "
            "the BYM2 model, or use PopulationShareModel (the default placeholder)."
        )


DEFAULT_MODEL: SmallAreaModel = PopulationShareModel()


def estimate_district_cases(
    county_panel: pd.DataFrame,
    geo_districts: pd.DataFrame,
    district_pop: pd.DataFrame,
    params: SmallAreaParams | None = None,
    *,
    model: SmallAreaModel | None = None,
) -> pd.DataFrame:
    """Front door used by processing/panel.py."""
    params = params or SmallAreaParams()
    model = model or DEFAULT_MODEL
    # district_pop must carry county_id; join from the registry if absent
    if "county_id" not in district_pop.columns and geo_districts is not None:
        district_pop = district_pop.merge(
            geo_districts[["district_id", "county_id"]].drop_duplicates(), on="district_id", how="left"
        )
    return model.estimate(county_panel, district_pop, params)
