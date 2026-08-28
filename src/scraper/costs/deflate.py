"""Nominal -> real conversion.

    c_real = c_nominal * (P_base / P_y)

The deflator is configurable per variable (spec §9): a health CPI for medical
costs, an earnings index for productivity loss, a headline CPI otherwise. Index
series come from config/cost_parameters.yaml :: deflators (resolved by the ksh
collector).
"""

from __future__ import annotations

from dataclasses import dataclass

from scraper.core.config import Config
from scraper.core.errors import ConfigError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.costs.deflate")


@dataclass(slots=True)
class Deflator:
    deflator_id: str
    base_year: int
    series: dict[int, float]
    source_url: str | None = None

    def factor(self, from_year: int) -> float:
        """P_base / P_from_year."""
        if not self.series:
            raise ConfigError(
                f"deflator '{self.deflator_id}' has an empty index series; the ksh "
                "collector must resolve it (config/sources.yaml :: price_index_stadat)."
            )
        if from_year == self.base_year:
            return 1.0
        try:
            p_base = self.series[self.base_year]
            p_from = self.series[from_year]
        except KeyError as exc:
            raise ConfigError(
                f"deflator '{self.deflator_id}' has no index value for year {exc}"
            ) from exc
        return p_base / p_from


class DeflatorSet:
    def __init__(self, config: Config) -> None:
        self.base_year = config.cost_parameters.base_price_year
        self._by_id: dict[str, Deflator] = {}
        for d in config.cost_parameters.deflators:
            self._by_id[d.id] = Deflator(
                deflator_id=d.id,
                base_year=d.base_year,
                series={int(k): float(v) for k, v in (d.series or {}).items()},
                source_url=d.source_url,
            )
        # variable-class -> deflator id mapping from hta_parameters.yaml
        self.mapping: dict[str, str] = dict(config.hta.deflator or {})

    def for_class(self, cost_class: str) -> Deflator:
        did = self.mapping.get(cost_class, self.mapping.get("default", "headline_cpi"))
        if did not in self._by_id:
            raise ConfigError(f"deflator id '{did}' (for '{cost_class}') not defined")
        return self._by_id[did]

    def to_real(self, value_nominal: float, *, from_year: int, cost_class: str = "default") -> tuple[float, str]:
        defl = self.for_class(cost_class)
        real = value_nominal * defl.factor(from_year)
        return real, defl.deflator_id


def deflate_value(
    config: Config, value_nominal: float, *, from_year: int, cost_class: str = "default"
) -> tuple[float, str, int]:
    """Returns (real_value, deflator_id, base_year)."""
    ds = DeflatorSet(config)
    real, did = ds.to_real(value_nominal, from_year=from_year, cost_class=cost_class)
    return real, did, ds.base_year
