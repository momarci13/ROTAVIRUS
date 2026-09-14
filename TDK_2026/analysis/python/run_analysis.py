#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""End-to-end analysis driver for the Corvinus TDK paper.

Reads the pipeline's parquet outputs (``data/processed`` + ``data/intermediate``)
and the analysis config in ``analysis/config``, then produces every figure
(``analysis/paper/figures/*.pdf``), LaTeX table fragment
(``analysis/paper/tables/*.tex``) and the number-macro file
(``analysis/paper/tables/_numbers.tex``) that ``analysis/paper/paper.tex``
pulls in with ``\\input``.

The R scripts in ``analysis/R`` reproduce the same steps from the same inputs;
this Python driver exists so the shipped paper compiles with real numbers even
where R is not installed.

Run:  python analysis/python/run_analysis.py
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# --------------------------------------------------------------------------- #
# paths & config
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parent
ROOT = ANALYSIS.parent
CFG = yaml.safe_load((ANALYSIS / "config" / "analysis.yaml").read_text(encoding="utf-8"))
COSTS = yaml.safe_load((ANALYSIS / "config" / "cost_parameters_analysis.yaml").read_text(encoding="utf-8"))
NEEDCFG = yaml.safe_load((ANALYSIS / "config" / "need_index_analysis.yaml").read_text(encoding="utf-8"))

PROC = ROOT / "data" / "processed"
INTER = ROOT / "data" / "intermediate"
META = ROOT / "data" / "metadata"
RESULTS = ANALYSIS / "results"
FIGDIR = ANALYSIS / "paper" / "figures"
TABDIR = ANALYSIS / "paper" / "tables"
for d in (RESULTS, FIGDIR, TABDIR):
    d.mkdir(parents=True, exist_ok=True)

YEAR = int(CFG["cross_section_year"])
PRE = int(CFG["pre_covid_year"])
BUDGET = float(CFG["budget_huf"])
CI_HW = float(CFG["burden_ci_halfwidth"])
TOP_SHARE = float(CFG["need_top_share"])
TOP_DEC = float(CFG["need_top_decile"])
ETA = float(CFG["allocation_eta"])
SEED = int(CFG["sensitivity"]["seed"])
PSA_DRAWS = int(CFG["sensitivity"]["psa_draws"])
W_DRAWS = int(CFG["sensitivity"]["weight_draws"])
DIR_CONC = float(CFG["sensitivity"]["dirichlet_concentration"])
ROBUST_T = float(CFG["sensitivity"]["robust_threshold"])

rng = np.random.default_rng(SEED)
plt.rcParams.update({"figure.dpi": 120, "savefig.bbox": "tight", "font.size": 9,
                     "axes.grid": True, "grid.alpha": 0.25})

NUM: dict[str, str] = {}  # LaTeX \newcommand payload


_NUMERIC_RE = re.compile(r"^([+\u2212-]?)(\d{1,3}(?:,\d{3})*|\d+)(\.\d+)?(\s*%?)$")


def hu_num(s: str) -> str:
    """Localise one Anglo-formatted number to Hungarian typographic convention.

    ``1,234.56`` becomes ``1\\,234{,}56``: the thousands separator becomes a LaTeX
    thin space and the decimal point becomes a brace-wrapped comma, which renders
    as a comma in both text and math mode.  Strings that are not plain numbers
    pass through unchanged, so this is safe to apply to every table cell.
    """
    m = _NUMERIC_RE.match(s.strip())
    if not m:
        return s
    sign, intpart, frac, suffix = m.groups()
    intpart = intpart.replace(",", "\\,")
    frac = "{,}" + frac[1:] if frac else ""
    return f"{sign}{intpart}{frac}{suffix}"


def macro(name: str, value, fmt: str = "{:,.0f}") -> None:
    """Register a LaTeX number macro (\\<name>), Hungarian-localised."""
    s = value if isinstance(value, str) else hu_num(fmt.format(value))
    NUM[name] = s


def zscore_np(x) -> np.ndarray:
    x = np.asarray(x, float)
    sd = np.nanstd(x, ddof=1)
    return (x - np.nanmean(x)) / sd if sd else np.zeros_like(x)


def boot_ci(fn, *arrays, reps=2000, seed=20260101, alpha=0.05):
    """Percentile bootstrap CI for statistic ``fn(*resampled_arrays)``."""
    arrays = [np.asarray(a, float) for a in arrays]
    n = len(arrays[0])
    rg = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        idx = rg.integers(0, n, n)
        try:
            out.append(fn(*[a[idx] for a in arrays]))
        except Exception:  # noqa: BLE001
            continue
    out = np.array([v for v in out if np.isfinite(v)])
    return float(np.quantile(out, alpha / 2)), float(np.quantile(out, 1 - alpha / 2))


# --------------------------------------------------------------------------- #
# name normalisation & county map
# --------------------------------------------------------------------------- #
_DROP = ("varmegye", "megye", " vm", "vm.", "kerulet", " ker", "ker.", "fovaros")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_accents(str(s).lower())
    s = s.replace(".", " ").replace("-", " ").replace(",", " ")
    s = " ".join(s.split())
    return s


def norm_settlement(s: str) -> str:
    s = norm(s)
    # "budapest 01 ker" / "budapest i " -> "budapest 01"
    m = re.match(r"budapest\s+(\d{1,2})\b", s)
    if m:
        return f"budapest {int(m.group(1)):02d}"
    roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
             "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
             "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20, "xxi": 21,
             "xxii": 22, "xxiii": 23}
    m = re.match(r"budapest\s+([ivx]+)\b", s)
    if m and m.group(1) in roman:
        return f"budapest {roman[m.group(1)]:02d}"
    for tok in ("kerulet", " ker", "ker "):
        s = s.replace(tok, " ")
    return " ".join(s.split())


def norm_county(s: str) -> str:
    s = norm(s)
    for tok in ("varmegye", "megye", "vm", "fovaros"):
        s = s.replace(tok, " ")
    s = " ".join(s.split())
    if s in ("budapest", "bp", ""):
        return "budapest"
    return s


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #
print("[1] loading data ...")
geo_d = pd.read_parquet(PROC / "geo_districts.parquet")
geo_s = pd.read_parquet(PROC / "geo_settlements.parquet")
cw = pd.read_parquet(PROC / "county_weekly_epi.parquet")
nfsz = pd.read_parquet(INTER / "nfsz" / "nfsz.parquet")
okfo = pd.read_parquet(INTER / "okfo" / "okfo.parquet")
ksh = pd.read_parquet(INTER / "ksh" / "ksh.parquet")

county_name_by_id = (geo_d[["county_id", "county_name"]].drop_duplicates()
                     .set_index("county_id")["county_name"].to_dict())
county_id_by_norm = {norm_county(v): k for k, v in county_name_by_id.items()}
# county_weekly_epi carries geo_name too
for _, r in cw[["county_id", "geo_name"]].drop_duplicates().iterrows():
    county_id_by_norm.setdefault(norm_county(r["geo_name"]), r["county_id"])

geo_s = geo_s.copy()
geo_s["s_norm"] = geo_s["settlement_name"].map(norm_settlement)
# settlement -> district, disambiguated by county
s2d = geo_s[["s_norm", "county_id", "district_id"]].copy()
s2d_unique_cty = (s2d.groupby(["s_norm", "county_id"])["district_id"]
                  .agg(lambda x: x.iloc[0] if x.nunique() == 1 else np.nan).reset_index())

DISTRICTS = geo_d[["district_id", "district_name", "county_id", "county_name",
                   "nuts3_code", "is_budapest_district"]].drop_duplicates("district_id").copy()
DISTRICTS = DISTRICTS.sort_values("district_id").reset_index(drop=True)
N_DIST = len(DISTRICTS)
print(f"    districts={N_DIST}  settlements={len(geo_s)}  counties={geo_d.county_id.nunique()}")


# --------------------------------------------------------------------------- #
# 1b. analysis-layer enrichments (analysis/data/, see acquire_extra.py)
# --------------------------------------------------------------------------- #
ADATA = ANALYSIS / "data"


def _opt_csv(name, **kw):
    p = ADATA / name
    return pd.read_csv(p, **kw) if p.exists() else None


POP290 = _opt_csv("kedvezmenyezett_jaras_290_2014.csv", dtype={"district_id": str})
POPAGE = _opt_csv("ksh_county_population_by_age.csv")
PRICE = _opt_csv("ksh_price_indices.csv")
ANN = _opt_csv("ksh_national_annual_diseases.csv")
MON = _opt_csv("ksh_national_monthly.csv")
OSAPC = _opt_csv("osap_county_annual_rotavirus.csv")
HAVE_290 = POP290 is not None and len(POP290) >= 150
HAVE_POPAGE = POPAGE is not None and len(POPAGE) > 0
print(f"    enrichments: 290/2014={'yes' if HAVE_290 else 'no'} "
      f"pop_by_age={'yes' if HAVE_POPAGE else 'no'} "
      f"price_idx={'yes' if PRICE is not None else 'no'} "
      f"osap_county={'yes' if OSAPC is not None else 'no'}")

# health-sector deflator 2024 -> 2025 (chained health CPI, base 2025=100); the
# wage/productivity term keeps its explicit documented nominal-growth factor.
DEFL_MED = 1.0
if PRICE is not None and {"year", "health_cpi_idx2025"}.issubset(PRICE.columns):
    _p = PRICE.set_index("year")["health_cpi_idx2025"]
    if 2024 in _p.index and 2025 in _p.index and _p.get(2024):
        DEFL_MED = float(_p[2025] / _p[2024])


# --------------------------------------------------------------------------- #
# 2. descriptive: national weekly series + county inequality over time
# --------------------------------------------------------------------------- #
print("[2] descriptive ...")
epi = cw[cw["variable"] == "rotavirus_cases"].copy()
epi["value"] = pd.to_numeric(epi["value"], errors="coerce")

# national weekly
natw = (epi.groupby(["iso_year", "iso_week"], as_index=False)["value"].sum()
        .sort_values(["iso_year", "iso_week"]))
natw["t"] = natw["iso_year"] + (natw["iso_week"] - 1) / 52.0

fig, ax = plt.subplots(figsize=(7.2, 2.9))
ax.plot(natw["t"], natw["value"], lw=0.9, color="#1f4e79")
ax.fill_between(natw["t"], 0, natw["value"], color="#1f4e79", alpha=0.15)
for py in CFG["partial_years"]:
    ax.axvspan(py, py + 1, color="grey", alpha=0.08)
ax.set_xlabel("Év"); ax.set_ylabel("Heti bejelentett eset")
ax.set_title("Bejelentett rotavírus‑gastroenteritis, országos heti esetszám (2017–2026)")
ax.margins(x=0.01)
fig.savefig(FIGDIR / "fig1_national_weekly.pdf"); plt.close(fig)

# annual county case counts + rate per 100k working-age pop (proxy)
nf = nfsz.copy()
nf["year"] = nf["period_start"].str.slice(0, 4).astype(int)
nf["cty_norm"] = nf["county_sheet"].map(norm_county)
nf["county_id"] = nf["cty_norm"].map(county_id_by_norm)
nf["s_norm"] = nf["settlement_name"].map(norm_settlement)
# a settlement is a valid data row only if it maps to a real settlement
pop_year = (nf[nf["year"] == YEAR].groupby(["county_id", "s_norm"], as_index=False)
            .agg(wap=("working_age_population", "mean"),
                 jobseekers=("registered_jobseekers", "mean")))
pop_year = pop_year.merge(s2d_unique_cty, on=["s_norm", "county_id"], how="left")
match_rate = pop_year["district_id"].notna().mean()
macro("nfsMatchRate", 100 * match_rate, "{:.1f}")

county_pop = pop_year.groupby("county_id", as_index=False).agg(
    wap=("wap", "sum"), jobseekers=("jobseekers", "sum"))
county_cases = (epi.groupby(["county_id", "iso_year"], as_index=False)["value"].sum()
                .rename(columns={"value": "cases", "iso_year": "year"}))

# observed county child population (KSH 0-14) by year for a meaningful rate
# denominator; falls back to the (time-invariant) working-age proxy if absent.
CHILD_BY_CY = {}
RATE_DENOM_LABEL = "100\\,000 munkavállalási korú fő"
if POPAGE is not None:
    _pa = POPAGE.copy()
    _pa["county_id"] = _pa["county_name"].map(norm_county).map(county_id_by_norm)
    _pa = _pa[(_pa["age_group"] == "age_0_14") & _pa["county_id"].notna()]
    CHILD_BY_CY = {(r.county_id, int(r.year)): r.population for r in _pa.itertuples()}
    RATE_DENOM_LABEL = "100\\,000 gyermek (0--14)"


def _cty_denom(cid, year):
    if CHILD_BY_CY:
        return CHILD_BY_CY.get((cid, year)) or CHILD_BY_CY.get((cid, max(y for (c, y) in CHILD_BY_CY if c == cid)))
    v = county_pop.loc[county_pop["county_id"] == cid, "wap"]
    return float(v.iloc[0]) if len(v) else np.nan


macro("rateDenom", RATE_DENOM_LABEL, "{}")


def gini(x: np.ndarray) -> float:
    x = np.sort(np.asarray(x, float))
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0 or x.sum() == 0:
        return np.nan
    idx = np.arange(1, n + 1)
    return float((2 * (idx * x).sum() - (n + 1) * x.sum()) / (n * x.sum()))


def cv(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    return float(x.std(ddof=1) / x.mean()) if len(x) > 1 and x.mean() else np.nan


ineq_rows = []
for y in CFG["trend_years"]:
    cc = county_cases[county_cases["year"] == y].merge(county_pop, on="county_id", how="inner")
    if cc.empty:
        continue
    cc["denom"] = [_cty_denom(c, y) for c in cc["county_id"]]
    cc["rate"] = cc["cases"] / cc["denom"] * 1e5
    ineq_rows.append({"year": y, "gini_rate": gini(cc["rate"].values),
                      "cv_rate": cv(cc["rate"].values), "total_cases": int(cc["cases"].sum()),
                      "partial": y in CFG["partial_years"]})
ineq = pd.DataFrame(ineq_rows)
ineq.to_csv(RESULTS / "county_inequality_by_year.csv", index=False)

# formal trend test: OLS of the annual Gini on year (complete years only)
_full = ineq[~ineq["partial"]]
if len(_full) >= 4:
    _b, _a = np.polyfit(_full["year"], _full["gini_rate"], 1)
    _yhat = _a + _b * _full["year"]
    _resid = _full["gini_rate"].values - _yhat.values
    _sse = float((_resid ** 2).sum())
    _sxx = float(((_full["year"] - _full["year"].mean()) ** 2).sum())
    _se = np.sqrt(_sse / (len(_full) - 2) / _sxx) if _sxx else np.nan
    from scipy import stats as _st  # noqa: E402
    _tt = _b / _se if _se else np.nan
    _p = float(2 * _st.t.sf(abs(_tt), len(_full) - 2)) if np.isfinite(_tt) else np.nan
    macro("giniTrendSlope", _b, "{:+.4f}")
    macro("giniTrendSlopeLo", _b - 1.96 * _se, "{:+.4f}")
    macro("giniTrendSlopeHi", _b + 1.96 * _se, "{:+.4f}")
    macro("giniTrendP", _p, "{:.3f}")
    macro("giniTrendNyears", len(_full))

fig, ax1 = plt.subplots(figsize=(7.0, 2.9))
m = ~ineq["partial"]
ax1.plot(ineq["year"], ineq["gini_rate"], "o-", color="#1f4e79", label="Gini (eset‑ráta)")
ax1.plot(ineq.loc[ineq.partial, "year"], ineq.loc[ineq.partial, "gini_rate"], "o",
         mfc="white", color="#1f4e79")
ax1.set_ylabel("Gini‑együttható"); ax1.set_xlabel("Év")
ax2 = ax1.twinx()
ax2.plot(ineq["year"], ineq["cv_rate"], "s--", color="#c0504d", label="Variációs koeff.")
ax2.set_ylabel("Variációs koefficiens"); ax2.grid(False)
ax1.set_title("Vármegyék közötti egyenlőtlenség a rotavírus eset‑rátában")
lines = ax1.get_lines()[:1] + ax2.get_lines()[:1]
ax1.legend(lines, [ln.get_label() for ln in lines], loc="upper right", fontsize=8)
fig.savefig(FIGDIR / "fig2_county_inequality.pdf"); plt.close(fig)

# cross-section county table 2019 vs 2024
def county_xs(y):
    cc = county_cases[county_cases["year"] == y].merge(county_pop, on="county_id", how="inner")
    cc["denom"] = [_cty_denom(c, y) for c in cc["county_id"]]
    cc["rate"] = cc["cases"] / cc["denom"] * 1e5
    return cc

xs19, xs24 = county_xs(PRE), county_xs(YEAR)
desc_tab = pd.DataFrame({
    "stat": ["Összes bejelentett eset", "Átlagos vármegyei eset‑ráta / 100e", "Szórás",
             "Minimum", "Maximum", "Max / min arány", "Gini (ráta)"],
    str(PRE): [xs19["cases"].sum(), xs19["rate"].mean(), xs19["rate"].std(ddof=1),
               xs19["rate"].min(), xs19["rate"].max(),
               xs19["rate"].max() / xs19["rate"].min(), gini(xs19["rate"].values)],
    str(YEAR): [xs24["cases"].sum(), xs24["rate"].mean(), xs24["rate"].std(ddof=1),
                xs24["rate"].min(), xs24["rate"].max(),
                xs24["rate"].max() / xs24["rate"].min(), gini(xs24["rate"].values)],
})
desc_tab.to_csv(RESULTS / "county_cross_section.csv", index=False)

# county <-> socio correlation (2024)
cc24 = county_xs(YEAR).copy()
cc24["jobseeker_rate"] = cc24["jobseekers"] / cc24["wap"] * 100
from scipy.stats import pearsonr, spearmanr  # noqa: E402
r_ps = pearsonr(cc24["rate"], cc24["jobseeker_rate"])
r_sp = spearmanr(cc24["rate"], cc24["jobseeker_rate"])
macro("countyBurdenSocioPearson", r_ps.statistic, "{:.2f}")
macro("countyBurdenSocioPearsonP", r_ps.pvalue, "{:.3f}")
macro("countyBurdenSocioSpearman", r_sp.statistic, "{:.2f}")

macro("epiYears", "2017--2026", "{}")
macro("nWeeksTotal", len(natw))
macro("casesPre", int(xs19["cases"].sum()))
macro("casesXs", int(xs24["cases"].sum()))
macro("giniPre", gini(xs19["rate"].values), "{:.3f}")
macro("giniXs", gini(xs24["rate"].values), "{:.3f}")
_glo, _ghi = boot_ci(lambda r: gini(r), xs24["rate"].values, reps=3000)
macro("giniXsLo", _glo, "{:.3f}")
macro("giniXsHi", _ghi, "{:.3f}")
# independent cross-check: OSAP annual county counts vs NNGYK weekly sums
if OSAPC is not None:
    _o = OSAPC.copy()
    _o["county_id"] = _o["county_name"].map(norm_county).map(county_id_by_norm)
    _oy = int(_o["year"].iloc[0])
    _m = (_o.dropna(subset=["county_id"])
          .merge(county_cases[county_cases["year"] == _oy], on="county_id", how="inner"))
    if len(_m) > 5:
        _r = pearsonr(_m["rotavirus_cases_osap"], _m["cases"])
        macro("osapWeeklyPearson", _r.statistic, "{:.3f}")
        macro("osapYear", str(_oy), "{}")
        macro("osapTotal", int(_m["rotavirus_cases_osap"].sum()))
        macro("weeklySumTotal", int(_m["cases"].sum()))
macro("maxminPre", xs19["rate"].max() / xs19["rate"].min(), "{:.1f}")
macro("maxminXs", xs24["rate"].max() / xs24["rate"].min(), "{:.1f}")
macro("csYear", str(YEAR), "{}")
macro("preYear", str(PRE), "{}")


# --------------------------------------------------------------------------- #
# 3. district burden model (population-weighted apportionment, +/-50% CI)
# --------------------------------------------------------------------------- #
print("[3] district burden ...")
dpop = (pop_year.dropna(subset=["district_id"])
        .groupby("district_id", as_index=False)
        .agg(pop=("wap", "sum"), jobseekers=("jobseekers", "sum")))
dpop["jobseeker_rate"] = dpop["jobseekers"] / dpop["pop"]
D = DISTRICTS.merge(dpop, on="district_id", how="left")
# districts with no NFSZ match: impute pop by county mean share (rare)
D["pop"] = D["pop"].fillna(D.groupby("county_id")["pop"].transform("median"))
D["jobseeker_rate"] = D["jobseeker_rate"].fillna(D["jobseeker_rate"].median())

cty_cases_y = (epi[epi["iso_year"] == YEAR].groupby("county_id", as_index=False)["value"]
               .sum().rename(columns={"value": "county_cases"}))
D = D.merge(cty_cases_y, on="county_id", how="left")
D["pop_share"] = D["pop"] / D.groupby("county_id")["pop"].transform("sum")
D["lambda"] = D["county_cases"] * D["pop_share"]
D["lambda_lo"] = D["lambda"] * (1 - CI_HW)
D["lambda_hi"] = D["lambda"] * (1 + CI_HW)

# --- real child-population denominator (KSH county 0-14, apportioned to the
#     district by its share of county working-age pop -> assumes age structure
#     is homogeneous within the county, the same assumption as the case split,
#     but now anchored to observed county child totals instead of a WA proxy).
POP_DENOM = "working-age proxy"
if HAVE_POPAGE:
    pa = POPAGE.copy()
    pa["county_id"] = pa["county_name"].map(norm_county).map(county_id_by_norm)
    c014 = (pa[(pa["age_group"] == "age_0_14") & (pa["year"] == YEAR)]
            .dropna(subset=["county_id"]).set_index("county_id")["population"])
    D["county_child_pop"] = D["county_id"].map(c014)
    D["pop_child"] = D["county_child_pop"] * D["pop_share"]
    # national 0-4 : 0-14 ratio (KSH age pyramid, ~1/3); documented assumption,
    # used only to express a per-1000 under-5 figure, not for the ranking.
    U5_OF_CHILD = 0.34
    D["pop_u5"] = D["pop_child"] * U5_OF_CHILD
    if D["pop_child"].notna().all():
        POP_DENOM = "KSH county 0-14 (apportioned)"
if POP_DENOM.startswith("KSH"):
    D["burden_rate"] = D["lambda"] / D["pop_child"] * 1e5   # per 100k children (0-14)
    D["burden_rate_u5"] = D["lambda"] / D["pop_u5"] * 1e3   # per 1000 under-5 (illustrative)
else:
    D["pop_child"] = D["pop"]
    D["pop_u5"] = D["pop"]
    D["burden_rate"] = D["lambda"] / D["pop"] * 1e5
    D["burden_rate_u5"] = D["burden_rate"]
macro("popDenom", "KSH vármegyei 0--14 éves népesség, járásra arányosítva"
      if POP_DENOM.startswith("KSH") else "járási munkavállalási korú népesség (proxy)", "{}")

# --- 290/2014 official complex development indicator + statutory beneficiary set
if HAVE_290:
    p290 = POP290.set_index("district_id")
    D["komplex_mutato"] = D["district_id"].map(p290["komplex_mutato"])
    D["kedvezmenyezett_290"] = D["district_id"].map(p290["kedvezmenyezett"]).fillna(0).astype(int)
    D["komplex_program_290"] = D["district_id"].map(p290["komplex_program"]).fillna(0).astype(int)
    # lower complex indicator = more deprived -> invert to a "deprivation" score
    D["deprivation_290"] = -zscore_np(D["komplex_mutato"].values)

D["evidence_class"] = "estimated"
D["confidence"] = "low"

# healthcare capacity: chronically vacant GP/paediatric practices, latest snapshot
ok = okfo[okfo["source_file"].str.contains("gp", case=False, na=False)].copy()
ok = ok[ok["snapshot_date"] == ok["snapshot_date"].max()]
ok["s_norm"] = ok["settlement_name"].map(norm_settlement)
ok["cty_norm"] = ok["county_name"].map(norm_county)
ok["county_id"] = ok["cty_norm"].map(county_id_by_norm)
ok = ok.merge(s2d_unique_cty, on=["s_norm", "county_id"], how="left")
vac = (ok.dropna(subset=["district_id"]).groupby("district_id", as_index=False)
       .agg(vacant_paed=("practice_type", lambda s: int(s.isin(["paediatric", "mixed"]).sum())),
            vacant_any=("practice_type", "size")))
D = D.merge(vac, on="district_id", how="left")
D[["vacant_paed", "vacant_any"]] = D[["vacant_paed", "vacant_any"]].fillna(0)
D["vacant_paed_practice_rate"] = D["vacant_paed"] / D["pop"] * 1e5
macro("okfoSnapshot", str(ok["snapshot_date"].max()), "{}")
macro("okfoVacantPaed", int(D["vacant_paed"].sum()))
macro("okfoDistrictsWithVacant", int((D["vacant_paed"] > 0).sum()))

D.to_csv(RESULTS / "district_burden.csv", index=False)
macro("nDistricts", N_DIST)
macro("burdenRateGini", gini(D["burden_rate"].values), "{:.3f}")
macro("jobseekerRateGini", gini(D["jobseeker_rate"].values), "{:.3f}")


# --------------------------------------------------------------------------- #
# 4. cost model
# --------------------------------------------------------------------------- #
print("[4] cost model ...")
P = {k: v for k, v in COSTS["parameters"].items()}


def pval(pid, which="base"):
    return float(P[pid][which])


# 2024 daily wage -> 2025 nominal level: explicit documented factor (config).
# The auto-collected KSH price-index parquet is multi-series and needs manual
# cleanup (see paper limitations), so it is NOT used as the deflator here.
defl_2024_to_2025 = float(CFG.get("wage_growth_2024_2025", 1.09))
macro("earningsDefl", defl_2024_to_2025, "{:.3f}")
# health-sector CPI 2024->2025 (KSH STADAT 1.1.1.3, COICOP 6), chained; the
# medical parameters are specified at 2025 price level, so this enters only as a
# documented robustness factor (see limitations).
macro("deflMed", DEFL_MED, "{:.3f}")


def cost_per_case(scn: dict) -> float:
    """scn: dict of parameter_id -> value (already sampled/level-set)."""
    c_inp = scn["hbcs_base_rate"] * scn["hbcs_weight_paed_gastroenteritis"]
    c_out = scn["outpatient_point_value"] * scn["outpatient_points_per_case"] + scn["gp_visit_cost"]
    h = scn["hospitalisation_rate_notified"]
    c_direct = h * c_inp + (1 - h) * c_out
    wage = scn["daily_gross_wage"] * defl_2024_to_2025
    prod = (scn["parental_work_loss_probability"] * min(scn["mean_parental_workdays_lost"],
            scn["working_days_per_year"]) * wage * (1 + scn["employer_contribution_rate"]))
    return c_direct + prod


base_scn = {k: pval(k, "base") for k in P}
C_CASE = cost_per_case(base_scn)
C_CASE_LO = cost_per_case({k: pval(k, "low") for k in P})
C_CASE_HI = cost_per_case({k: pval(k, "high") for k in P})
macro("costPerCase", C_CASE)
macro("costPerCaseLo", C_CASE_LO)
macro("costPerCaseHi", C_CASE_HI)

D["expected_cost"] = D["lambda"] * C_CASE
D["expected_cost_societal"] = D["lambda"] * base_scn["underreporting_multiplier"] * C_CASE
macro("totalExpectedCost", D["expected_cost"].sum())
macro("totalExpectedCostSoc", D["expected_cost_societal"].sum())

# cost parameter table
rows = []
for pid, p in P.items():
    rows.append({"param": pid, "desc": p["description"], "base": p["base"], "low": p["low"],
                 "high": p["high"], "unit": p.get("unit", ""), "evidence": p["evidence_class"],
                 "confidence": p["confidence"]})
pd.DataFrame(rows).to_csv(RESULTS / "cost_parameters.csv", index=False)


# --------------------------------------------------------------------------- #
# 5. need index (z-score + MPI ; robustness: weighted sum, minmax)
# --------------------------------------------------------------------------- #
print("[5] need index ...")
DIMS = NEEDCFG["dimensions"]
VARS = {d: v["variables"] for d, v in DIMS.items()}
DW = {d: v["weight"] for d, v in DIMS.items()}


def zscore(s):
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.mean()) / s.std(ddof=1)


def minmax(s):
    s = pd.to_numeric(s, errors="coerce")
    return (s - s.min()) / (s.max() - s.min())


def dim_score(df, dvars, method="z"):
    f = zscore if method == "z" else minmax
    return pd.concat([f(df[v]) for v in dvars], axis=1).mean(axis=1)


for d, dvars in VARS.items():
    D[f"score_{d}"] = dim_score(D, dvars, "z")

# MPI (Mazziotta-Pareto): rescale to mean 100 sd 10, mean minus penalty*cv
resc = {}
for d in VARS:
    z = D[f"score_{d}"]
    resc[d] = 100 + 10 * z
R = pd.DataFrame(resc)
wvec = np.array([DW[d] for d in VARS])
Mbar = (R.values * wvec).sum(axis=1) / wvec.sum()
Msd = np.sqrt(((R.values - Mbar[:, None]) ** 2 * wvec).sum(axis=1) / wvec.sum())
Mcv = Msd / Mbar
D["need_mpi"] = Mbar - Msd * Mcv  # negative penalty (non-compensatory)
D["need_score"] = minmax(D["need_mpi"])
# robustness variants
D["need_wsum"] = minmax(sum(DW[d] * minmax(D[f"score_{d}"]) for d in VARS))
D["need_rank_ws"] = minmax(sum(DW[d] * D[f"score_{d}"].rank() for d in VARS))
D["need_rank"] = D["need_score"].rank(ascending=False).astype(int)

sp_variants = pd.DataFrame({"mpi": D["need_score"], "wsum": D["need_wsum"], "rankws": D["need_rank_ws"]})
macro("needMpiWsumSpearman", spearmanr(sp_variants["mpi"], sp_variants["wsum"]).statistic, "{:.3f}")


def mpi_from_z(zcols: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """Mazziotta-Pareto index from z-scored dimension arrays -> minmax [0,1]."""
    dims = list(zcols)
    Rm = np.column_stack([100 + 10 * zcols[d] for d in dims])
    wv = np.array([weights[d] for d in dims])
    mbar = (Rm * wv).sum(1) / wv.sum()
    msd = np.sqrt(((Rm - mbar[:, None]) ** 2 * wv).sum(1) / wv.sum())
    m = mbar - msd * (msd / mbar)
    return (m - m.min()) / (m.max() - m.min())


_zbase = {d: zscore(D[f"score_{d}"]).values for d in VARS}

# --- external validation: composite need vs the official 290/2014 indicator
if HAVE_290 and D["komplex_mutato"].notna().all():
    r_ev = spearmanr(D["need_score"], -D["komplex_mutato"])
    r_ev_p = pearsonr(D["need_score"], D["deprivation_290"])
    macro("needVsOfficialSpearman", r_ev.statistic, "{:.2f}")
    macro("needVsOfficialSpearmanP", r_ev.pvalue, "{:.3f}")
    macro("needVsOfficialPearson", r_ev_p.statistic, "{:.2f}")
    # need index rebuilt with the official indicator replacing the jobseeker proxy
    z290 = dict(_zbase)
    z290["socioeconomic"] = zscore_np(D["deprivation_290"].values)
    D["need_score_290"] = mpi_from_z(z290, DW)
    macro("needSwapSpearman",
          spearmanr(D["need_score"], D["need_score_290"]).statistic, "{:.3f}")

# --- specification-robustness: leave-one-dimension-out + method swaps
k_dec_spec = max(int(round(TOP_DEC * N_DIST)), 1)
spec_scores = {"mpi_z": D["need_score"].values,
               "wsum_minmax": D["need_wsum"].values,
               "rank_ws": D["need_rank_ws"].values}
for drop in VARS:
    keep = {d: _zbase[d] for d in VARS if d != drop}
    kw = {d: DW[d] for d in keep}
    spec_scores[f"drop_{drop}"] = mpi_from_z(keep, kw)
if "need_score_290" in D:
    spec_scores["socio_290"] = D["need_score_290"].values
spec_top = np.zeros(N_DIST, int)
for v in spec_scores.values():
    spec_top[np.argsort(-v)[:k_dec_spec]] += 1
D["spec_top_count"] = spec_top
D["spec_n_specs"] = len(spec_scores)
robust_spec = D[D["spec_top_count"] == len(spec_scores)]
macro("nSpecs", len(spec_scores))
macro("nSpecRobust", int(len(robust_spec)))
D[["district_name", "county_name", "need_score", "spec_top_count", "spec_n_specs"]] \
    .sort_values("spec_top_count", ascending=False).to_csv(RESULTS / "spec_robust.csv", index=False)

D.sort_values("need_rank").to_csv(RESULTS / "need_index.csv", index=False)

top10 = D.sort_values("need_rank").head(10)[
    ["district_name", "county_name", "need_score", "score_disease", "score_socioeconomic",
     "score_healthcare", "lambda", "jobseeker_rate", "vacant_paed"]]
top10.to_csv(RESULTS / "need_top10.csv", index=False)

# --------------------------------------------------------------------------- #
# 6. allocation scenarios
# --------------------------------------------------------------------------- #
print("[6] allocation ...")
# existing local funding (municipal) -> district (only a handful of Budapest ker.)
muni = json.loads((INTER / "jogtar" / "municipal_vaccination_support.json").read_text(encoding="utf-8"))
L = pd.Series(0.0, index=D["district_id"].values)
muni_map = {}
for m in muni:
    key = m.get("municipality_key", "")
    amt = m.get("support_amount_huf")
    mm = re.match(r"budapest_(\d{2})", key)
    if mm and amt:
        dname = f"budapest {int(mm.group(1)):02d}"
        row = D[D["district_name"].map(norm_settlement) == dname]
        if len(row):
            # amount is per child; scale by district pop share of u5 ~ proportional to pop
            muni_map[row.iloc[0]["district_id"]] = amt
macro("nMuniSupport", len([m for m in muni if m.get("support_amount_huf")]))
macro("nMuniMentionRota", len([m for m in muni if m.get("mentions_rotavirus")]))

D["existing_local_funding"] = D["district_id"].map(muni_map).fillna(0.0)
# turn per-child amount into a notional district envelope (amount * modelled cases as a proxy scale)
D["L_envelope"] = D["existing_local_funding"] * D["lambda"].clip(lower=1)


def normalise(raw, budget=BUDGET):
    raw = np.clip(np.asarray(raw, float), 0, None)
    tot = raw.sum()
    return raw / tot * budget if tot > 0 else np.zeros_like(raw)


A = pd.DataFrame({"district_id": D["district_id"].values})
A["s0_statusquo"] = D["L_envelope"].values
A["s1_percapita"] = normalise(D["pop"].values)
A["s2_epi"] = normalise(D["lambda"].values)
A["s3_socio"] = normalise(D["pop"].values * (D["score_socioeconomic"].values - D["score_socioeconomic"].min() + 0.01))
A["s4_capacity"] = normalise(D["pop"].values * (D["score_healthcare"].values - D["score_healthcare"].min() + 0.01))
A["s5_fullneed"] = normalise(D["expected_cost"].values * (1 + ETA * D["need_score"].values))
A["s6_costgap"] = np.clip(D["expected_cost"].values - D["L_envelope"].values, 0, None)  # not normalised

# scenario 7: statutory threshold -- the REAL 290/2014 beneficiary districts
if HAVE_290 and "kedvezmenyezett_290" in D:
    proxy = False
    D["eligible_290"] = D["kedvezmenyezett_290"] == 1
else:
    proxy = True
    thr = D["score_socioeconomic"].quantile(2 / 3)
    D["eligible_290"] = D["score_socioeconomic"] >= thr
macro("statProxy", "nem (a 290/2014.~Korm.~r.\\ 3.~melléklete betöltve)" if not proxy
      else "igen (proxy: a szocioökonómiai depriváltság legrosszabb harmada)", "{}")
macro("nEligibleProxy", int(D["eligible_290"].sum()))
if not proxy:
    macro("nKomplexProgram", int((D["komplex_program_290"] == 1).sum()))
raw7 = np.where(D["eligible_290"].values, D["pop"].values, 0.0)
A["s7_statutory"] = normalise(raw7)

SCN_LABELS = {
    "s0_statusquo": "0 · Status quo",
    "s1_percapita": "1 · Egyenlő fejkvóta",
    "s2_epi": "2 · Epidemiológiai",
    "s3_socio": "3 · Szocioökonómiai",
    "s4_capacity": "4 · Kapacitásalapú",
    "s5_fullneed": "5 · Teljes szükségletalapú",
    "s6_costgap": "6 · Költségrés",
    "s7_statutory": "7 · Jogszabályi küszöb",
}
SCN = list(SCN_LABELS)
NORMED = [s for s in SCN if s not in ("s6_costgap",)]

A = A.merge(D[["district_id", "district_name", "county_id", "county_name", "nuts3_code",
               "need_score", "need_rank", "score_socioeconomic", "pop", "lambda"]], on="district_id")
A.to_csv(RESULTS / "allocation.csv", index=False)

macro("budgetHuf", BUDGET)
macro("statusQuoTotal", A["s0_statusquo"].sum())
macro("costGapTotal", A["s6_costgap"].sum())
macro("statusQuoNonZero", int((A["s0_statusquo"] > 0).sum()))

# Lorenz curves
def lorenz(x):
    x = np.sort(np.asarray(x, float))
    c = np.cumsum(x)
    c = np.insert(c, 0, 0) / c[-1] if c[-1] > 0 else np.linspace(0, 1, len(x) + 1)
    p = np.linspace(0, 1, len(x) + 1)
    return p, c


fig, ax = plt.subplots(figsize=(4.6, 4.4))
ax.plot([0, 1], [0, 1], color="grey", lw=0.8, ls=":")
for s in ["s1_percapita", "s2_epi", "s3_socio", "s5_fullneed", "s7_statutory"]:
    p, c = lorenz(A[s].values)
    ax.plot(p, c, lw=1.2, label=SCN_LABELS[s])
ax.set_xlabel("Járások kumulált hányada (allokáció szerint rendezve)")
ax.set_ylabel("A keret kumulált hányada")
ax.set_title("Az allokáció Lorenz‑görbéi forgatókönyvenként")
ax.legend(fontsize=7, loc="upper left")
fig.savefig(FIGDIR / "fig5_lorenz.pdf"); plt.close(fig)


# --------------------------------------------------------------------------- #
# 7. equity metrics
# --------------------------------------------------------------------------- #
print("[7] equity ...")
def concentration_index(aid, rank_var):
    """CI of `aid` ordered by ascending `rank_var` (need). +1 => all to highest-need."""
    df = pd.DataFrame({"a": np.asarray(aid, float), "r": np.asarray(rank_var, float)})
    df = df.sort_values("r").reset_index(drop=True)
    n = len(df)
    a = df["a"].values
    if a.sum() == 0:
        return np.nan
    frac_rank = (np.arange(1, n + 1) - 0.5) / n
    mu = a.mean()
    return float(2 / (n * mu) * np.sum((frac_rank - frac_rank.mean()) * (a - mu)))


def theil(x, groups):
    x = np.asarray(x, float)
    m = x > 0
    x, groups = x[m], np.asarray(groups)[m]
    mu = x.mean()
    total = np.mean((x / mu) * np.log(x / mu))
    between = 0.0
    within = 0.0
    for g in np.unique(groups):
        xi = x[groups == g]
        si = xi.sum() / x.sum()
        mui = xi.mean()
        between += si * np.log(mui / mu)
        within += si * np.mean((xi / mui) * np.log(xi / mui))
    return total, between, within


eq_rows = []
for s in SCN:
    aid = A[s].values
    t, b, w = theil(aid, A["county_id"].values)
    q = pd.qcut(A["need_score"].rank(method="first"), 5, labels=False)
    worst_q_share = aid[q == 4].sum() / aid.sum() if aid.sum() else np.nan
    eq_rows.append({
        "scenario": s, "label": SCN_LABELS[s],
        "gini_aid": gini(aid),
        "ci_need": concentration_index(aid, A["need_score"].values),
        "ci_socio": concentration_index(aid, A["score_socioeconomic"].values),
        "kakwani_need": concentration_index(aid, A["need_score"].values) - gini(A["need_score"].values),
        "theil_between": b, "theil_within": w,
        "theil_between_share": b / t if t else np.nan,
        "worst_quintile_share": worst_q_share,
    })
EQ = pd.DataFrame(eq_rows)
EQ.to_csv(RESULTS / "equity.csv", index=False)
# LaTeX control words cannot contain digits -> word tags per scenario
TAGW = {"s0_statusquo": "Sq", "s1_percapita": "Pc", "s2_epi": "Epi", "s3_socio": "Soc",
        "s4_capacity": "Cap", "s5_fullneed": "Full", "s6_costgap": "Gap", "s7_statutory": "Stat"}
for s in SCN:
    tg = TAGW[s]
    row = EQ[EQ.scenario == s].iloc[0]
    macro(f"ci{tg}", row["ci_need"], "{:+.3f}")
    macro(f"kak{tg}", row["kakwani_need"], "{:+.3f}")
    macro(f"wq{tg}", 100 * row["worst_quintile_share"], "{:.1f}")
    macro(f"gini{tg}", row["gini_aid"], "{:.3f}")
    macro(f"tb{tg}", 100 * row["theil_between_share"], "{:.0f}")

# bootstrap 95% CIs (resample districts) for the headline progressivity metrics
_needg = gini(A["need_score"].values)
eqci_rows = []
for s in ("s1_percapita", "s2_epi", "s5_fullneed", "s7_statutory"):
    tg = TAGW[s]
    lo_ci, hi_ci = boot_ci(lambda a, n: concentration_index(a, n),
                           A[s].values, A["need_score"].values, reps=2000)
    lo_k, hi_k = boot_ci(lambda a, n: concentration_index(a, n) - gini(n),
                         A[s].values, A["need_score"].values, reps=2000)
    macro(f"ci{tg}Lo", lo_ci, "{:+.3f}")
    macro(f"ci{tg}Hi", hi_ci, "{:+.3f}")
    macro(f"kak{tg}Lo", lo_k, "{:+.3f}")
    macro(f"kak{tg}Hi", hi_k, "{:+.3f}")
    eqci_rows.append({"scenario": s, "label": SCN_LABELS[s],
                      "ci_need": EQ.loc[EQ.scenario == s, "ci_need"].iloc[0],
                      "ci_lo": lo_ci, "ci_hi": hi_ci,
                      "kakwani": EQ.loc[EQ.scenario == s, "kakwani_need"].iloc[0],
                      "kak_lo": lo_k, "kak_hi": hi_k})
pd.DataFrame(eqci_rows).to_csv(RESULTS / "equity_bootstrap.csv", index=False)

# Spearman + Jaccard across normalised scenarios
sp = A[NORMED].corr(method="spearman")
sp.to_csv(RESULTS / "scenario_spearman.csv")
K = 20  # top set
tops = {s: set(A.sort_values(s, ascending=False).head(K)["district_id"]) for s in NORMED}
jac = pd.DataFrame(index=NORMED, columns=NORMED, dtype=float)
for a1 in NORMED:
    for a2 in NORMED:
        u = tops[a1] | tops[a2]
        jac.loc[a1, a2] = len(tops[a1] & tops[a2]) / len(u) if u else np.nan
jac.to_csv(RESULTS / "scenario_jaccard.csv")
macro("jaccardEpiFull", jac.loc["s2_epi", "s5_fullneed"], "{:.2f}")
macro("spearmanEpiSocio", sp.loc["s2_epi", "s3_socio"], "{:.2f}")

# equity dot plot with PSA error bars computed below -> placeholder now
fig, ax = plt.subplots(figsize=(6.6, 3.0))
order = EQ.sort_values("ci_need")
ax.errorbar(order["ci_need"], range(len(order)), fmt="o", color="#1f4e79")
ax.set_yticks(range(len(order))); ax.set_yticklabels(order["label"], fontsize=8)
ax.axvline(0, color="grey", lw=0.8)
ax.set_xlabel("Koncentrációs index (allokáció | szükséglet‑rang)  —  pozitív = progresszív")
ax.set_title("Az allokáció progresszivitása a szükséglethez képest")
fig.savefig(FIGDIR / "fig6_concentration.pdf"); plt.close(fig)


# --------------------------------------------------------------------------- #
# 8. sensitivity
# --------------------------------------------------------------------------- #
print("[8] sensitivity ...")
LAMBDA_TOT = float(D["lambda"].sum())
UR = base_scn["underreporting_multiplier"]


def societal_cost_mrd(scn_costs, burden_mult=1.0):
    """Total societal expected cost (Mrd HUF) = Sum lambda * underreporting * c_case."""
    return LAMBDA_TOT * burden_mult * scn_costs["underreporting_multiplier"] * cost_per_case(scn_costs) / 1e9


# 8a  one-way tornado on the total societal expected cost (this IS cost-sensitive;
#     the s5 allocation *share* is not, because cost scales all districts uniformly)
base_cost_mrd = societal_cost_mrd(base_scn)
macro("baseCostMrd", base_cost_mrd, "{:.2f}")
tor_params = ["hbcs_base_rate", "hbcs_weight_paed_gastroenteritis", "hospitalisation_rate_notified",
              "underreporting_multiplier", "daily_gross_wage", "parental_work_loss_probability",
              "mean_parental_workdays_lost", "outpatient_points_per_case", "gp_visit_cost"]
PARAM_HU = {
    "hbcs_base_rate": "Fekvőbeteg alapdíj (Ft/súlyszám)",
    "hbcs_weight_paed_gastroenteritis": "HBCs‑súlyszám (gyermek GE)",
    "hospitalisation_rate_notified": "Kórházi felvételi arány",
    "underreporting_multiplier": "Aluljelentési szorzó",
    "daily_gross_wage": "Napi bruttó bér",
    "parental_work_loss_probability": "Szülői munkakiesés valószínűsége",
    "mean_parental_workdays_lost": "Kiesett munkanapok / eset",
    "outpatient_points_per_case": "Járóbeteg pont / eset",
    "gp_visit_cost": "Háziorvosi vizit költsége",
    "eta_010_100": "Szuk: rugalmassag eta (0,1-1,0)",
    "burden_ci": "Betegségteher ±50% sáv",
}
tornado = []
for pid in tor_params:
    lo = dict(base_scn); lo[pid] = pval(pid, "low")
    hi = dict(base_scn); hi[pid] = pval(pid, "high")
    tornado.append({"param": PARAM_HU[pid], "low": societal_cost_mrd(lo), "high": societal_cost_mrd(hi)})
tornado.append({"param": PARAM_HU["burden_ci"], "low": societal_cost_mrd(base_scn, 1 - CI_HW),
                "high": societal_cost_mrd(base_scn, 1 + CI_HW)})
TOR = pd.DataFrame(tornado)
TOR["spread"] = (TOR["high"] - TOR["low"]).abs()
TOR = TOR.sort_values("spread")
TOR.to_csv(RESULTS / "tornado.csv", index=False)

fig, ax = plt.subplots(figsize=(6.6, 3.2))
y = range(len(TOR))
ax.hlines(y, TOR["low"], TOR["high"], color="#1f4e79", lw=7, alpha=0.75)
ax.axvline(base_cost_mrd, color="#c0504d", lw=1)
ax.set_yticks(list(y)); ax.set_yticklabels(TOR["param"], fontsize=8)
ax.set_xlabel("Teljes társadalmi várható költség (Mrd Ft) — alap: {:.2f}".format(base_cost_mrd))
ax.set_title("Egyváltozós érzékenység (tornádó)")
fig.savefig(FIGDIR / "fig7_tornado.pdf"); plt.close(fig)

# 8a-note: the s5 worst-need-quintile share depends only on eta and the weights
q_need = pd.qcut(pd.Series(D["need_score"].values).rank(method="first"), 5, labels=False).values
eta_rows = []
for e in (0.10, 0.25, 0.50, 0.75, 1.00):
    raw = normalise(D["expected_cost"].values * (1 + e * D["need_score"].values))
    eta_rows.append({"eta": e, "worst_q_share": raw[q_need == 4].sum() / raw.sum(),
                     "ci_need": concentration_index(raw, D["need_score"].values)})
ETAS = pd.DataFrame(eta_rows)
ETAS.to_csv(RESULTS / "eta_scan.csv", index=False)
macro("etaLoShare", 100 * ETAS.iloc[0]["worst_q_share"], "{:.1f}")
macro("etaHiShare", 100 * ETAS.iloc[-1]["worst_q_share"], "{:.1f}")

# 8b  PSA: (i) cost uncertainty -> societal-cost distribution;
#          (ii) allocation progressivity under joint cost + per-district burden
#               noise + eta + Dirichlet weights
def sample_param(pid):
    b, lo, hi = pval(pid, "base"), pval(pid, "low"), pval(pid, "high")
    if b <= 0:
        return b
    if pid in ("hospitalisation_rate_notified", "parental_work_loss_probability",
               "vaccine_efficacy", "employer_contribution_rate"):
        s = 40.0
        a = max(b * s, 1e-3); bb = max((1 - b) * s, 1e-3)
        return float(np.clip(rng.beta(a, bb), lo * 0.5, min(hi * 1.2, 0.999)))
    cvv = max((hi - lo) / (3.92 * b), 0.05)
    k = 1.0 / cvv ** 2
    return float(rng.gamma(k, b / k))


base_w = np.array([DW[d] for d in VARS])
zmat = np.column_stack([zscore(D[f"score_{d}"]).values for d in VARS])
need_lo, need_hi = D["need_score"].min(), D["need_score"].max()
psa_rows = []
for _ in range(PSA_DRAWS):
    scn = {k: sample_param(k) for k in P}
    bmult = float(rng.lognormal(0.0, 0.20))
    cost_mrd = societal_cost_mrd(scn, bmult)
    # allocation: independent per-district burden noise (~ +/-50% as lognormal),
    # eta ~ U(0.2,1.0), Dirichlet-resampled dimension weights
    e = float(rng.uniform(0.2, 1.0))
    w = rng.dirichlet(base_w / base_w.sum() * DIR_CONC)
    need_draw = (zmat @ w)
    need_draw = (need_draw - need_draw.min()) / (need_draw.max() - need_draw.min())
    lam_draw = D["lambda"].values * rng.lognormal(0.0, 0.35, size=N_DIST)
    raw = normalise(lam_draw * cost_per_case(scn) * (1 + e * need_draw))
    psa_rows.append({
        "cost_mrd": cost_mrd,
        "worst_q_share": raw[q_need == 4].sum() / raw.sum(),
        "ci_need": concentration_index(raw, D["need_score"].values),
    })
PSA = pd.DataFrame(psa_rows)
PSA.to_csv(RESULTS / "psa.csv", index=False)
macro("psaCostMean", PSA["cost_mrd"].mean(), "{:.2f}")
macro("psaCostLo", PSA["cost_mrd"].quantile(0.025), "{:.2f}")
macro("psaCostHi", PSA["cost_mrd"].quantile(0.975), "{:.2f}")
macro("psaWorstQMean", 100 * PSA["worst_q_share"].mean(), "{:.1f}")
macro("psaWorstQLo", 100 * PSA["worst_q_share"].quantile(0.025), "{:.1f}")
macro("psaWorstQHi", 100 * PSA["worst_q_share"].quantile(0.975), "{:.1f}")
macro("psaCiMean", PSA["ci_need"].mean(), "{:+.3f}")
macro("psaCiLo", PSA["ci_need"].quantile(0.025), "{:+.3f}")
macro("psaCiHi", PSA["ci_need"].quantile(0.975), "{:+.3f}")

fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.9))
axes[0].hist(PSA["cost_mrd"], bins=40, color="#1f4e79", alpha=0.85)
axes[0].axvline(base_cost_mrd, color="#c0504d", lw=1)
axes[0].set_xlabel("Teljes társadalmi várható költség (Mrd Ft)")
axes[0].set_ylabel("Húzások")
axes[0].set_title("PSA: költségbizonytalanság")
axes[1].hist(PSA["ci_need"], bins=40, color="#1f4e79", alpha=0.85)
axes[1].axvline(0, color="grey", lw=0.8)
axes[1].set_xlabel("Koncentrációs index (allokáció | szükséglet)")
axes[1].set_title("PSA: progresszivitás (5. forgatókönyv)")
fig.savefig(FIGDIR / "fig7b_psa.pdf"); plt.close(fig)

# 8c Dirichlet weight resampling -> P(top decile need)
base_w = np.array([DW[d] for d in VARS])
k_dec = max(int(round(TOP_DEC * N_DIST)), 1)
zmat = np.column_stack([zscore(D[f"score_{d}"]).values for d in VARS])
counts = np.zeros(N_DIST)
for _ in range(W_DRAWS):
    w = rng.dirichlet(base_w / base_w.sum() * DIR_CONC)
    score = zmat @ w
    top = np.argsort(-score)[:k_dec]
    counts[top] += 1
D["p_top_decile"] = counts / W_DRAWS
robust = D[D["p_top_decile"] >= ROBUST_T].sort_values("p_top_decile", ascending=False)
robust[["district_name", "county_name", "p_top_decile", "need_score", "lambda",
        "jobseeker_rate", "vacant_paed"]].to_csv(RESULTS / "robust_priority.csv", index=False)
macro("nRobustPriority", len(robust))
macro("robustThreshold", int(ROBUST_T * 100))
macro("topDecileK", k_dec)

fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.1), width_ratios=[2, 1])
srt = D.sort_values("p_top_decile", ascending=False).reset_index(drop=True)
axes[0].plot(range(N_DIST), srt["p_top_decile"], color="#1f4e79")
axes[0].axhline(ROBUST_T, color="#c0504d", ls="--", lw=1)
axes[0].fill_between(range(N_DIST), 0, srt["p_top_decile"],
                     where=srt["p_top_decile"] >= ROBUST_T, color="#c0504d", alpha=0.3)
axes[0].set_xlabel("Járások (P szerint rendezve)")
axes[0].set_ylabel("P(felső decilis a szükségletben)")
axes[0].set_title("Dirichlet‑súlyújramintavétel")
axes[1].barh(range(len(robust.head(12))), robust.head(12)["p_top_decile"][::-1], color="#1f4e79")
axes[1].set_yticks(range(len(robust.head(12))))
axes[1].set_yticklabels(robust.head(12)["district_name"][::-1], fontsize=7)
axes[1].set_xlabel("P"); axes[1].set_title("Robusztus prioritás")
fig.savefig(FIGDIR / "fig8_dirichlet.pdf"); plt.close(fig)


# --------------------------------------------------------------------------- #
# 9. policy evaluation
# --------------------------------------------------------------------------- #
print("[9] policy evaluation ...")
need_top_q = set(A.sort_values("need_score", ascending=False)
                 .head(int(round(TOP_SHARE * N_DIST)))["district_id"])
elig = set(D[D["eligible_290"]]["district_id"])
inter = need_top_q & elig
union = need_top_q | elig
macro("needTopQn", len(need_top_q))
macro("policyJaccard", len(inter) / len(union) if union else 0.0, "{:.2f}")
macro("needTopInElig", 100 * len(inter) / len(need_top_q) if need_top_q else 0.0, "{:.0f}")

# municipal support vs need
D["muni_support"] = D["district_id"].map(muni_map).fillna(0.0)
ci_muni = concentration_index(D["muni_support"].values, D["need_score"].values) \
    if D["muni_support"].sum() > 0 else np.nan
macro("ciMuni", ci_muni, "{:+.3f}")
macro("nDistrictsMuni", int((D["muni_support"] > 0).sum()))

# redistribution s2 vs s1 by NUTS3/county
red = A.groupby("county_name", as_index=False).agg(s1=("s1_percapita", "sum"),
                                                   s2=("s2_epi", "sum"))
red["delta"] = red["s2"] - red["s1"]
red = red.sort_values("delta")
red.to_csv(RESULTS / "redistribution_s2_vs_s1.csv", index=False)

fig, ax = plt.subplots(figsize=(6.4, 4.2))
colors = ["#c0504d" if d < 0 else "#4f81bd" for d in red["delta"]]
ax.barh(range(len(red)), red["delta"] / 1e6, color=colors)
ax.set_yticks(range(len(red))); ax.set_yticklabels(red["county_name"], fontsize=7)
ax.axvline(0, color="grey", lw=0.8)
ax.set_xlabel("Változás (millió Ft): 2. (epidemiológiai) − 1. (fejkvóta)")
ax.set_title("Újraelosztási hatás vármegyénként")
fig.savefig(FIGDIR / "fig9_redistribution.pdf"); plt.close(fig)


# --------------------------------------------------------------------------- #
# 9b. external validation: composite need vs the official 290/2014 indicator
# --------------------------------------------------------------------------- #
if HAVE_290 and D["komplex_mutato"].notna().all():
    print("[9b] external validation vs 290/2014 ...")
    fig, ax = plt.subplots(figsize=(5.2, 4.0))
    xcol = D["komplex_mutato"].values
    ycol = D["need_score"].values
    elig = D["eligible_290"].values
    ax.scatter(xcol[~elig], ycol[~elig], s=14, color="#4f81bd", alpha=0.7, label="Nem kedvezményezett")
    ax.scatter(xcol[elig], ycol[elig], s=16, color="#c0504d", alpha=0.8, label="Kedvezményezett (290/2014)")
    bb, aa = np.polyfit(xcol, ycol, 1)
    xs_ = np.linspace(xcol.min(), xcol.max(), 50)
    ax.plot(xs_, aa + bb * xs_, color="grey", lw=1, ls="--")
    ax.set_xlabel("290/2014 komplex fejlettségi mutató  (kisebb = deprivált)")
    ax.set_ylabel("Összetett szükségletindex (MPI)")
    ax.set_title("Külső érvényesség: szükségletindex vs.\nhivatalos fejlettségi mutató")
    ax.legend(fontsize=7)
    fig.savefig(FIGDIR / "fig10_external_validation.pdf"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 9c. two-way sensitivity: need elasticity (eta) x under-reporting multiplier
#     -> redistribution magnitude vs the per-capita benchmark
# --------------------------------------------------------------------------- #
print("[9c] two-way sensitivity (eta x under-reporting) ...")
eta_grid = [0.10, 0.25, 0.50, 0.75, 1.00, 1.50]
ur_grid = [3.0, 5.0, 8.0, 12.0, 15.0]
pc = normalise(D["pop"].values)
tw = np.zeros((len(ur_grid), len(eta_grid)))
twci = np.zeros_like(tw)
for i, ur in enumerate(ur_grid):
    for j, e in enumerate(eta_grid):
        raw = normalise(D["lambda"].values * ur * C_CASE * (1 + e * D["need_score"].values))
        tw[i, j] = np.abs(raw - pc).sum() / BUDGET / 2       # share of budget reshuffled
        twci[i, j] = concentration_index(raw, D["need_score"].values)
pd.DataFrame(tw, index=[f"UR={u:g}" for u in ur_grid],
             columns=[f"eta={e:g}" for e in eta_grid]).to_csv(RESULTS / "twoway_reshuffle.csv")
pd.DataFrame(twci, index=[f"UR={u:g}" for u in ur_grid],
             columns=[f"eta={e:g}" for e in eta_grid]).to_csv(RESULTS / "twoway_ci.csv")
macro("twoWayCiMin", twci.min(), "{:+.3f}")
macro("twoWayCiMax", twci.max(), "{:+.3f}")
macro("twoWayReshufMin", 100 * tw.min(), "{:.1f}")
macro("twoWayReshufMax", 100 * tw.max(), "{:.1f}")

fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.1))
for ax, M, ttl, fmt in ((axes[0], tw * 100, "Átcsoportosított keret (%)", "%.0f"),
                        (axes[1], twci, "Koncentrációs index", "%.2f")):
    im = ax.imshow(M, aspect="auto", cmap="YlGnBu", origin="lower")
    ax.set_xticks(range(len(eta_grid))); ax.set_xticklabels([f"{e:g}" for e in eta_grid], fontsize=7)
    ax.set_yticks(range(len(ur_grid))); ax.set_yticklabels([f"{u:g}" for u in ur_grid], fontsize=7)
    ax.set_xlabel("szükségleti rugalmasság $\\eta$"); ax.set_ylabel("aluljelentési szorzó")
    ax.set_title(ttl, fontsize=9)
    for (yy, xx), v in np.ndenumerate(M):
        ax.text(xx, yy, fmt % v, ha="center", va="center", fontsize=6.5)
fig.tight_layout()
fig.savefig(FIGDIR / "fig11_twoway.pdf"); plt.close(fig)

# --------------------------------------------------------------------------- #
# 9d. cost-effectiveness / break-even of a need-targeted vaccination subsidy
# --------------------------------------------------------------------------- #
print("[9d] cost-effectiveness / break-even ...")
vp = base_scn["vaccine_course_price"] + base_scn["vaccine_administration_cost"]
veff = base_scn["vaccine_efficacy"]
UPTAKE_GAIN = float(CFG.get("subsidy_uptake_gain", 0.60))  # documented assumption
UR = base_scn["underreporting_multiplier"]
# steady-state annual comparison (both sides are perpetual annual flows, so no
# discounting): subsidise each birth cohort at +UPTAKE_GAIN coverage; in steady
# state the whole under-5 population carries that extra coverage.
D["birth_cohort"] = D["pop_child"] / 15.0
D["subsidy_cost"] = D["birth_cohort"] * UPTAKE_GAIN * vp
D["averted_societal"] = (D["lambda"] * UR * C_CASE) * UPTAKE_GAIN * veff
D["net_benefit"] = D["averted_societal"] - D["subsidy_cost"]
D["benefit_cost_ratio"] = D["averted_societal"] / D["subsidy_cost"].clip(lower=1)
ce = D.sort_values("need_score", ascending=False)[
    ["district_name", "county_name", "need_score", "birth_cohort", "subsidy_cost",
     "averted_societal", "net_benefit", "benefit_cost_ratio"]]
ce.to_csv(RESULTS / "cost_effectiveness.csv", index=False)
macro("ceUptakeGain", 100 * UPTAKE_GAIN, "{:.0f}")
macro("ceBcrMedian", D["benefit_cost_ratio"].median(), "{:.2f}")
macro("ceNPositive", int((D["net_benefit"] > 0).sum()))
top_need = D.sort_values("need_score", ascending=False).head(int(round(TOP_SHARE * N_DIST)))
macro("ceBcrTopNeed", top_need["benefit_cost_ratio"].median(), "{:.2f}")
macro("ceNetTopNeedMrd", top_need["net_benefit"].sum() / 1e9, "{:.2f}")

fig, ax = plt.subplots(figsize=(6.2, 3.4))
srt = D.sort_values("need_score")
ax.scatter(srt["need_score"], srt["benefit_cost_ratio"], s=14,
           c=np.where(srt["eligible_290"], "#c0504d", "#4f81bd"), alpha=0.75)
ax.axhline(1.0, color="grey", lw=0.9, ls="--")
ax.set_xlabel("Összetett szükségletindex")
ax.set_ylabel("Haszon/költség arány")
ax.set_title("Egy szükségletarányos oltástámogatás megtérülése járásonként\n"
             "(piros = 290/2014 kedvezményezett)")
fig.savefig(FIGDIR / "fig12_costeffectiveness.pdf"); plt.close(fig)


# --------------------------------------------------------------------------- #
# 9e. national context: rotavirus vs a vaccine-preventable comparator
# --------------------------------------------------------------------------- #
if ANN is not None and {"rotavirus", "varicella"}.issubset(ANN.columns):
    print("[9e] national annual context ...")
    a = ANN.dropna(subset=["rotavirus"]).sort_values("year")
    fig, ax = plt.subplots(figsize=(7.0, 2.9))
    ax.plot(a["year"], a["rotavirus"], "o-", color="#c0504d", label="Rotavírus (nem támogatott oltás)")
    if a["varicella"].notna().any():
        ax2 = ax.twinx()
        ax2.plot(a["year"], a["varicella"], "s--", color="#1f4e79",
                 label="Bárányhimlő (2019-től kötelező oltás)")
        ax2.set_ylabel("Bárányhimlő, bejelentett eset"); ax2.grid(False)
    ax.set_ylabel("Rotavírus, bejelentett eset"); ax.set_xlabel("Év")
    ax.axvspan(2019, 2019.01, color="#1f4e79", alpha=0)  # anchor
    ax.axvline(2019, color="#1f4e79", lw=0.8, ls=":")
    ax.set_title("Országos bejelentett esetszám: rotavírus vs. bárányhimlő, 2012–2025")
    lines = ax.get_lines()[:1] + (ax2.get_lines()[:1] if a["varicella"].notna().any() else [])
    ax.legend(lines, [ln.get_label() for ln in lines], fontsize=7, loc="upper center")
    fig.savefig(FIGDIR / "fig13_national_context.pdf"); plt.close(fig)
    macro("rotaAnnPre", int(a.loc[a.year == 2019, "rotavirus"].iloc[0]))
    macro("rotaAnnXs", int(a.loc[a.year == 2024, "rotavirus"].iloc[0]))
    macro("variAnnPre", int(a.loc[a.year == 2019, "varicella"].iloc[0]))
    macro("variAnnXs", int(a.loc[a.year == 2024, "varicella"].iloc[0]))
    macro("annYearMin", str(int(a["year"].min())), "{}")


# --------------------------------------------------------------------------- #
# 10. need-index composition + priority/eligibility overlap (non-spatial;
#     the collected OSM boundary files are HTML listing pages, not GeoJSON)
# --------------------------------------------------------------------------- #
print("[10] composition & overlap figures ...")

# fig 4 — the 30 highest-need districts, stacked weighted dimension contributions
srtN = D.sort_values("need_score", ascending=False).head(30).iloc[::-1]
contrib = {d: DW[d] * (srtN[f"score_{d}"] - D[f"score_{d}"].min()) for d in VARS}
fig, ax = plt.subplots(figsize=(6.6, 5.2))
left = np.zeros(len(srtN))
dim_hu = {"disease": "Betegségteher", "socioeconomic": "Szocioökonómiai", "healthcare": "Kapacitáshiány"}
palette = {"disease": "#c0504d", "socioeconomic": "#1f4e79", "healthcare": "#4f81bd"}
for d in VARS:
    ax.barh(range(len(srtN)), contrib[d].values, left=left, color=palette[d], label=dim_hu[d])
    left += contrib[d].values
ax.set_yticks(range(len(srtN)))
ax.set_yticklabels([f"{n} ({c})" for n, c in zip(srtN["district_name"], srtN["county_name"])], fontsize=6.5)
ax.set_xlabel("Súlyozott dimenzió‑hozzájárulás (z‑score, eltolva)")
ax.set_title("A 30 legmagasabb szükségletindexű járás összetétele")
ax.legend(fontsize=8, loc="lower right")
fig.savefig(FIGDIR / "fig4_need_composition.pdf"); plt.close(fig)

# fig 9b — overlap of the need-priority quintile with the 290/2014(-proxy) eligible set
D["_priority"] = D["district_id"].isin(need_top_q)
ct2 = pd.crosstab(D["_priority"].map({True: "Prioritás", False: "Nem prioritás"}),
                  D["eligible_290"].map({True: "Jogosult", False: "Nem jogosult"}))
fig, ax = plt.subplots(figsize=(4.6, 3.2))
ct2.plot(kind="bar", stacked=True, ax=ax, color=["#c0504d", "#1f4e79"])
ax.set_xlabel(""); ax.set_ylabel("Járások száma")
ax.set_title("Szükségleti prioritás vs. 290/2014(‑proxy) jogosultság")
ax.tick_params(axis="x", rotation=0)
fig.savefig(FIGDIR / "fig9b_overlap.pdf"); plt.close(fig)
macro("mapMatchRate", "n/a", "{}")


# --------------------------------------------------------------------------- #
# LaTeX table fragments
# --------------------------------------------------------------------------- #
print("[11] writing LaTeX fragments ...")


_GREEK = {"π": r"$\pi$", "τ": r"$\tau$", "λ": r"$\lambda$", "η": r"$\eta$",
          "μ": r"$\mu$", "κ": r"$\kappa$", "ρ": r"$\rho$",
          "–": "--", "≤": r"$\le$", "≥": r"$\ge$"}


def latexify(s):
    s = str(s)
    # Localise pure numbers before escaping, so "12.5%" becomes "12{,}5\\%".
    s = hu_num(s)
    s = s.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
    for k, v in _GREEK.items():
        s = s.replace(k, v)
    return s


DEFAULT_SOURCE = (
    "saj\u00e1t sz\u00e1m\u00edt\u00e1s az \\texttt{analysis/} pipeline kimeneteib\u0151l"
)


def write_table(path, df, header, aligns, fmts, caption, label, source=DEFAULT_SOURCE):
    """Write a booktabs table whose number, title and source sit *below* the table.

    The Corvinus TDK call requires a serial number, a title and a source under
    every table and figure, so the caption follows the tabular and is followed by
    a ``\\forras`` line (defined in ``tdk.sty``).
    """
    lines = [r"\begin{table}[htbp]", r"\centering", r"\small",
             rf"\begin{{tabular}}{{{aligns}}}", r"\toprule",
             " & ".join(header) + r" \\", r"\midrule"]
    for _, row in df.iterrows():
        cells = [latexify(f.format(row[c])) for c, f in zip(df.columns, fmts)]
        lines.append(" & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}",
              rf"\caption{{{caption}}}", rf"\label{{{label}}}",
              rf"\forras{{{source}}}",
              r"\end{table}", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# T2 cost parameters
cp = pd.read_csv(RESULTS / "cost_parameters.csv")
cp["b"] = cp.apply(lambda r: f"{r['base']:,.2f}".rstrip("0").rstrip(".") if r['base'] < 10
                   else f"{r['base']:,.0f}", axis=1)
cp["rng"] = cp.apply(lambda r: f"{r['low']:,.2f}–{r['high']:,.2f}" if r['high'] < 10
                     else f"{r['low']:,.0f}–{r['high']:,.0f}", axis=1)
cp_out = cp[["desc", "b", "rng", "evidence", "confidence"]]
write_table(TABDIR / "t2_cost_parameters.tex", cp_out,
            ["Paraméter", "Alap", "Tartomány", "Bizonyíték", "Megbízh."],
            "p{5.4cm}rp{2.9cm}ll", ["{}", "{}", "{}", "{}", "{}"],
            "Költségparaméterek: alap‑ és érzékenységi tartomány, bizonyíték‑osztály és megbízhatóság. "
            "Minden érték az elemzési réteg átlátható feltevése (lásd a Módszertan fejezet költségmodell alfejezetét).",
            "tab:cost",
            source="NEAK-közlemények, 9/1993. NM rendelet és szakirodalmi becslések alapján saját számítás")

# T3 county cross-section
ct = pd.read_csv(RESULTS / "county_cross_section.csv")
ct[str(PRE)] = ct[str(PRE)].map(lambda v: f"{v:,.1f}")
ct[str(YEAR)] = ct[str(YEAR)].map(lambda v: f"{v:,.1f}")
write_table(TABDIR / "t3_county_xs.tex", ct.rename(columns={"stat": "Mutató"}),
            ["Mutató", str(PRE), str(YEAR)], "p{6.2cm}rr", ["{}", "{}", "{}"],
            f"Vármegyei rotavírus eset‑ráta (eset / {RATE_DENOM_LABEL}) keresztmetszete, "
            f"{PRE} és {YEAR}. A nevező a KSH vármegyei 0--14 éves népessége.", "tab:countyxs",
            source="NNGYK heti surveillance és KSH STADAT 22.1.2.2 alapján saját számítás")

# T4 need top 10
nt = pd.read_csv(RESULTS / "need_top10.csv")
nt2 = pd.DataFrame({
    "Járás": nt["district_name"], "Vármegye": nt["county_name"],
    "Szükséglet": nt["need_score"].map("{:.3f}".format),
    "Beteg.": nt["score_disease"].map("{:+.2f}".format),
    "Szoc.": nt["score_socioeconomic"].map("{:+.2f}".format),
    "Kap.": nt["score_healthcare"].map("{:+.2f}".format),
    r"$\lambda$ (eset)": nt["lambda"].map("{:.0f}".format),
})
write_table(TABDIR / "t4_need_top10.tex", nt2,
            list(nt2.columns), "llrrrrr", ["{}"] * len(nt2.columns),
            "A tíz legmagasabb összetett szükségletindexű járás és a dimenzió‑pontszámok (z‑score).",
            "tab:needtop",
            source="NNGYK, KSH, NFSZ és OKFŐ adatai alapján saját számítás")

# T5 equity
eq = pd.read_csv(RESULTS / "equity.csv")
eq_out = pd.DataFrame({
    "Forgatókönyv": eq["label"],
    "Gini(támog.)": eq["gini_aid"].map("{:.3f}".format),
    "CI$_{sz}$": eq["ci_need"].map("{:+.3f}".format),
    "CI$_{szoc}$": eq["ci_socio"].map("{:+.3f}".format),
    "Kakwani": eq["kakwani_need"].map("{:+.3f}".format),
    "Theil köz. (\\%)": (100 * eq["theil_between_share"]).map("{:.0f}".format),
    "Legr. kvint. (\\%)": (100 * eq["worst_quintile_share"]).map("{:.1f}".format),
})
write_table(TABDIR / "t5_equity.tex", eq_out, list(eq_out.columns),
            "p{3.5cm}rrrrrr", ["{}"] * len(eq_out.columns),
            "Méltányossági mérőszámok forgatókönyvenként. CI$_{sz}$: koncentrációs index a "
            "szükséglet‑rang szerint (pozitív = progresszív); CI$_{szoc}$: a szocioökonómiai "
            "rang szerint; Theil köz.: a vármegyék közötti egyenlőtlenség részaránya.",
            "tab:equity",
            source="saját számítás az \\texttt{analysis/} pipeline kimeneteiből")

# T6 spearman
sp = pd.read_csv(RESULTS / "scenario_spearman.csv", index_col=0)
sp.index = [SCN_LABELS[i].split(" · ")[0] for i in sp.index]
sp.columns = [SCN_LABELS[c].split(" · ")[0] for c in sp.columns]
sp_out = sp.reset_index().rename(columns={"index": ""})
for c in sp_out.columns[1:]:
    sp_out[c] = sp_out[c].map("{:.2f}".format)
write_table(TABDIR / "t6_spearman.tex", sp_out, [""] + list(sp_out.columns[1:]),
            "l" + "r" * (len(sp_out.columns) - 1), ["{}"] * len(sp_out.columns),
            "A normált forgatókönyvek járási allokációinak Spearman‑rangkorrelációja.",
            "tab:spearman",
            source="saját számítás az \\texttt{analysis/} pipeline kimeneteiből")

# T7 robust priority
rp = pd.read_csv(RESULTS / "robust_priority.csv")
rp_out = pd.DataFrame({
    "Járás": rp["district_name"], "Vármegye": rp["county_name"],
    "P(felső dec.)": rp["p_top_decile"].map("{:.2f}".format),
    "Szükséglet": rp["need_score"].map("{:.3f}".format),
    r"$\lambda$": rp["lambda"].map("{:.0f}".format),
    "Álláskeresői ráta": rp["jobseeker_rate"].map("{:.1%}".format),
    "Bet.tlen körzet": rp["vacant_paed"].map("{:.0f}".format),
})
write_table(TABDIR / "t7_robust.tex", rp_out.head(20), list(rp_out.columns),
            "llrrrrr", ["{}"] * len(rp_out.columns),
            f"Robusztus prioritási járások: P(felső decilis a szükségletben) $\\ge$ {ROBUST_T:.2f} "
            f"a Dirichlet‑súlyújramintavételben ({W_DRAWS} húzás).",
            "tab:robust",
            source="saját számítás (Dirichlet-súlyújramintavétel)")

# T8 tornado (total societal expected cost, Mrd HUF)
tor = pd.read_csv(RESULTS / "tornado.csv").sort_values("spread", ascending=False)
tor_out = pd.DataFrame({
    "Tényező": tor["param"],
    "Alsó (Mrd Ft)": tor["low"].map("{:.2f}".format),
    "Felső (Mrd Ft)": tor["high"].map("{:.2f}".format),
    "Terjedelem (Mrd Ft)": tor["spread"].map("{:.2f}".format),
})
write_table(TABDIR / "t8_tornado.tex", tor_out, list(tor_out.columns),
            "p{5.4cm}rrr", ["{}"] * 4,
            "Egyváltozós érzékenység: a teljes társadalmi várható éves költség (Mrd Ft) az egyes "
            "költségtényezők alsó/felső értéke mellett. Alapérték: \\baseCostMrd~Mrd Ft.",
            "tab:tornado",
            source="saját számítás a költségparaméterek alsó/felső értékeivel")

# T9 cost-effectiveness / break-even, ten highest-need districts
ce_t = pd.read_csv(RESULTS / "cost_effectiveness.csv").head(10)
ce_out = pd.DataFrame({
    "Járás": ce_t["district_name"], "Vármegye": ce_t["county_name"],
    "Szüks.": ce_t["need_score"].map("{:.3f}".format),
    "Kohorsz": ce_t["birth_cohort"].map("{:.0f}".format),
    "Támogatás": (ce_t["subsidy_cost"] / 1e6).map("{:.1f}".format),
    "Elkerült ktg.": (ce_t["averted_societal"] / 1e6).map("{:.1f}".format),
    "H/K arány": ce_t["benefit_cost_ratio"].map("{:.2f}".format),
})
write_table(TABDIR / "t9_costeff.tex", ce_out, list(ce_out.columns),
            "llrrrrr", ["{}"] * len(ce_out.columns),
            "Egy szükségletarányos oltástámogatás állandósult állapotú éves megtérülése a tíz "
            "legmagasabb szükségletindexű járásban (Támogatás és Elkerült ktg.\\ M~Ft/év-ben). "
            "Feltételezett átoltottság-növekmény "
            f"{int(100 * float(CFG.get('subsidy_uptake_gain', 0.6)))}\\%, oltóanyag-hatásosság "
            f"{base_scn['vaccine_efficacy'] * 100:.0f}\\%. H/K arány $>1$: a támogatás megtérül.",
            "tab:costeff",
            source="saját számítás; oltóanyagár és hatásosság a szakirodalomból")

# T10 bootstrap 95% CIs for the progressivity metrics
eb = pd.read_csv(RESULTS / "equity_bootstrap.csv")
eb_out = pd.DataFrame({
    "Forgatókönyv": eb["label"],
    "CI (szükséglet)": eb.apply(lambda r: f"{r['ci_need']:+.3f} [{r['ci_lo']:+.3f}; {r['ci_hi']:+.3f}]", axis=1),
    "Kakwani": eb.apply(lambda r: f"{r['kakwani']:+.3f} [{r['kak_lo']:+.3f}; {r['kak_hi']:+.3f}]", axis=1),
})
write_table(TABDIR / "t10_bootstrap.tex", eb_out, list(eb_out.columns),
            "p{3.4cm}p{5.2cm}p{5.2cm}", ["{}"] * 3,
            "A progresszivitási mérőszámok pontbecslése és 95\\%-os bootstrap konfidenciaintervalluma "
            "(2000 járás-újramintavétel). A koncentrációs index mind a három szükségletalapú "
            "forgatókönyvnél pozitív, és a konfidenciaintervallum nem tartalmazza a nullát.",
            "tab:bootstrap",
            source="saját számítás (2000 járás-újramintavétel)")

# T11 external validation vs 290/2014 + specification robustness summary
sr = pd.read_csv(RESULTS / "spec_robust.csv")
sr_top = sr[sr["spec_top_count"] >= sr["spec_n_specs"].iloc[0] - 1].head(12)
sr_out = pd.DataFrame({
    "Járás": sr_top["district_name"], "Vármegye": sr_top["county_name"],
    "Szükségletindex": sr_top["need_score"].map("{:.3f}".format),
    "Felső decilis (spec. / összes)": sr_top.apply(
        lambda r: f"{int(r['spec_top_count'])} / {int(r['spec_n_specs'])}", axis=1),
})
write_table(TABDIR / "t11_specrobust.tex", sr_out, list(sr_out.columns),
            "llrr", ["{}"] * 4,
            "Specifikáció-robusztus prioritás: hány elemzési specifikációban (3 aggregálás + 3 "
            "dimenzió-elhagyás + a hivatalos 290/2014 mutatóval való csere) kerül a járás a "
            "szükségleti felső decilisbe.",
            "tab:specrobust",
            source="saját számítás; hivatalos mutató: 290/2014. Korm. r. 2. melléklet")

# T1 data sources (static-ish, from what we loaded)
src_rows = [
    ("Rotavírus-surveillance", "NNGYK heti tájékoztató", "vármegye × ISO-hét", "2017–2026", "observed"),
    ("Rotavírus éves kontroll", "NNGYK OSAP éves jelentés", "vármegye × év", "2024", "observed"),
    ("Országos idősor", "KSH STADAT 4.1.1.31 / 4.2.1.1", "ország, év / hó", "2012–2025", "observed"),
    ("Gyermeknépesség", "KSH STADAT 22.1.2.2", "vármegye × korcsop. × év", "2001–2026", "observed"),
    ("Munkaerőpiac", "NFSZ településsoros álláskeresők", "település × hó → járás", "2019–2026", "observed"),
    ("Alapellátási kapacitás", "OKFŐ betöltetlen körzetek", "település × pillanatkép → járás", "2021–2026", "observed"),
    ("Fejlettségi mutató", "290/2014. Korm. r. 2--3. mell.", "járás", "2014", "observed"),
    ("Árindex (deflátor)", "KSH STADAT 1.1.1.1 / 1.1.1.3", "országos, éves", "2001–2025", "observed"),
    ("Közigazgatási térkép", "KSH TSZJ 2022/2025", "járás, település", "2022, 2025", "observed"),
    ("Önkorm. oltástámogatás", "önkorm. rendeletek (Jogtár)", "önkormányzat", "eseti", "observed"),
    ("Költségparaméterek", "NEAK közlemények + szakirodalom", "—", "2024–2025", "assumed/estim."),
]
write_table(TABDIR / "t1_sources.tex", pd.DataFrame(src_rows, columns=["blk", "src", "res", "per", "ev"]),
            ["Blokk", "Forrás", "Felbontás", "Időszak", "Biz."],
            "p{2.5cm}p{3.7cm}p{4.0cm}p{1.8cm}p{1.6cm}", ["{}"] * 5,
            "Az elemzésben felhasznált adatforrások. Minden rotavírus-esetszám "
            "vármegyei felbontásban megfigyelt; a járási bontás modellezett.", "tab:sources",
            source="NNGYK, KSH, NFSZ, OKFŐ, NEAK és a 290/2014. Korm. rendelet közlései alapján saját szerkesztés")

# --------------------------------------------------------------------------- #
# number macros
# --------------------------------------------------------------------------- #
macro("nScenarios", 8)
macro("seed", str(SEED), "{}")
macro("psaDraws", PSA_DRAWS)
macro("wDraws", W_DRAWS)
lines = [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(NUM.items())]
(TABDIR / "_numbers.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

print(f"\nDONE. figures -> {FIGDIR}\n      tables  -> {TABDIR}\n      results -> {RESULTS}")
print(f"      {len(NUM)} number macros written to _numbers.tex")
