"""Build the canonical district / settlement registry.

Outputs (spec 6):
    data/processed/geo_districts.parquet
    data/processed/geo_settlements.parquet
    data/metadata/boundary_changes.json

Primary key is always ``district_id`` (KSH TSZJ code, zero-padded string) and
``settlement_id`` (5-digit KSH törzsszám) — never the name.

Input priority:
    1. canonical CSVs in data/raw/ksh/manual/registry/  (columns below)
    2. KSH TSZJ "…_megnevezesekkel_<year>.xlsx" in data/raw/ksh/
If neither is present, :class:`ManualExportMissingError` is raised with the exact
steps to produce the manual export.

Canonical CSV columns (one file per year, ``registry_<year>.csv``):
    settlement_id, settlement_name, postal_codes, district_id, district_name,
    county_id, county_name, nuts3_code, nuts2_code
``postal_codes`` is ``;``-separated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from scraper import METADATA_DIR, PROCESSED_DIR, RAW_DIR
from scraper.core.config import Config
from scraper.core.errors import ManualExportMissingError, SchemaDriftError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.geography.build")

CANONICAL_COLUMNS = [
    "settlement_id",
    "settlement_name",
    "postal_codes",
    "district_id",
    "district_name",
    "county_id",
    "county_name",
    "nuts3_code",
    "nuts2_code",
]

MANUAL_REGISTRY_DIR = RAW_DIR / "ksh" / "manual" / "registry"
DISTRICTS_OUT = PROCESSED_DIR / "geo_districts.parquet"
SETTLEMENTS_OUT = PROCESSED_DIR / "geo_settlements.parquet"
BOUNDARY_CHANGES_OUT = METADATA_DIR / "boundary_changes.json"

_MANUAL_HELP = f"""\
No geography source files found.

Provide ONE of:

  A) Canonical yearly CSVs (recommended for reproducibility):
     Put files named  registry_<year>.csv  in
       {MANUAL_REGISTRY_DIR}
     with columns: {", ".join(CANONICAL_COLUMNS)}
     (postal_codes is ';'-separated; leave nuts codes blank if unknown).

  B) KSH TSZJ workbooks:
     Download from https://www.ksh.hu/teruleti_szamjel_menu the files
       teruleti_szamjelrendszer_struktura_elemei_<year>_megnevezesekkel.xlsx
     and place them (unchanged) in
       {RAW_DIR / "ksh"}
     then re-run `python -m scraper.geography build`.
