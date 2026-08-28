"""Typed configuration loading.

Every ``config/*.yaml`` file has a pydantic model here. ``load_config()`` reads
them, validates, and returns an aggregate :class:`Config`. The SHA-256 of each
raw file is recorded so the run manifest can pin exactly which configuration
produced a given output.
"""

from __future__ import annotations

import hashlib
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scraper import CONFIG_DIR
from scraper.core.errors import ConfigError

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level YAML in {path} must be a mapping, got {type(data)}")
    return data


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=False)


# --------------------------------------------------------------------------- #
# sources.yaml
# --------------------------------------------------------------------------- #


class SourceResource(_Base):
    key: str
    type: str = "raw"
    url: str | None = None
    alt: list[str] = Field(default_factory=list)
    status: Literal["verified", "to_discover", "broken"] = "verified"
    items: dict[str, str] | dict[int, str] = Field(default_factory=dict)
    notes: str | None = None


class Source(_Base):
    description: str = ""
    base_url: str | None = None
    parser: str = "raw"
    update_frequency: str = "irregular"
    rate_limit_seconds: float | None = None
    robots_allowed: bool = True
    render_required: bool = False
    resources: list[SourceResource] = Field(default_factory=list)

    def resource(self, key: str) -> SourceResource:
        for r in self.resources:
            if r.key == key:
                return r
        raise ConfigError(f"resource '{key}' not found in source")


class SourcesConfig(_Base):
    defaults: dict[str, Any] = Field(default_factory=dict)
    sources: dict[str, Source]

    def get(self, name: str) -> Source:
        if name not in self.sources:
            raise ConfigError(f"Unknown source '{name}'. Known: {sorted(self.sources)}")
        return self.sources[name]

    def rate_limit(self, name: str) -> float:
        src = self.get(name)
        if src.rate_limit_seconds is not None:
            return src.rate_limit_seconds
        return float(self.defaults.get("rate_limit_seconds", 1.0))

    def user_agent(self, contact_email: str) -> str:
        tmpl = self.defaults.get(
            "user_agent_template",
            "rotavirus-research-pipeline/0.1 (+mailto:{contact_email})",
        )
        return tmpl.format(contact_email=contact_email or "unset")


# --------------------------------------------------------------------------- #
# geography.yaml
# --------------------------------------------------------------------------- #


class GeographyConfig(_Base):
    canonical: dict[str, Any]
    crosswalk: dict[str, Any]
    harmonisation: dict[str, Any]
    boundary_changes: dict[str, Any] = Field(default_factory=dict)
    sources_years: dict[str, list[int]] = Field(default_factory=dict)

    @property
    def county_count_expected(self) -> int:
        return int(self.canonical.get("county_count_expected", 20))

    @property
    def settlement_id_digits(self) -> int:
        return int(self.canonical.get("settlement_id_digits", 5))

    @property
    def fuzzy_threshold(self) -> float:
        return float(self.crosswalk.get("fuzzy", {}).get("threshold", 90))


# --------------------------------------------------------------------------- #
# variables.yaml
# --------------------------------------------------------------------------- #


class VariableSpec(_Base):
    source_id: str
    tier: int = 3
    block: str = "exploratory"
    geo_level: Literal["country", "county", "district"] = "district"
    time_resolution: Literal["none", "yearly", "monthly", "weekly"] = "yearly"
    unit: str = "unknown"
    evidence_class: Literal["observed", "estimated", "assumed"] = "observed"
    extensive: bool = False


class VariablesConfig(_Base):
    variables: dict[str, VariableSpec]

    def require(self, column: str) -> VariableSpec:
        if column not in self.variables:
            raise ConfigError(
                f"Panel column '{column}' has no entry in config/variables.yaml. "
                "Every column must declare a source_id."
            )
        return self.variables[column]

    def columns(self) -> list[str]:
        return list(self.variables)


# --------------------------------------------------------------------------- #
# cost_parameters.yaml
# --------------------------------------------------------------------------- #


class CostValue(_Base):
    year: int | None = None
    value_huf_nominal: float | None = None
    price_year: int | None = None
    evidence_class: Literal["observed", "estimated", "assumed"] = "assumed"
    source_citation: str | None = None
    source_url: str | None = None
    source_year: int | None = None
    confidence: Literal["high", "medium", "low"] = "low"

    # Alternative numeric slots a parameter value may use instead of
    # value_huf_nominal (dimensionless weights, ratios, day counts, ...).
    _SCALAR_SLOTS = ("weight", "ratio", "rate", "probability", "multiplier", "points", "days")

    def scalar(self) -> float | None:
        """Return whichever numeric slot this value carries, or None if unset."""
        if self.value_huf_nominal is not None:
            return float(self.value_huf_nominal)
        extra = self.__pydantic_extra__ or {}
        for key in self._SCALAR_SLOTS:
            v = extra.get(key)
            if v is not None:
                return float(v)
        return None


