"""Small-area smoothing: empirical-Bayes shrinkage and moving averages.

These reduce the volatility that small district counts otherwise show
(README limitation: "kis területi volatilitás").
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def moving_average(s: pd.Series, window: int = 5, *, center: bool = True, min_periods: int = 1) -> pd.Series:
    return s.rolling(window=window, center=center, min_periods=min_periods).mean()


def empirical_bayes_poisson(
    counts: np.ndarray | pd.Series,
    expected: np.ndarray | pd.Series,
) -> pd.Series:
    """Poisson-Gamma empirical Bayes (Clayton-Kaldor style).

    Relative risk RR_i shrunk towards 1 by a data-estimated Gamma(alpha, beta)
    prior. Returns the posterior RR mean per area.
    """
    y = np.asarray(counts, dtype=float)
    e = np.asarray(expected, dtype=float)
    e = np.where(e <= 0, np.nan, e)

    rr_raw = y / e
    m = np.nanmean(rr_raw)
    v = np.nanvar(rr_raw)
    # method of moments for Gamma prior on RR with mean m
    if v <= 0 or np.isnan(v) or m <= 0:
        return pd.Series(np.nan_to_num(rr_raw, nan=1.0))
    beta = m / v
    alpha = m * beta
    rr_post = (y + alpha) / (e + beta)
    return pd.Series(rr_post)


def eb_smoothed_rate(
    df: pd.DataFrame,
    *,
    count_col: str,
    expected_col: str,
    national_rate: float,
    per: int = 1000,
    rr_col: str = "eb_rr",
    out_col: str = "eb_rate",
) -> pd.DataFrame:
    """Add the EB posterior relative risk and the implied smoothed rate
    (``rr_post * national_rate * per``)."""
    out = df.copy()
    rr = empirical_bayes_poisson(out[count_col], out[expected_col]).to_numpy()
    out[rr_col] = rr
    out[out_col] = rr * national_rate * per
    return out
