"""Spatial harmonisation across boundary vintages.

Order (spec 6), each variable logged to data/metadata/harmonisation_log.json:
    1. KTE (konzisztens területi egységek): finest common refinement of the
       yearly district partitions. Because every district is a union of whole
       settlements, this is always well defined — a KTE is a maximal set of
       settlements that stay in the same district in every vintage.
    2. Population-weighted apportionment:
         extensive : x_new_i = Σ_j x_old_j · (Σ_{s∈i∩j} pop_s / Σ_{s∈j} pop_s)
         intensive : apportion numerator and denominator separately, then divide.
    3. Truncation: last resort, explicitly logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scraper import METADATA_DIR
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.geography.harmonise")

HARMONISATION_LOG = METADATA_DIR / "harmonisation_log.json"


@dataclass
class HarmonisationLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, variable: str, method: str, **detail) -> None:
        self.entries.append(
            {
                "variable": variable,
                "method": method,
                "at": datetime.now(UTC).isoformat(),
                **detail,
            }
        )

    def flush(self, path: Path | None = None) -> Path:
        path = path or HARMONISATION_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8")).get("entries", [])
            except json.JSONDecodeError:
                existing = []
        path.write_text(
            json.dumps({"entries": existing + self.entries}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return path


def build_kte_partition(year_maps: dict[int, dict[str, str]]) -> dict[str, str]:
    """``year_maps``: year -> {settlement_id: district_id}. Returns
    {settlement_id: kte_id} where kte_id is a stable synthetic label made from
    the tuple of district ids the settlement had across the sorted years.
    """
    years = sorted(year_maps)
    all_settlements: set[str] = set()
    for m in year_maps.values():
        all_settlements.update(m)

    signatures: dict[str, tuple[str, ...]] = {}
    for sid in sorted(all_settlements):
        sig = tuple(year_maps[y].get(sid, "NA") for y in years)
        signatures[sid] = sig

    sig_to_id: dict[tuple[str, ...], str] = {}
    out: dict[str, str] = {}
    for sid, sig in signatures.items():
        if sig not in sig_to_id:
            sig_to_id[sig] = f"KTE{len(sig_to_id) + 1:04d}"
        out[sid] = sig_to_id[sig]
    log.info("harmonise.kte", settlements=len(out), kte_units=len(sig_to_id), years=years)
    return out


def apportion_extensive(
    source_values: dict[str, float],
    settlement_pop: dict[str, float],
    settlement_source: dict[str, str],
    settlement_target: dict[str, str],
    *,
    variable: str = "value",
    hlog: HarmonisationLog | None = None,
) -> dict[str, float]:
    """Redistribute an extensive quantity from source units to target units by
    population share. ``settlement_source`` / ``settlement_target`` map each
    settlement to its source-unit / target-unit id."""
    src_pop_total: dict[str, float] = {}
    for sid, su in settlement_source.items():
        src_pop_total[su] = src_pop_total.get(su, 0.0) + settlement_pop.get(sid, 0.0)

    target: dict[str, float] = {}
    truncated = 0
    for sid, su in settlement_source.items():
        tu = settlement_target.get(sid)
        if tu is None:
            truncated += 1
            continue
        denom = src_pop_total.get(su, 0.0)
        if denom <= 0:
            # fall back to equal split among the source unit's settlements
            share = 1.0 / max(1, sum(1 for x in settlement_source.values() if x == su))
        else:
            share = settlement_pop.get(sid, 0.0) / denom
        target[tu] = target.get(tu, 0.0) + source_values.get(su, 0.0) * share

    if hlog is not None:
        hlog.add(
            variable,
            "population_weighted_extensive",
            source_units=len(src_pop_total),
            target_units=len(target),
            truncated_settlements=truncated,
        )
    if truncated:
        log.warning("harmonise.truncation", variable=variable, settlements=truncated)
    return target


def apportion_intensive(
    numerator_source: dict[str, float],
    denominator_source: dict[str, float],
    settlement_pop: dict[str, float],
    settlement_source: dict[str, str],
    settlement_target: dict[str, str],
    *,
    variable: str = "rate",
    hlog: HarmonisationLog | None = None,
) -> dict[str, float]:
    num = apportion_extensive(
        numerator_source, settlement_pop, settlement_source, settlement_target,
        variable=f"{variable}__num", hlog=hlog,
    )
    den = apportion_extensive(
        denominator_source, settlement_pop, settlement_source, settlement_target,
        variable=f"{variable}__den", hlog=hlog,
    )
    out = {k: (num[k] / den[k] if den.get(k) else float("nan")) for k in num}
    if hlog is not None:
        hlog.add(variable, "population_weighted_intensive", target_units=len(out))
    return out


def harmonise_frame(
    df: pd.DataFrame,
    *,
    value_columns: list[str],
    extensive_flags: dict[str, bool],
    settlement_pop: dict[str, float],
    settlement_source: dict[str, str],
    settlement_target: dict[str, str],
    source_col: str = "unit_id",
    hlog: HarmonisationLog | None = None,
) -> pd.DataFrame:
    """Apply apportionment to every ``value_columns`` entry of a source-unit frame,
    returning a target-unit frame."""
    hlog = hlog or HarmonisationLog()
    target_ids = sorted(set(settlement_target.values()))
    out = pd.DataFrame({"unit_id": target_ids})
    for col in value_columns:
        src_values = dict(zip(df[source_col], df[col]))
        if extensive_flags.get(col, True):
            mapped = apportion_extensive(
                src_values, settlement_pop, settlement_source, settlement_target,
                variable=col, hlog=hlog,
            )
        else:
            pop_by_src: dict[str, float] = {}
            for sid, su in settlement_source.items():
                pop_by_src[su] = pop_by_src.get(su, 0.0) + settlement_pop.get(sid, 0.0)
            num = {su: src_values.get(su, 0.0) * pop_by_src.get(su, 0.0) for su in src_values}
            mapped = apportion_intensive(
                num, pop_by_src, settlement_pop, settlement_source, settlement_target,
                variable=col, hlog=hlog,
            )
        out[col] = out["unit_id"].map(mapped)
    return out
