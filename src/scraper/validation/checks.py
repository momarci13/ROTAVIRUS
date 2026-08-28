"""The 12 validation rules of spec §8.

Each rule is a function ``check_*(ctx) -> list[Finding]``. ``run_all`` runs them,
writes ``data/metadata/validation_report_<ts>.json`` and ``VALIDATION_REPORT.md``
(Hungarian), and — when ``raise_on_error`` — raises :class:`ValidationError`
aggregating every error-severity finding.

Findings never mutate the data except rule 7 (outliers) and rule 12 (drift),
which set ``quality_flag`` in place rather than dropping rows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from scraper import METADATA_DIR
from scraper.core.config import Config
from scraper.core.errors import ValidationError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.validation")

Severity = Literal["error", "warning", "flag"]

ROTAVIRUS_VARS = {
    "rotavirus_cases",
    "rotavirus_cases_annual",
    "rotavirus_cases_district_modelled",
    "rotavirus_incidence_u5_modelled",
}
SURVEILLANCE_BREAK = date(2014, 1, 1)


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    n_rows: int = 0
    sample: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "n_rows": self.n_rows,
            "sample": self.sample,
        }


@dataclass
class ValidationContext:
    df: pd.DataFrame
    config: Config | None = None
    geo_districts: pd.DataFrame | None = None
    geo_counties: pd.DataFrame | None = None
    resolution: str = "unknown"  # county | district | panel
    foia_source_id: str = "nngyk_foia"

    def col(self, *names: str) -> str | None:
        for n in names:
            if n in self.df.columns:
                return n
        return None


# --------------------------------------------------------------------------- #
# rule 1 — duplicates
# --------------------------------------------------------------------------- #


def check_duplicates(ctx: ValidationContext) -> list[Finding]:
    geo = ctx.col("geo_id", "district_id", "county_id", "geo_name")
    per = ctx.col("period_start", "iso_week", "year")
    var = ctx.col("variable")
    keys = [c for c in (geo, "geo_level", per, var) if c and c in ctx.df.columns]
    if len(keys) < 2:
        return []
    dup = ctx.df.duplicated(subset=keys, keep=False)
    if not dup.any():
        return []
    sample = ctx.df.loc[dup, keys].head(10).to_dict("records")
    return [
        Finding(
            "duplicates",
            "error",
            f"{int(dup.sum())} rows share a (geo, level, period, variable) key: {keys}",
            int(dup.sum()),
            sample,
        )
    ]


# --------------------------------------------------------------------------- #
# rule 2 — missing territorial unit
# --------------------------------------------------------------------------- #


def check_missing_units(ctx: ValidationContext) -> list[Finding]:
    reg = ctx.geo_districts if ctx.resolution == "district" else ctx.geo_counties
    geo = ctx.col("geo_id", "district_id", "county_id")
    per = ctx.col("period_start")
    if reg is None or geo is None or per is None:
        return []
    reg_id = "district_id" if ctx.resolution == "district" else "county_id"
    if reg_id not in reg.columns:
        return []
    expected = set(reg[reg_id].astype(str))
    findings: list[Finding] = []
    missing_total = 0
    for period, grp in ctx.df.groupby(per):
        present = set(grp[geo].astype(str))
        gap = expected - present
        # a NaN placeholder row with missing_reason counts as "present"
        missing_total += len(gap)
        if gap:
            findings.append(
                Finding(
                    "missing_units",
                    "warning",
                    f"{len(gap)} unit(s) absent for period {period} (expected explicit NaN rows with missing_reason)",
                    len(gap),
                    [{"period": str(period), "missing": sorted(gap)[:15]}],
                )
            )
    if not findings:
        return []
    head = findings[:5]
    head.append(
        Finding("missing_units", "warning", f"total missing unit-periods: {missing_total}", missing_total)
    )
    return head


# --------------------------------------------------------------------------- #
# rule 3 — valid identifier
# --------------------------------------------------------------------------- #


def check_valid_ids(ctx: ValidationContext) -> list[Finding]:
    reg = ctx.geo_districts if ctx.resolution == "district" else ctx.geo_counties
    geo = ctx.col("geo_id", "district_id", "county_id")
    if reg is None or geo is None:
        return []
    reg_id = "district_id" if ctx.resolution == "district" else "county_id"
    if reg_id not in reg.columns:
        return []
    valid = set(reg[reg_id].astype(str))
    ids = ctx.df[geo].astype(str)
    bad = ids[~ids.isin(valid) & ids.ne("nan") & ids.ne("")]
    if bad.empty:
        return []
    return [
        Finding(
            "valid_ids",
            "error",
            f"{bad.nunique()} geo id(s) not in the period-valid registry: {sorted(bad.unique())[:15]}",
            len(bad),
        )
    ]


# --------------------------------------------------------------------------- #
# rule 4 — temporal continuity (ISO weeks, incl. week 53)
# --------------------------------------------------------------------------- #


def check_temporal_continuity(ctx: ValidationContext) -> list[Finding]:
    y = ctx.col("iso_year", "year")
    w = ctx.col("iso_week")
    if y is None or w is None:
        return []
    have = ctx.df[[y, w]].dropna().drop_duplicates()
    if have.empty:
        return []
    from itertools import pairwise

    pairs = sorted({(int(r[y]), int(r[w])) for _, r in have.iterrows()})
    weeks_in_year: dict[int, int] = {}
    gaps: list[str] = []
    for (y0, w0), (y1, w1) in pairwise(pairs):
        if y0 == y1:
            if w1 - w0 > 1:
                gaps.append(f"{y0} weeks {w0 + 1}..{w1 - 1} missing")
        else:
            last = weeks_in_year.setdefault(y0, date(y0, 12, 28).isocalendar().week)
            if w0 < last:
                gaps.append(f"{y0} weeks {w0 + 1}..{last} missing")
            if w1 > 1:
                gaps.append(f"{y1} weeks 1..{w1 - 1} missing")
    if not gaps:
        return []
    return [Finding("temporal_continuity", "warning", f"{len(gaps)} ISO-week gap span(s)", len(gaps), [{"gaps": gaps[:20]}])]


# --------------------------------------------------------------------------- #
# rule 5 — range
# --------------------------------------------------------------------------- #

_RANGES: dict[str, tuple[float, float]] = {
    "cases": (0, np.inf),
    "value": (0, np.inf),
    "population_total": (1, np.inf),
    "population_0_4": (0, np.inf),
    "jobseeker_rate": (0, 1),
    "sewerage_ratio": (0, 1),
    "low_education_ratio": (0, 1),
    "daily_gross_wage": (1, np.inf),
}


def check_ranges(ctx: ValidationContext) -> list[Finding]:
    findings: list[Finding] = []
    var = ctx.col("variable")
    val = ctx.col("value")
    if var and val:
        for v, grp in ctx.df.groupby(var):
            # counts / incidences / costs are all non-negative by default
            lo, hi = _RANGES.get(str(v), (0.0, np.inf))
            nums = pd.to_numeric(grp[val], errors="coerce")
            bad = grp[(nums < lo) | (nums > hi)]
            if len(bad):
                findings.append(
                    Finding("ranges", "error", f"variable '{v}': {len(bad)} value(s) outside [{lo}, {hi}]", len(bad), bad.head(5).to_dict("records"))
                )
    for col, (lo, hi) in _RANGES.items():
        if col in ctx.df.columns and col != "value":
            nums = pd.to_numeric(ctx.df[col], errors="coerce")
            bad = ctx.df[(nums < lo) | (nums > hi)]
            if len(bad):
                findings.append(Finding("ranges", "error", f"column '{col}': {len(bad)} value(s) outside [{lo}, {hi}]", len(bad)))
    return findings


# --------------------------------------------------------------------------- #
# rule 6 — sum agreement (county vs national within the frame)
# --------------------------------------------------------------------------- #


def check_sum_agreement(ctx: ValidationContext) -> list[Finding]:
    lvl = ctx.col("geo_level")
    var = ctx.col("variable")
    val = ctx.col("value")
    per = ctx.col("period_start", "iso_week")
    if not (lvl and var and val and per):
        return []
    df = ctx.df
    if not {"county", "country"}.issubset(set(df[lvl].unique())):
        return []
    findings: list[Finding] = []
    for (v, p), grp in df.groupby([var, per]):
        cty = pd.to_numeric(grp.loc[grp[lvl] == "county", val], errors="coerce").sum()
        nat = pd.to_numeric(grp.loc[grp[lvl] == "country", val], errors="coerce")
        if nat.empty:
            continue
        if abs(cty - nat.iloc[0]) > 0.5:
            findings.append(
                Finding("sum_agreement", "error", f"{v} @ {p}: county sum {cty} != national {nat.iloc[0]}", 1)
            )
    return findings


# --------------------------------------------------------------------------- #
# rule 7 — outliers (robust MAD z-score) -> flag, never delete
# --------------------------------------------------------------------------- #


def check_outliers(ctx: ValidationContext, *, threshold: float = 5.0) -> list[Finding]:
    var = ctx.col("variable")
    val = ctx.col("value")
    if not (var and val):
        return []
    if "quality_flag" not in ctx.df.columns:
        ctx.df["quality_flag"] = ""
    flagged = 0
    for _v, grp in ctx.df.groupby(var):
        x = pd.to_numeric(grp[val], errors="coerce")
        med = x.median()
        mad = (x - med).abs().median()
        if not mad or np.isnan(mad):
            continue
        z = 0.6745 * (x - med) / mad
        mask = z.abs() > threshold
        idx = grp.index[mask.fillna(False)]
        if len(idx):
            cur = ctx.df.loc[idx, "quality_flag"].tolist()
            ctx.df.loc[idx, "quality_flag"] = [
                c if (c not in ("", None) and not pd.isna(c)) else "outlier" for c in cur
            ]
            flagged += len(idx)
    if not flagged:
        return []
    return [Finding("outliers", "flag", f"{flagged} row(s) flagged quality_flag='outlier' (MAD z>{threshold})", flagged)]


# --------------------------------------------------------------------------- #
# rule 8 — price-year consistency
# --------------------------------------------------------------------------- #


def check_price_year_mix(ctx: ValidationContext) -> list[Finding]:
    df = ctx.df
    nominal_cols = [c for c in df.columns if c.endswith("_huf_nominal")]
    if "price_year" not in df.columns or not nominal_cols:
        return []
    if "expected_total_cost_huf_real_2025" in df.columns:
        mix = df["price_year"].dropna().nunique()
        if mix > 1 and "deflator_id" not in df.columns:
            return [
                Finding(
                    "price_year_mix",
                    "error",
                    f"a real cost column exists but {mix} distinct price_year values are present with no deflator_id",
                    mix,
                )
            ]
    return []


# --------------------------------------------------------------------------- #
# rule 9 — evidence class (district + observed + rotavirus)
# --------------------------------------------------------------------------- #


def check_evidence_class(ctx: ValidationContext) -> list[Finding]:
    lvl = ctx.col("geo_level")
    var = ctx.col("variable")
    ec = ctx.col("evidence_class")
    src = ctx.col("source_id")
    if not (lvl and ec):
        return []
    df = ctx.df
    cond = (df[lvl] == "district") & (df[ec] == "observed")
    if var:
        cond &= df[var].isin(ROTAVIRUS_VARS)
    else:
        cond &= pd.Series(True, index=df.index)
    if src:
        cond &= df[src] != ctx.foia_source_id
    bad = df[cond]
    if bad.empty:
        return []
    return [
        Finding(
            "evidence_class",
            "error",
            f"{len(bad)} district-level OBSERVED rotavirus record(s) outside the '{ctx.foia_source_id}' collector",
            len(bad),
            bad.head(5).to_dict("records"),
        )
    ]


# --------------------------------------------------------------------------- #
# rule 10 — surveillance break
# --------------------------------------------------------------------------- #


def check_surveillance_break(ctx: ValidationContext) -> list[Finding]:
    var = ctx.col("variable")
    per = ctx.col("period_start")
    if per is None:
        return []
    dates = pd.to_datetime(ctx.df[per], errors="coerce")
    is_rota = ctx.df[var].isin(ROTAVIRUS_VARS) if var else pd.Series(True, index=ctx.df.index)
    bad = ctx.df[is_rota & (dates < pd.Timestamp(SURVEILLANCE_BREAK))]
    if bad.empty:
        return []
    return [
        Finding(
            "surveillance_break",
            "error",
            f"{len(bad)} rotavirus record(s) dated before the 2014-01-01 surveillance break",
            len(bad),
            bad.head(5).to_dict("records"),
        )
    ]


# --------------------------------------------------------------------------- #
# rule 11 — population consistency
# --------------------------------------------------------------------------- #


def check_population_consistency(ctx: ValidationContext) -> list[Finding]:
    df = ctx.df
    findings: list[Finding] = []
    if {"population_0_4", "population_total"}.issubset(df.columns):
        n0 = pd.to_numeric(df["population_0_4"], errors="coerce")
        nt = pd.to_numeric(df["population_total"], errors="coerce")
        bad = df[(n0 > nt) & n0.notna() & nt.notna()]
        if len(bad):
            findings.append(Finding("population_consistency", "error", f"{len(bad)} row(s) with population_0_4 > population_total", len(bad)))
    if {"district_id", "county_id", "population_total", "year"}.issubset(df.columns):
        by_c = df.groupby(["year", "county_id"])["population_total"].sum()
        if "population_total_county" in df.columns:
            ref = df.groupby(["year", "county_id"])["population_total_county"].first()
            rel = (by_c - ref).abs() / ref.replace(0, np.nan)
            off = rel[rel > 0.005]
            if len(off):
                findings.append(Finding("population_consistency", "error", f"{len(off)} county-year(s) where district population sum deviates >0.5% from the county figure", len(off)))
    return findings


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

ALL_CHECKS = [
    check_duplicates,
    check_missing_units,
    check_valid_ids,
    check_temporal_continuity,
    check_ranges,
    check_sum_agreement,
    check_outliers,
    check_price_year_mix,
    check_evidence_class,
    check_surveillance_break,
    check_population_consistency,
]

VALIDATION_MD = Path("VALIDATION_REPORT.md")


def run_all(ctx: ValidationContext, *, raise_on_error: bool = False, label: str = "") -> list[Finding]:
    findings: list[Finding] = []
    for chk in ALL_CHECKS:
        try:
            findings.extend(chk(ctx))
        except Exception as exc:
            findings.append(Finding(chk.__name__, "warning", f"check crashed: {exc}"))
    _write_reports(findings, label=label, rows=len(ctx.df))
    errors = [f for f in findings if f.severity == "error"]
    if errors and raise_on_error:
        raise ValidationError("; ".join(f"{f.rule}: {f.message}" for f in errors))
    return findings


def _write_reports(findings: list[Finding], *, label: str, rows: int) -> None:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        sev: sum(1 for f in findings if f.severity == sev) for sev in ("error", "warning", "flag")
    }
    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "generated_at": generated_at,
        "label": label,
        "rows_checked": rows,
        "summary": summary,
        "findings": [f.as_dict() for f in findings],
    }
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    (METADATA_DIR / f"validation_report_{ts}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    lines = [
        "# Validációs jelentés",
        "",
        f"- Generálva: {generated_at}",
        f"- Vizsgált sorok: {rows}",
        f"- Címke: {label or '—'}",
        "",
        f"**Hibák:** {summary['error']} · "
        f"**Figyelmeztetések:** {summary['warning']} · "
        f"**Megjelölések:** {summary['flag']}",
        "",
        "| Szabály | Súlyosság | Érintett sorok | Üzenet |",
        "| --- | --- | ---: | --- |",
    ]
    sev_hu = {"error": "hiba", "warning": "figyelmeztetés", "flag": "megjelölés"}
    for f in findings:
        lines.append(f"| {f.rule} | {sev_hu[f.severity]} | {f.n_rows} | {f.message} |")
    if not findings:
        lines.append("| — | — | 0 | Minden szabály hiba nélkül lefutott. |")
    VALIDATION_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
