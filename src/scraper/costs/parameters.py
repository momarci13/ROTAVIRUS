"""Resolve cost parameters from config/cost_parameters.yaml.

Hard rule (spec §9, §17): a parameter with ``required: true`` whose value is
still ``null`` HALTS with :class:`MissingParameterError` naming the parameter and
its ``source_url``. No default number is ever substituted.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from scraper import PROCESSED_DIR
from scraper.core.config import Config, CostParameter
from scraper.core.errors import MissingParameterError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.costs.parameters")

RESOLVED_OUT = PROCESSED_DIR / "cost_parameters_resolved.parquet"


@dataclass(slots=True)
class ResolvedParameter:
    parameter_id: str
    description: str
    value: float | None
    unit: str
    price_year: int | None
    evidence_class: str
    confidence: str
    source_citation: str | None
    source_url: str | None
    source_year: int | None
    required: bool
    year_requested: int | None

    @property
    def missing(self) -> bool:
        return self.required and self.value is None


def resolve_parameter(param: CostParameter, *, year: int | None = None) -> ResolvedParameter:
    val = param.value_for(year)
    return ResolvedParameter(
        parameter_id=param.id,
        description=param.description,
        value=val.scalar(),
        unit=param.unit,
        price_year=val.price_year,
        evidence_class=val.evidence_class,
        confidence=val.confidence,
        source_citation=val.source_citation,
        source_url=val.source_url,
        source_year=val.source_year,
        required=param.required,
        year_requested=year,
    )


def resolve_all(
    config: Config, *, year: int | None = None, strict: bool = True
) -> list[ResolvedParameter]:
    resolved = [resolve_parameter(p, year=year) for p in config.cost_parameters.parameters]
    missing = [r for r in resolved if r.missing]
    if missing and strict:
        lines = [
            f"  - {r.parameter_id}: {r.description}\n      fill from: {r.source_url or 'see cost_parameters.yaml'}"
            for r in missing
        ]
        raise MissingParameterError(
            "Required cost parameters are unset (no default will be substituted):\n"
            + "\n".join(lines)
        )
    for r in missing:
        log.warning("costs.parameter_missing", parameter_id=r.parameter_id, source_url=r.source_url)
    return resolved


def to_frame(resolved: list[ResolvedParameter]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "parameter_id": r.parameter_id,
                "description": r.description,
                "value": r.value,
                "unit": r.unit,
                "price_year": r.price_year,
                "evidence_class": r.evidence_class,
                "confidence": r.confidence,
                "source_citation": r.source_citation,
                "source_url": r.source_url,
                "source_year": r.source_year,
                "required": r.required,
                "missing": r.missing,
            }
            for r in resolved
        ]
    )


def write_resolved(resolved: list[ResolvedParameter]) -> pd.DataFrame:
    df = to_frame(resolved)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(RESOLVED_OUT, index=False)
    df.to_csv(RESOLVED_OUT.with_suffix(".csv"), index=False)
    return df


class ParameterBook:
    """Convenience lookup used by the cost model. ``get()`` raises for a missing
    required parameter."""

    def __init__(self, resolved: list[ResolvedParameter]) -> None:
        self._by_id = {r.parameter_id: r for r in resolved}

    def get(self, pid: str) -> float:
        r = self._by_id.get(pid)
        if r is None:
            raise MissingParameterError(f"unknown cost parameter '{pid}'")
        if r.value is None:
            raise MissingParameterError(
                f"cost parameter '{pid}' is unset; fill it from {r.source_url or 'cost_parameters.yaml'}"
            )
        return float(r.value)

    def get_optional(self, pid: str, default: float | None = None) -> float | None:
        r = self._by_id.get(pid)
        return r.value if (r and r.value is not None) else default

    def price_year(self, pid: str) -> int | None:
        r = self._by_id.get(pid)
        return r.price_year if r else None
