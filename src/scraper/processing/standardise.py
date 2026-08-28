"""Indirect age-standardisation.

The county x age-group cross-tabulation is not public (README limitation), so we
standardise *indirectly*: apply a national age-specific rate schedule to each
area's age structure to get an "expected" count, then form the
standardised incidence ratio  SIR = observed / expected.
"""

from __future__ import annotations

import pandas as pd

from scraper.core.logging_setup import get_logger

log = get_logger("scraper.processing.standardise")


def expected_counts(
    area_population_by_age: pd.DataFrame,
    national_rates_by_age: dict[str, float],
    *,
    area_col: str = "area_id",
    age_cols: list[str] | None = None,
) -> pd.DataFrame:
    """``area_population_by_age``: one row per area, columns = age-group populations.
    ``national_rates_by_age``: {age_group: rate per person}. Returns area_id +
    expected_count."""
    age_cols = age_cols or [c for c in area_population_by_age.columns if c in national_rates_by_age]
    if not age_cols:
        raise ValueError("no age-group columns match the national rate schedule")
    out = area_population_by_age[[area_col]].copy()
    exp = sum(
        area_population_by_age[c].astype(float) * national_rates_by_age[c] for c in age_cols
    )
    out["expected_count"] = exp
    return out


def indirect_sir(
    observed: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    area_col: str = "area_id",
    observed_col: str = "observed_count",
) -> pd.DataFrame:
    m = observed.merge(expected, on=area_col, how="inner")
    m["sir"] = m[observed_col] / m["expected_count"].replace(0, pd.NA)
    m["sir"] = m["sir"].astype(float)
    return m[[area_col, observed_col, "expected_count", "sir"]]


def age_standardised_rate(
    sir_frame: pd.DataFrame, national_crude_rate: float, *, per: int = 1000
) -> pd.DataFrame:
    out = sir_frame.copy()
    out["age_standardised_rate"] = out["sir"] * national_crude_rate * per
    return out