class CostParameter(_Base):
    id: str
    description: str = ""
    required: bool = False
    unit: str = "unknown"
    geo_level: Literal["country", "county", "district"] = "country"
    values: list[CostValue] = Field(default_factory=list)

    def value_for(self, year: int | None = None) -> CostValue:
        if not self.values:
            raise ConfigError(f"cost parameter '{self.id}' has no values[]")
        if year is None:
            return self.values[-1]
        candidates = [v for v in self.values if v.year == year]
        if candidates:
            return candidates[-1]
        # nearest earlier year, else earliest
        earlier = sorted(
            (v for v in self.values if v.year is not None and v.year <= year),
            key=lambda v: v.year or 0,
        )
        return earlier[-1] if earlier else self.values[0]


class Deflator(_Base):
    id: str
    description: str = ""
    source_url: str | None = None
    base_year: int
    series: dict[int, float] = Field(default_factory=dict)


class CostParametersConfig(_Base):
    meta: dict[str, Any] = Field(default_factory=dict)
    deflators: list[Deflator] = Field(default_factory=list)
    parameters: list[CostParameter]

    def param(self, pid: str) -> CostParameter:
        for p in self.parameters:
            if p.id == pid:
                return p
        raise ConfigError(f"Unknown cost parameter '{pid}'")

    def deflator(self, did: str) -> Deflator:
        for d in self.deflators:
            if d.id == did:
                return d
        raise ConfigError(f"Unknown deflator '{did}'")

    @property
    def base_price_year(self) -> int:
        return int(self.meta.get("base_price_year", 2025))


# --------------------------------------------------------------------------- #
# hta_parameters.yaml
# --------------------------------------------------------------------------- #


class HTAConfig(_Base):
    perspective: str = "societal"
    base_price_year: int = 2025
    discounting: dict[str, Any] = Field(default_factory=dict)
    cost_effectiveness_threshold: dict[str, Any] = Field(default_factory=dict)
    deflator: dict[str, str] = Field(default_factory=dict)
    qaly: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# need_index.yaml
# --------------------------------------------------------------------------- #


class NeedDimension(_Base):
    weight: float
    direction: Literal["higher_is_more_need", "inverse"] = "higher_is_more_need"
    variables: list[str]


class NeedIndexConfig(_Base):
    standardisation: Literal["zscore", "minmax", "rank"] = "zscore"
    aggregation: Literal["weighted_sum", "mpi", "pca", "entropy"] = "weighted_sum"
    mpi: dict[str, Any] = Field(default_factory=dict)
    pca: dict[str, Any] = Field(default_factory=dict)
    entropy: dict[str, Any] = Field(default_factory=dict)
    dimensions: dict[str, NeedDimension]
    inverse_suffix: str = "_inverse"
    missing_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _weights_positive(self) -> NeedIndexConfig:
        for name, dim in self.dimensions.items():
            if dim.weight < 0:
                raise ConfigError(f"need dimension '{name}' has negative weight")
        return self

    def normalised_weights(self) -> dict[str, float]:
        total = sum(d.weight for d in self.dimensions.values())
        if total <= 0:
            raise ConfigError("need-index dimension weights sum to <= 0")
        return {k: v.weight / total for k, v in self.dimensions.items()}


# --------------------------------------------------------------------------- #
# scenarios.yaml
# --------------------------------------------------------------------------- #


class Scenario(_Base):
    id: int
    name: str
    description: str = ""
    per_capita_base: str = "none"
    cost_term: str = "none"
    need_term: str = "none"
    eta: float = 0.0
    kappa: float = 0.0
    alpha: float = 1.0
    phi: float = 0.0
    subtract_existing: bool = False
    fiscal_penalty: bool = False
    fiscal_capacity_subtraction: bool = False
    eligibility_filter: str = "none"
    passthrough_variable: str | None = None
    normalise_to_budget: bool = True
    floor: float = 0.0


