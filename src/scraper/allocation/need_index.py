"""Composite need index (spec §10), fully driven by config/need_index.yaml.

Standardisation:  zscore | minmax | rank
Aggregation:      weighted_sum | mpi (Mazziotta-Pareto) | pca | entropy

Returns a frame with one row per area carrying ``need_score`` (0..1 after a final
min-max rescale) plus a ``need_<dimension>`` sub-score for every dimension, so
scenarios 3/4 can target a single dimension.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from scraper.core.config import NeedIndexConfig
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.allocation.need_index")


# --------------------------------------------------------------------------- #
# standardisation
# --------------------------------------------------------------------------- #


def standardise(s: pd.Series, method: str) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce").astype(float)
    if method == "zscore":
        sd = x.std(ddof=0)
        return (x - x.mean()) / sd if sd and not np.isnan(sd) else x * 0.0
    if method == "minmax":
        lo, hi = x.min(), x.max()
        return (x - lo) / (hi - lo) if hi > lo else x * 0.0
    if method == "rank":
        return x.rank(method="average", pct=True)
    raise ValueError(f"unknown standardisation '{method}'")


def _minmax01(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else s * 0.0 + 0.5


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #


def _weighted_sum(dim_scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    acc = pd.Series(0.0, index=dim_scores.index)
    for d, w in weights.items():
        acc = acc + dim_scores[d] * w
    return acc


def _mpi(dim_scores: pd.DataFrame, weights: dict[str, float], *, penalty_sign: str) -> pd.Series:
    """Mazziotta-Pareto: mean +/- (std * cv). Non-compensatory: penalises areas
    with unbalanced dimension profiles."""
    cols = list(weights)
    z = dim_scores[cols]
    # rescale each dim to mean 100, sd 10 as in the classic MPI
    zz = 100 + 10 * (z - z.mean()) / z.std(ddof=0).replace(0, np.nan)
    zz = zz.fillna(100.0)
    m = zz.mean(axis=1)
    sd = zz.std(axis=1, ddof=0)
    cv = sd / m.replace(0, np.nan)
    sign = -1.0 if penalty_sign == "negative" else 1.0
    return m + sign * sd * cv


def _pca(dim_scores: pd.DataFrame, weights: dict[str, float], n_components: int) -> pd.Series:
    cols = list(weights)
    x = dim_scores[cols].to_numpy(dtype=float)
    x = x - x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0
    x = x / sd
    _u, _s, vt = np.linalg.svd(x, full_matrices=False)
    comp = x @ vt[:n_components].T
    scores = comp[:, 0] if comp.shape[1] else np.zeros(len(x))
    # orient so higher score = more need (correlate with the mean dimension)
    if np.corrcoef(scores, x.mean(axis=1))[0, 1] < 0:
        scores = -scores
    return pd.Series(scores, index=dim_scores.index)


def _entropy(dim_scores: pd.DataFrame, weights: dict[str, float], *, respect_dim_weights: bool) -> pd.Series:
    cols = list(weights)
    p = dim_scores[cols].clip(lower=0) + 1e-9
    p = p / p.sum(axis=0)
    k = 1.0 / np.log(len(p))
    e = -k * (p * np.log(p)).sum(axis=0)
    d = 1 - e
    w = d / d.sum()
    if respect_dim_weights:
        base = pd.Series(weights)
        w = (w * base) / (w * base).sum()
    return dim_scores[cols].mul(w, axis=1).sum(axis=1)


# --------------------------------------------------------------------------- #
# public
# --------------------------------------------------------------------------- #


def compute_need_index(
    panel: pd.DataFrame,
    cfg: NeedIndexConfig,
    *,
    id_col: str = "district_id",
) -> pd.DataFrame:
    """Return ``[id_col, need_score, need_<dim>...]`` for every row of ``panel``."""
    method = cfg.standardisation
    inv_suffix = cfg.inverse_suffix
    weights = cfg.normalised_weights()

    impute = cfg.missing_data.get("impute", "median")
    warn_t = float(cfg.missing_data.get("warn_threshold", 0.1))

    dim_scores = pd.DataFrame(index=panel.index)
    for dim_name, dim in cfg.dimensions.items():
        var_std: list[pd.Series] = []
        for var in dim.variables:
            src = var[: -len(inv_suffix)] if var.endswith(inv_suffix) else var
            flip = var.endswith(inv_suffix)
            if src not in panel.columns:
                log.warning("need_index.missing_variable", variable=src, dimension=dim_name)
                continue
            col = pd.to_numeric(panel[src], errors="coerce")
            miss = col.isna().mean()
            if miss > warn_t:
                log.warning("need_index.high_missing", variable=src, share=round(float(miss), 3))
            if impute == "median":
                col = col.fillna(col.median())
            elif impute == "mean":
                col = col.fillna(col.mean())
            z = standardise(col, method)
            if flip:
                z = -z
            var_std.append(z)
        if not var_std:
            dim_scores[dim_name] = 0.0
            continue
        dscore = pd.concat(var_std, axis=1).mean(axis=1)
        if dim.direction == "inverse":
            dscore = -dscore
        dim_scores[dim_name] = dscore

    agg = cfg.aggregation
    if agg == "weighted_sum":
        raw = _weighted_sum(dim_scores, weights)
    elif agg == "mpi":
        raw = _mpi(dim_scores, weights, penalty_sign=cfg.mpi.get("penalty_sign", "negative"))
    elif agg == "pca":
        raw = _pca(dim_scores, weights, int(cfg.pca.get("n_components", 1)))
    elif agg == "entropy":
        raw = _entropy(dim_scores, weights, respect_dim_weights=bool(cfg.entropy.get("respect_dimension_weights", False)))
    else:
        raise ValueError(f"unknown aggregation '{agg}'")

    out = pd.DataFrame({id_col: panel[id_col].to_numpy()})
    out["need_score"] = _minmax01(raw).to_numpy()
    for dim_name in cfg.dimensions:
        out[f"need_{dim_name}"] = _minmax01(dim_scores[dim_name]).to_numpy()
    log.info("need_index.computed", areas=len(out), aggregation=agg, standardisation=method)
    return out
