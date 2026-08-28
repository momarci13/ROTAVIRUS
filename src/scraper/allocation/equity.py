"""Distributional / equity metrics for comparing allocation scenarios (spec §10).

    concentration_index   aid ranked by a need/burden variable
    kakwani_index         concentration(aid) - Gini(need)  (progressivity)
    gini                  of the aid distribution
    lorenz_points         cumulative population share vs cumulative aid share
    theil_decomposition   between-county vs within-county
    spearman_between      rank correlation of aid across scenarios
    top_decile_overlap    share of the top-need decile also in the top-aid decile
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _sorted_by(values: np.ndarray, key: np.ndarray) -> np.ndarray:
    order = np.argsort(key, kind="mergesort")
    return values[order]


def gini(x: np.ndarray | pd.Series) -> float:
    a = np.asarray(x, dtype=float)
    a = a[~np.isnan(a)]
    if a.size == 0 or np.all(a == 0):
        return 0.0
    a = np.sort(a)
    n = a.size
    cum = np.cumsum(a)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def lorenz_points(x: np.ndarray | pd.Series) -> tuple[np.ndarray, np.ndarray]:
    a = np.sort(np.asarray(x, dtype=float))
    a = a[~np.isnan(a)]
    if a.size == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])
    cum = np.cumsum(a)
    cum = cum / cum[-1] if cum[-1] else np.linspace(0, 1, a.size)
    p = np.arange(1, a.size + 1) / a.size
    return np.concatenate([[0.0], p]), np.concatenate([[0.0], cum])


def concentration_index(aid: np.ndarray | pd.Series, rank_var: np.ndarray | pd.Series) -> float:
    """CI in [-1, 1]. 0 => aid unrelated to rank_var; >0 => aid concentrates on
    high-rank_var (e.g. high-need) areas."""
    y = np.asarray(aid, dtype=float)
    r = np.asarray(rank_var, dtype=float)
    ok = ~(np.isnan(y) | np.isnan(r))
    y, r = y[ok], r[ok]
    if y.size == 0 or y.sum() == 0:
        return 0.0
    ys = _sorted_by(y, r)
    n = ys.size
    frac_rank = (np.arange(1, n + 1) - 0.5) / n
    mu = ys.mean()
    return float(2.0 / (n * mu) * np.sum((ys - mu) * (frac_rank - 0.5)))


def kakwani_index(aid: np.ndarray | pd.Series, need: np.ndarray | pd.Series) -> float:
    """Progressivity: concentration(aid wrt need) - Gini(need)."""
    return concentration_index(aid, need) - gini(need)


def theil_decomposition(
    df: pd.DataFrame, *, value_col: str, group_col: str
) -> dict[str, float]:
    x = pd.to_numeric(df[value_col], errors="coerce").to_numpy(dtype=float)
    x = np.where(np.isnan(x), 0.0, x)
    if x.sum() == 0:
        return {"total": 0.0, "between": 0.0, "within": 0.0}
    n = x.size
    mu = x.mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        t_total = np.nansum((x / mu) * np.log(np.where(x > 0, x / mu, 1.0))) / n

    groups = df[group_col].to_numpy()
    between = 0.0
    within = 0.0
    for g in pd.unique(groups):
        xg = x[groups == g]
        ng = xg.size
        sg = xg.sum()
        if sg <= 0:
            continue
        share = sg / x.sum()
        mug = xg.mean()
        between += share * np.log(mug / mu) if mug > 0 else 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            tg = np.nansum((xg / mug) * np.log(np.where(xg > 0, xg / mug, 1.0))) / ng
        within += share * tg
    return {"total": float(t_total), "between": float(between), "within": float(within)}


def spearman_between_scenarios(long_alloc: pd.DataFrame) -> pd.DataFrame:
    wide = long_alloc.pivot_table(index="district_id", columns="scenario_id", values="aid_amount_huf")
    return wide.corr(method="spearman")


def top_decile_overlap(
    aid: pd.Series, need: pd.Series, *, q: float = 0.9
) -> float:
    a_thr = aid.quantile(q)
    n_thr = need.quantile(q)
    top_a = set(aid[aid >= a_thr].index)
    top_n = set(need[need >= n_thr].index)
    if not top_n:
        return float("nan")
    return len(top_a & top_n) / len(top_n)


def equity_summary(
    alloc: pd.DataFrame,
    *,
    need_col: str = "need_score",
    aid_col: str = "aid_amount_huf",
    group_col: str | None = None,
) -> dict:
    aid = pd.to_numeric(alloc[aid_col], errors="coerce")
    need = pd.to_numeric(alloc[need_col], errors="coerce")
    out: dict = {
        "gini_aid": gini(aid),
        "concentration_index": concentration_index(aid, need),
        "kakwani_index": kakwani_index(aid, need),
        "top_decile_overlap": top_decile_overlap(aid.reset_index(drop=True), need.reset_index(drop=True)),
    }
    if group_col and group_col in alloc.columns:
        out["theil"] = theil_decomposition(alloc, value_col=aid_col, group_col=group_col)
    px, py = lorenz_points(aid)
    out["lorenz_points"] = {"p": px.tolist(), "L": py.tolist()}
    return out