class ScenariosConfig(_Base):
    default_budget_huf: float = 2_500_000_000
    default_year: int = 2024
    scenarios: list[Scenario]
    sensitivity: dict[str, Any] = Field(default_factory=dict)

    def by_id(self, sid: int) -> Scenario:
        for s in self.scenarios:
            if s.id == sid:
                return s
        raise ConfigError(f"Unknown scenario id {sid}. Known: {[s.id for s in self.scenarios]}")


# --------------------------------------------------------------------------- #
# logging.yaml
# --------------------------------------------------------------------------- #


class LoggingConfig(_Base):
    level: str = "INFO"
    console: dict[str, Any] = Field(default_factory=dict)
    file: dict[str, Any] = Field(default_factory=dict)
    timestamps: dict[str, Any] = Field(default_factory=dict)
    extra_context: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# disease_names.yaml
# --------------------------------------------------------------------------- #


class DiseaseNamesConfig(_Base):
    canonical: dict[str, Any]
    county_table_rows: list[str]
    county_name_aliases: dict[str, str] = Field(default_factory=dict)

    @field_validator("county_table_rows")
    @classmethod
    def _twenty_rows(cls, v: list[str]) -> list[str]:
        if len(v) != 20:
            raise ConfigError(f"county_table_rows must list 20 territorial units, got {len(v)}")
        return v

    def alias_lookup(self) -> dict[str, str]:
        """Map every lowercase alias -> canonical key."""
        out: dict[str, str] = {}
        for key, spec in self.canonical.items():
            for alias in spec.get("aliases", []):
                out[str(alias).strip().lower()] = key
            out[str(spec.get("label_hu", key)).strip().lower()] = key
        return out


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #

_FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "sources": ("sources.yaml", SourcesConfig),
    "geography": ("geography.yaml", GeographyConfig),
    "variables": ("variables.yaml", VariablesConfig),
    "cost_parameters": ("cost_parameters.yaml", CostParametersConfig),
    "hta": ("hta_parameters.yaml", HTAConfig),
    "need_index": ("need_index.yaml", NeedIndexConfig),
    "scenarios": ("scenarios.yaml", ScenariosConfig),
    "logging": ("logging.yaml", LoggingConfig),
    "disease_names": ("disease_names.yaml", DiseaseNamesConfig),
}


class Config:
    """Lazy aggregate over every config file, plus their content hashes."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else CONFIG_DIR
        self._cache: dict[str, BaseModel] = {}
        self.hashes: dict[str, str] = {}

    def _load(self, name: str) -> BaseModel:
        if name in self._cache:
            return self._cache[name]
        filename, model = _FILES[name]
        path = self.config_dir / filename
        raw = _read_yaml(path)
        try:
            obj = model.model_validate(raw)
        except Exception as exc:  # pydantic.ValidationError and friends
            raise ConfigError(f"{filename} failed validation: {exc}") from exc
        self._cache[name] = obj
        self.hashes[filename] = sha256_file(path)
        return obj

    # typed accessors -------------------------------------------------------
    @cached_property
    def sources(self) -> SourcesConfig:
        return self._load("sources")  # type: ignore[return-value]

    @cached_property
    def geography(self) -> GeographyConfig:
        return self._load("geography")  # type: ignore[return-value]

    @cached_property
    def variables(self) -> VariablesConfig:
        return self._load("variables")  # type: ignore[return-value]

    @cached_property
    def cost_parameters(self) -> CostParametersConfig:
        return self._load("cost_parameters")  # type: ignore[return-value]

    @cached_property
    def hta(self) -> HTAConfig:
        return self._load("hta")  # type: ignore[return-value]

    @cached_property
    def need_index(self) -> NeedIndexConfig:
        return self._load("need_index")  # type: ignore[return-value]

    @cached_property
    def scenarios(self) -> ScenariosConfig:
        return self._load("scenarios")  # type: ignore[return-value]

    @cached_property
    def logging(self) -> LoggingConfig:
        return self._load("logging")  # type: ignore[return-value]

    @cached_property
    def disease_names(self) -> DiseaseNamesConfig:
        return self._load("disease_names")  # type: ignore[return-value]

    def load_all(self) -> Config:
        for name in _FILES:
            self._load(name)
        return self

    def seed(self) -> int:
        path = self.config_dir / "seed"
        if not path.exists():
            return 0
        return int(path.read_text(encoding="utf-8").strip() or "0")

    def config_hashes(self) -> dict[str, str]:
        self.load_all()
        return dict(self.hashes)


def load_config(config_dir: Path | str | None = None) -> Config:
    """Public entry point used by the CLI and every module."""
    return Config(Path(config_dir) if config_dir else None)
