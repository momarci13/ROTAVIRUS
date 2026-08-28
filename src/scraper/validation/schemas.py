"""pandera schemas for the key tables.

Kept permissive on presence (many columns are optional depending on which
collectors have run) but strict on the invariants the spec calls out:
non-negative counts, the evidence_class enum, the geo_level enum, and the
rotavirus surveillance-break lower bound.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

GEO_LEVELS = ["country", "county", "district"]
EVIDENCE = ["observed", "estimated", "assumed"]
CONFIDENCE = ["high", "medium", "low"]

_break = pd.Timestamp("2014-01-01")


def _not_pre_break(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce")
    return d.isna() | (d >= _break)


county_weekly_epi_schema = DataFrameSchema(
    {
        "geo_level": Column(str, Check.isin(GEO_LEVELS)),
        "geo_name": Column(str, nullable=True, required=False),
        "variable": Column(str),
        "value": Column(float, Check.ge(0), coerce=True, nullable=True),
        "iso_year": Column("Int64", nullable=True, required=False, coerce=True),
        "iso_week": Column("Int64", Check.in_range(1, 53), nullable=True, required=False, coerce=True),
        "period_start": Column(nullable=True, required=False, checks=Check(_not_pre_break, element_wise=False)),
        "evidence_class": Column(str, Check.isin(EVIDENCE)),
        "source_id": Column(str),
    },
    strict=False,
    coerce=True,
    name="county_weekly_epi",
)


cost_parameters_resolved_schema = DataFrameSchema(
    {
        "parameter_id": Column(str),
        "value": Column(float, nullable=True, coerce=True),
        "price_year": Column("Int64", nullable=True, coerce=True),
        "evidence_class": Column(str, Check.isin(EVIDENCE)),
        "confidence": Column(str, Check.isin(CONFIDENCE), nullable=True),
        "source_url": Column(str, nullable=True),
    },
    strict=False,
    coerce=True,
    name="cost_parameters_resolved",
)


geo_districts_schema = DataFrameSchema(
    {
        "district_id": Column(str, Check.str_matches(r"^\S+$")),
        "district_name": Column(str),
        "county_id": Column(str),
        "valid_from": Column(nullable=True),
        "valid_to": Column(nullable=True),
    },
    strict=False,
    coerce=True,
    name="geo_districts",
)


district_panel_schema = DataFrameSchema(
    {
        "district_id": Column(str),
        "year": Column("Int64", coerce=True),
        "evidence_class": Column(str, Check.isin(EVIDENCE), nullable=True),
        "rotavirus_cases_district_modelled": Column(float, Check.ge(0), nullable=True, required=False, coerce=True),
        "rotavirus_cases_district_modelled_lo": Column(float, Check.ge(0), nullable=True, required=False, coerce=True),
        "rotavirus_cases_district_modelled_hi": Column(float, Check.ge(0), nullable=True, required=False, coerce=True),
    },
    strict=False,
    coerce=True,
    name="district_panel",
)


def validate_schema(df: pd.DataFrame, schema: DataFrameSchema) -> tuple[bool, list[str]]:
    """Return (ok, errors) instead of raising, so the caller can aggregate."""
    try:
        schema.validate(df, lazy=True)
        return True, []
    except pa.errors.SchemaErrors as exc:
        return False, [str(e) for e in exc.failure_cases.to_dict("records")]
    except pa.errors.SchemaError as exc:
        return False, [str(exc)]
