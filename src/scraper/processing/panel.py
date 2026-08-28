"""Assemble the two published panels.

    county_weekly_epi.parquet   observed county x ISO-week rotavirus panel
                                ("ground truth")
    district_panel.parquet      district x year panel with the MODELLED rotavirus
                                columns and whatever else the collectors provided

Every column written to district_panel.parquet must have an entry in
config/variables.yaml (source_id required) — otherwise :class:`ConfigError`.
"""

from __future__ import annotations

import pandas as pd

from scraper import INTERMEDIATE_DIR, PROCESSED_DIR
from scraper.core.config import Config
from scraper.core.errors import ConfigError
from scraper.core.logging_setup import get_logger
from scraper.processing.small_area_model import (
    SmallAreaParams,
    estimate_district_cases,
)

log = get_logger("scraper.processing.panel")

COUNTY_WEEKLY_OUT = PROCESSED_DIR / "county_weekly_epi.parquet"
DISTRICT_PANEL_OUT = PROCESSED_DIR / "district_panel.parquet"

# columns that are structural / quality and are allowed without a source row check
_ALWAYS_OK = {
    "county_id",
    "county_name",
    "geo_level",
    "geo_name",
    "iso_year",
    "period_start",
    "period_end",
    "confidence",
    "method",
    "crosswalk_method",
    "crosswalk_status",
    "crosswalk_score",
    "source_file",
    "collector",
}


# --------------------------------------------------------------------------- #
# county weekly epi
# --------------------------------------------------------------------------- #


def build_county_weekly_epi(config: Config, *, intermediate_dir=INTERMEDIATE_DIR) -> pd.DataFrame:
    src = intermediate_dir / "nngyk" / "nngyk.parquet"
    if not src.exists():
        log.warning("panel.no_nngyk_intermediate", path=str(src))
        return pd.DataFrame(
            columns=[
                "geo_level", "geo_name", "county_id", "variable", "value",
                "iso_year", "iso_week", "period_start", "period_end",
                "evidence_class", "source_id", "quality_flag",
            ]
        )
    df = pd.read_parquet(src)
    df = df[df["variable"].isin({"rotavirus_cases", "rotavirus_cases_annual"})].copy()

    # attach county_id from the disease-name canonical list order (Budapest + 19)
    canon = {name: f"{i:02d}" for i, name in enumerate(config.disease_names.county_table_rows, start=1)}
    if "geo_name" in df.columns:
        mapped = df["geo_name"].map(canon)
        if "county_id" in df.columns:
            mapped = mapped.fillna(df["county_id"])
        df["county_id"] = mapped
    if "quality_flag" not in df.columns:
        df["quality_flag"] = ""

    df = df.drop_duplicates(subset=["geo_name", "variable", "period_start"])
    df = df.sort_values(["iso_year", "iso_week", "geo_name"], na_position="last").reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(COUNTY_WEEKLY_OUT, index=False)
    df.to_csv(COUNTY_WEEKLY_OUT.with_suffix(".csv"), index=False)
    log.info("panel.county_weekly_written", rows=len(df), path=str(COUNTY_WEEKLY_OUT))
    return df


# --------------------------------------------------------------------------- #
# district panel
# --------------------------------------------------------------------------- #


def _county_annual_from_weekly(weekly: pd.DataFrame) -> pd.DataFrame:
    if weekly.empty:
        return pd.DataFrame(columns=["county_id", "year", "cases"])
    w = weekly[weekly["variable"] == "rotavirus_cases"].copy()
    if "iso_year" not in w.columns:
        return pd.DataFrame(columns=["county_id", "year", "cases"])
    w["year"] = pd.to_numeric(w["iso_year"], errors="coerce")
    w["value"] = pd.to_numeric(w["value"], errors="coerce")
    g = (
        w.dropna(subset=["county_id", "year"])
        .groupby(["county_id", "year"], as_index=False)
        .agg(cases=("value", "sum"))
    )
    g["year"] = g["year"].astype(int)
    return g


def build_district_panel(
    config: Config,
    *,
    county_weekly: pd.DataFrame | None = None,
    geo_districts: pd.DataFrame | None = None,
    district_pop: pd.DataFrame | None = None,
    ci_fraction: float = 0.5,
) -> pd.DataFrame:
    if county_weekly is None:
        county_weekly = (
            pd.read_parquet(COUNTY_WEEKLY_OUT) if COUNTY_WEEKLY_OUT.exists() else pd.DataFrame()
        )
    if geo_districts is None:
        gp = PROCESSED_DIR / "geo_districts.parquet"
        if not gp.exists():
            raise ConfigError(
                "geo_districts.parquet missing — run `python -m scraper.geography build` first."
            )
        geo_districts = pd.read_parquet(gp)

    if district_pop is None:
        district_pop = geo_districts[["district_id", "county_id"]].drop_duplicates().copy()
        # no population source loaded -> equal split fallback (logged by the model)
        district_pop["population_0_4"] = 1.0
        district_pop["population_total"] = 1.0

    county_annual = _county_annual_from_weekly(county_weekly)
    if county_annual.empty:
        log.warning("panel.district.no_county_totals")
        modelled = pd.DataFrame(
            columns=[
                "district_id", "county_id", "year",
                "rotavirus_cases_district_modelled",
                "rotavirus_cases_district_modelled_lo",
                "rotavirus_cases_district_modelled_hi",
                "rotavirus_incidence_u5_modelled",
                "evidence_class", "confidence", "method",
            ]
        )
    else:
        modelled = estimate_district_cases(
            county_annual,
            geo_districts,
            district_pop,
            SmallAreaParams(ci_fraction=ci_fraction),
        )

    panel = geo_districts[["district_id", "district_name", "county_id"]].drop_duplicates().merge(
        modelled, on=["district_id", "county_id"], how="left"
    )
    if "county_name" in geo_districts.columns:
        panel = panel.merge(
            geo_districts[["county_id", "county_name"]].drop_duplicates(), on="county_id", how="left"
        )
    if "nuts3_code" in geo_districts.columns:
        panel = panel.merge(
            geo_districts[["district_id", "nuts3_code"]].drop_duplicates(), on="district_id", how="left"
        )
    panel["hospitalisations_modelled"] = pd.NA
    panel["expected_cases_per_1000_u5_modelled"] = panel.get("rotavirus_incidence_u5_modelled")
    panel["evidence_class"] = panel["evidence_class"].fillna("estimated")
    panel["source_id"] = "nngyk"
    panel["quality_flag"] = ""

    _enforce_variable_sources(config, panel)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(DISTRICT_PANEL_OUT, index=False)
    panel.to_csv(DISTRICT_PANEL_OUT.with_suffix(".csv"), index=False)
    log.info("panel.district_written", rows=len(panel), cols=len(panel.columns), path=str(DISTRICT_PANEL_OUT))
    return panel


def _enforce_variable_sources(config: Config, panel: pd.DataFrame) -> None:
    known = set(config.variables.columns())
    offenders = [
        c for c in panel.columns if c not in known and c not in _ALWAYS_OK and not c.startswith("_")
    ]
    if offenders:
        raise ConfigError(
            "district_panel columns without a config/variables.yaml entry (add a source_id): "
            + ", ".join(sorted(offenders))
        )