"""


@dataclass(slots=True)
class RegistryBuild:
    districts: pd.DataFrame
    settlements: pd.DataFrame
    boundary_changes: list[dict]
    consistency_errors: list[str]


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #

# Heuristic header aliases for KSH TSZJ workbooks (layouts vary by vintage).
# Matching is exact against the normalised header (see ``_norm_header``): a "\n"
# becomes a space and the text is lower-cased. The first alias present wins, so
# the concrete KSH '…megnevezesekkel' headers are listed before looser fallbacks.
_TSZJ_ALIASES = {
    "settlement_id": [
        "település-azonosító törzsszám településkód",
        "település-azonosító törzsszám\ntelepüléskód",
        "településazonosító törzsszám",
        "törzsszám",
        "torzsszam",
        "település törzsszáma",
        "telepules_torzsszam",
        "ksh kód",
        "ksh_kod",
    ],
    "settlement_name": [
        "név",
        "település megnevezése",
        "telepules",
        "helység",
        "település neve",
        "megnevezés",
    ],
    "district_id": [
        "járás kód",
        "járási kód",
        "járás kódja",
        "jaras_kod",
        "járás azonosító",
        "járáskód",
    ],
    "district_name": [
        "járás neve",
        "járás megnevezése",
        "jaras",
        "járás",
    ],
    "county_id": [
        "területi jelzőszámból képzett megyekód",
        "megyekód",
        "megye kódja",
        "megyekod",
        "vármegye kódja",
        "megye_kod",
    ],
    "county_name": [
        "vármegyenév",
        "megye megnevezése",
        "vármegye neve",
        "megye",
        "vármegye",
        "megye neve",
    ],
    "postal_codes": ["irányítószám", "iranyitoszam", "irsz", "posta irányítószám"],
}


def _norm_header(h: object) -> str:
    return str(h).strip().lower().replace("\n", " ").replace("  ", " ")


def parse_canonical_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in ("settlement_id", "district_id", "county_id") if c not in df.columns]
    if missing:
        raise SchemaDriftError(f"{path.name}: missing required columns {missing}")
    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["settlement_id"] = df["settlement_id"].str.strip().str.zfill(5)
    df["district_id"] = df["district_id"].str.strip()
    df["county_id"] = df["county_id"].str.strip()
    return df[CANONICAL_COLUMNS]


def parse_tszj_workbook(path: Path) -> pd.DataFrame:
    """Best-effort parse of a KSH TSZJ '…megnevezesekkel…' workbook."""
    try:
        raw = pd.read_excel(path, dtype=str)
    except Exception as exc:  # pragma: no cover - passthrough
        raise SchemaDriftError(f"cannot read workbook {path.name}: {exc}") from exc

    headers = {_norm_header(c): c for c in raw.columns}
    resolved: dict[str, str] = {}
    for canon, aliases in _TSZJ_ALIASES.items():
        for alias in aliases:
            if alias in headers:
                resolved[canon] = headers[alias]
                break
    required = {"settlement_id", "district_id", "county_id"}
    if not required.issubset(resolved):
        raise SchemaDriftError(
            f"{path.name}: could not locate columns {required - set(resolved)}. "
            f"Seen headers: {list(raw.columns)[:20]}"
        )

    out = pd.DataFrame()
    for canon, src in resolved.items():
        out[canon] = raw[src].astype(str).str.strip()
    for col in CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out["settlement_id"] = out["settlement_id"].str.zfill(5)
    out = out[out["settlement_id"].str.match(r"\d{5}$")]
    # KSH TSZJ workbooks carry "…területre nem bontható adatai" pseudo-rows with
    # a fiktív district code (999) — drop them; they are not settlements.
    out["district_id"] = out["district_id"].str.replace(r"\D", "", regex=True).str.zfill(3)
    out["county_id"] = out["county_id"].str.replace(r"\D", "", regex=True).str.zfill(2)
    out = out[(out["district_id"] != "999") & (out["district_id"] != "000")]
    out = out[out["county_id"] != "00"]
    return out[CANONICAL_COLUMNS].drop_duplicates("settlement_id")


def discover_year_files(
    config: Config, *, registry_dir: Path | None = None
) -> dict[int, tuple[Path, str]]:
    """year -> (path, kind) where kind is 'csv' or 'xlsx'."""
    years = config.geography.sources_years.get("tszj", [])
    found: dict[int, tuple[Path, str]] = {}
    reg_dir = registry_dir or MANUAL_REGISTRY_DIR
    if reg_dir.exists():
        for p in sorted(reg_dir.glob("registry_*.csv")):
            try:
                yr = int(p.stem.split("_")[-1])
            except ValueError:
                continue
            found[yr] = (p, "csv")
    ksh_dir = RAW_DIR / "ksh"
    if registry_dir is None and ksh_dir.exists():
        for p in sorted(ksh_dir.glob("*megnevezesekkel*.xlsx")):
            for yr in years:
                if str(yr) in p.stem and yr not in found:
                    found[yr] = (p, "xlsx")
    return found


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #


def _load_year(path: Path, kind: str) -> pd.DataFrame:
    return parse_canonical_csv(path) if kind == "csv" else parse_tszj_workbook(path)


def check_consistency(year_frame: pd.DataFrame, *, county_count_expected: int) -> list[str]:
    """Rules the spec requires: every settlement in exactly one district,
    every district in exactly one county."""
    errs: list[str] = []
    dup = year_frame["settlement_id"][year_frame["settlement_id"].duplicated()].unique()
    if len(dup):
        errs.append(f"{len(dup)} settlement_id(s) appear in more than one row: {list(dup)[:10]}")

    d2c = year_frame.groupby("district_id")["county_id"].nunique()
    bad = d2c[d2c > 1]
    if len(bad):
        errs.append(f"{len(bad)} district(s) map to multiple counties: {list(bad.index)[:10]}")

    n_counties = year_frame["county_id"].nunique()
    if n_counties != county_count_expected:
        errs.append(f"county count {n_counties} != expected {county_count_expected}")

    empty = year_frame[year_frame["district_id"].eq("") | year_frame["district_id"].isna()]
    if len(empty):
        errs.append(f"{len(empty)} settlement(s) have no district_id")
    return errs


def _intervals(per_year: dict[int, pd.DataFrame], key_cols: list[str], id_col: str) -> pd.DataFrame:
    """Collapse yearly snapshots into valid_from / valid_to intervals per entity."""
    years = sorted(per_year)
    records: dict[str, dict] = {}
    rows: list[dict] = []

    for yr in years:
        frame = per_year[yr].drop_duplicates(id_col)
        seen_now = set()
        for _, r in frame.iterrows():
            ent = r[id_col]
            seen_now.add(ent)
            sig = tuple(str(r.get(c, "")) for c in key_cols)
            prev = records.get(ent)
            if prev is None or prev["sig"] != sig:
                if prev is not None:
                    rows.append({**prev["row"], "valid_to": date(yr, 1, 1)})
                records[ent] = {
                    "sig": sig,
                    "row": {
                        id_col: ent,
                        **{c: r.get(c, "") for c in key_cols},
                        "valid_from": date(yr, 1, 1),
                        "valid_to": None,
                        "source_file": r.get("source_file", ""),
                    },
                }
        # entities that disappeared this year
        for ent, prev in list(records.items()):
            if ent not in seen_now and prev["row"]["valid_to"] is None:
                rows.append({**prev["row"], "valid_to": date(yr, 1, 1)})
                del records[ent]

    for prev in records.values():
        rows.append(prev["row"])
    return pd.DataFrame(rows)


def build_registry(config: Config, *, registry_dir: Path | None = None) -> RegistryBuild:
    year_files = discover_year_files(config, registry_dir=registry_dir)
    if not year_files:
        raise ManualExportMissingError(_MANUAL_HELP)

    county_count = config.geography.county_count_expected
    per_year: dict[int, pd.DataFrame] = {}
    consistency_errors: list[str] = []

    for yr, (path, kind) in sorted(year_files.items()):
        frame = _load_year(path, kind)
        frame["source_file"] = path.name
        errs = check_consistency(frame, county_count_expected=county_count)
        for e in errs:
            consistency_errors.append(f"{yr}: {e}")
            log.warning("geography.consistency", year=yr, issue=e)
        per_year[yr] = frame
        log.info("geography.year_loaded", year=yr, settlements=len(frame), file=path.name)

    settlements = _intervals(
        per_year,
        key_cols=["settlement_name", "postal_codes", "district_id", "county_id"],
        id_col="settlement_id",
    )

    district_year: dict[int, pd.DataFrame] = {}
    for yr, frame in per_year.items():
        d = (
            frame.drop_duplicates("district_id")[
                ["district_id", "district_name", "county_id", "county_name", "nuts3_code", "nuts2_code"]
            ]
            .assign(source_file=frame["source_file"].iloc[0] if len(frame) else "")
        )
        district_year[yr] = d
    districts = _intervals(
        district_year,
        key_cols=["district_name", "county_id", "county_name", "nuts3_code", "nuts2_code"],
        id_col="district_id",
    )
    # Budapest's 23 kerület sit under county code 01 and stand in for "járás".
    districts["is_budapest_district"] = districts["county_id"].astype(str).str.zfill(2) == "01"

    boundary_changes = _boundary_changes(per_year)

    return RegistryBuild(
        districts=districts,
        settlements=settlements,
        boundary_changes=boundary_changes,
        consistency_errors=consistency_errors,
    )


def _boundary_changes(per_year: dict[int, pd.DataFrame]) -> list[dict]:
    from itertools import pairwise

    years = sorted(per_year)
    changes: list[dict] = []
    for a, b in pairwise(years):
        left = per_year[a].set_index("settlement_id")["district_id"]
        right = per_year[b].set_index("settlement_id")["district_id"]
        common = left.index.intersection(right.index)
        moved = common[left.loc[common].values != right.loc[common].values]
        for sid in moved:
            changes.append(
                {
                    "type": "settlement_reassigned",
                    "year": b,
                    "settlement_id": sid,
                    "from_district": left.loc[sid],
                    "to_district": right.loc[sid],
                }
            )
        new_d = set(right.values) - set(left.values)
        gone_d = set(left.values) - set(right.values)
        for d in sorted(new_d):
            changes.append({"type": "district_created", "year": b, "district_id": d})
        for d in sorted(gone_d):
            changes.append({"type": "district_dissolved", "year": b, "district_id": d})
    return changes


def write_registry(build: RegistryBuild) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    build.districts.to_parquet(DISTRICTS_OUT, index=False)
    build.settlements.to_parquet(SETTLEMENTS_OUT, index=False)
    BOUNDARY_CHANGES_OUT.write_text(
        json.dumps(
            {"schema": 1, "changes": build.boundary_changes},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    log.info(
        "geography.written",
        districts=len(build.districts),
        settlements=len(build.settlements),
        boundary_changes=len(build.boundary_changes),
        consistency_errors=len(build.consistency_errors),
    )
