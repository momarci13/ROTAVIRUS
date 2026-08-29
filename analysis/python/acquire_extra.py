#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Acquire additional, higher-resolution inputs for the TDK analysis.

Everything written here lands in ``analysis/data/`` with a companion
``_provenance.json`` entry (source file / URL, evidence class, retrieval date).
None of this touches the pipeline core: the pipeline still halts on a missing
mandatory cost parameter and still forbids observed district-level rotavirus.
These are *analysis-layer* enrichments with explicit provenance.

Datasets produced
-----------------
1. ``kedvezmenyezett_jaras_290_2014.csv`` -- the REAL Annex 2/3 of Korm. r.
   290/2014: the government "complex development indicator" and the statutory
   beneficiary classification for every one of the 197 districts. Parsed from
   the already-downloaded ``data/raw/jogtar/korm_290_2014.html``. Replaces the
   proxy eligibility rule and gives an independent yardstick for the composite
   need index.
2. ``ksh_national_annual_diseases.csv`` -- notified reportable infectious
   diseases, national, annual (KSH STADAT 4.1.1.31); rotavirus 2012-> plus
   varicella / mumps / hepatitis-A as vaccine-preventable comparators.
3. ``ksh_national_monthly.csv`` -- the same, monthly (STADAT 4.2.1.1), 2020->,
   for a clean seasonality panel.
4. ``ksh_price_indices.csv`` -- headline CPI and the health-sector CPI
   (STADAT 1.1.1.3, COICOP group 6), yearly, chained to a 2025 base. Used to
   deflate the medical cost components instead of one blanket factor.
5. ``osap_county_annual_rotavirus.csv`` -- observed county rotavirus counts for
   the OSAP annual report year (from ``data/intermediate/nngyk/osap_*table9``);
   an independent cross-check on the NNGYK weekly sums.
6. Best-effort network pulls (skipped cleanly on failure, logged to
   ``_broken.json``): KSH 2022 census settlement age structure -> real district
   under-5 population; district boundary GeoJSON for choropleths / Moran's I.

Run:  python analysis/python/acquire_extra.py
"""

from __future__ import annotations

import datetime as _dt
import difflib
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = Path(__file__).resolve().parent
ANALYSIS = HERE.parent
ROOT = ANALYSIS.parent
RAW = ROOT / "data" / "raw"
INTER = ROOT / "data" / "intermediate"
OUT = ANALYSIS / "data"
OUT.mkdir(parents=True, exist_ok=True)

TODAY = _dt.date.today().isoformat()
PROV: dict[str, dict] = {}
BROKEN: list[dict] = []


def prov(name: str, **kw) -> None:
    PROV[name] = {"retrieved": TODAY, **kw}


# --------------------------------------------------------------------------- #
# name normalisation shared with run_analysis.py
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(c))


def norm(s: str) -> str:
    s = strip_accents(str(s)).lower()
    s = re.sub(r"[.,\-]", " ", s)
    return " ".join(s.split())


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
          "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
          "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20, "xxi": 21,
          "xxii": 22, "xxiii": 23}


def build_matcher(geo_d: pd.DataFrame):
    by_norm = {norm(n): i for n, i in zip(geo_d["district_name"], geo_d["district_id"])}
    keys = list(by_norm)

    def match(name: str):
        nn = norm(name)
        if nn in by_norm:
            return by_norm[nn]
        m = re.match(r"budapest\s+([ivx]+)\s*ker", nn)
        if m and m.group(1) in _ROMAN:
            want = f"budapest {_ROMAN[m.group(1)]:02d} ker"
            if want in by_norm:
                return by_norm[want]
        # last resort: high-cutoff fuzzy (handles 'Janoshalmi' vs 'Janoshalmai')
        hit = difflib.get_close_matches(nn, keys, n=1, cutoff=0.88)
        return by_norm[hit[0]] if hit else None

    return match


# --------------------------------------------------------------------------- #
# 1. 290/2014 -- real complex indicator + beneficiary status
# --------------------------------------------------------------------------- #
def acquire_290(geo_d: pd.DataFrame) -> None:
    src = RAW / "jogtar" / "korm_290_2014.html"
    if not src.exists():
        BROKEN.append({"dataset": "kedvezmenyezett_jaras_290_2014", "reason": "raw html missing"})
        return
    tabs = pd.read_html(src)
    # Annex 2 = the 197-row ranked table (widest, ~199 rows, 10 cols)
    t = max(tabs, key=lambda d: d.shape[0] * (d.shape[1] >= 9))
    sub = t.iloc[1:].copy()
    sub.columns = ["idx", "regio", "varmegye", "jaras", "pop2013", "komplex",
                   "rank", "kedvezmenyezett", "fejlesztendo", "komplex_program"][: sub.shape[1]]
    sub = sub[sub["jaras"].notna()]
    sub = sub[~sub["jaras"].astype(str).str.contains("összesen", case=False, na=False)]

    def to_num(x):
        return pd.to_numeric(re.sub(r"[^\d,.\-]", "", str(x)).replace(",", "."), errors="coerce")

    sub["pop2013"] = sub["pop2013"].map(lambda x: pd.to_numeric(re.sub(r"\D", "", str(x)), errors="coerce"))
    sub["komplex_mutato"] = sub["komplex"].map(to_num)
    sub["rank"] = sub["rank"].map(lambda x: pd.to_numeric(re.sub(r"\D", "", str(x)), errors="coerce"))
    for c in ("kedvezmenyezett", "fejlesztendo", "komplex_program"):
        sub[c] = pd.to_numeric(sub[c], errors="coerce").fillna(0).astype(int).clip(0, 1)

    match = build_matcher(geo_d)
    sub["district_id"] = sub["jaras"].map(match)
    unmatched = sub[sub["district_id"].isna()]["jaras"].tolist()
    sub = sub.dropna(subset=["district_id"])

    out = sub[["district_id", "jaras", "varmegye", "regio", "pop2013",
               "komplex_mutato", "rank", "kedvezmenyezett", "fejlesztendo",
               "komplex_program"]].rename(columns={"jaras": "district_name_290"})
    out["district_id"] = out["district_id"].astype(str).str.zfill(3)
    out = out.sort_values("rank")
    out.to_csv(OUT / "kedvezmenyezett_jaras_290_2014.csv", index=False, encoding="utf-8")
    prov("kedvezmenyezett_jaras_290_2014",
         source_file="data/raw/jogtar/korm_290_2014.html",
         source_citation="290/2014. (XI. 26.) Korm. rendelet 2. és 3. melléklet "
                         "(hatályos, egységes szerkezet)",
         source_url="https://net.jogtar.hu/jogszabaly?docid=A1400290.KOR",
         source_year=2014, evidence_class="observed", confidence="high",
         rows=len(out), unmatched=unmatched,
         note="A 'komplex mutato' a terulet tarsadalmi-gazdasagi es infrastrukturalis "
              "fejlettseget mero osszetett kormanyzati mutato; alacsonyabb = deprivaltabb. "
              "kedvezmenyezett=1 a 3. melleklet szerinti jogosult jarasokra.")
    print(f"[1] 290/2014: {len(out)} districts matched, {len(unmatched)} unmatched "
          f"({out['kedvezmenyezett'].sum()} kedvezmenyezett)")


# --------------------------------------------------------------------------- #
# 2-3. KSH notified infectious diseases (annual + monthly)
# --------------------------------------------------------------------------- #
_DISEASE_KEEP = {
    "rotavirus fertozes": "rotavirus",
    "rotavirus": "rotavirus",
    "baranyhimlo": "varicella",
    "jarvanyos fultomirigy gyulladas": "mumps",
    "fertozo majgyulladas": "hepatitis_a",
    "vorheny": "scarlet_fever",
    "szalmonellozis": "salmonellosis",
    "campylobakteriozis": "campylobacteriosis",
    "lyme kor": "lyme",
}


def _clean_int(x):
    s = re.sub(r"[^\d]", "", str(x))
    return int(s) if s else pd.NA


def acquire_ksh_annual() -> None:
    src = RAW / "ksh" / "stadat_ege0028.xlsx"
    if not src.exists():
        BROKEN.append({"dataset": "ksh_national_annual_diseases", "reason": "xlsx missing"})
        return
    raw = pd.read_excel(src, header=None)
    hdr = raw.iloc[1].tolist()
    colmap = {}
    for j, h in enumerate(hdr):
        key = norm(h)
        for pat, name in _DISEASE_KEEP.items():
            if key.startswith(pat):
                colmap[j] = name
    rows = []
    for _, r in raw.iloc[2:].iterrows():
        yr = _clean_int(r[0])
        if yr is None or not (1990 <= yr <= 2035):
            continue
        rec = {"year": yr}
        for j, name in colmap.items():
            rec[name] = _clean_int(r[j])
        rows.append(rec)
    df = pd.DataFrame(rows).dropna(subset=["rotavirus"]) if rows else pd.DataFrame()
    df.to_csv(OUT / "ksh_national_annual_diseases.csv", index=False, encoding="utf-8")
    prov("ksh_national_annual_diseases",
         source_file="data/raw/ksh/stadat_ege0028.xlsx",
         source_citation="KSH STADAT 4.1.1.31 -- A bejelentett fontosabb fertozo betegsegek",
         source_url="https://www.ksh.hu/stadat_files/ege/hu/ege0028.html",
         source_year=2025, evidence_class="observed", confidence="high",
         rows=len(df), note="Orszagos eves bejelentett esetszamok; a rotavirus 2012-tol "
                            "onallo kategoria.")
    print(f"[2] KSH annual diseases: {len(df)} years "
          f"({df['year'].min() if len(df) else '-'}-{df['year'].max() if len(df) else '-'})")


_HU_MONTHS = {"januar": 1, "februar": 2, "marcius": 3, "aprilis": 4, "majus": 5,
              "junius": 6, "julius": 7, "augusztus": 8, "szeptember": 9,
              "oktober": 10, "november": 11, "december": 12}


def acquire_ksh_monthly() -> None:
    src = RAW / "ksh" / "stadat_ege0060.xlsx"
    if not src.exists():
        BROKEN.append({"dataset": "ksh_national_monthly", "reason": "xlsx missing"})
        return
    raw = pd.read_excel(src, header=None)
    hdr = raw.iloc[1].tolist()
    colmap = {}
    for j, h in enumerate(hdr):
        key = norm(h)
        for pat, name in _DISEASE_KEEP.items():
            if key.startswith(pat):
                colmap[j] = name
    rows = []
    cur_year = None
    for _, r in raw.iloc[2:].iterrows():
        ytxt = re.sub(r"[^\d]", "", str(r[0]))
        if ytxt and 2015 <= int(ytxt) <= 2035:
            cur_year = int(ytxt)
        mon = _HU_MONTHS.get(norm(r[1]))
        if cur_year is None or mon is None:
            continue
        rec = {"year": cur_year, "month": mon}
        for j, name in colmap.items():
            rec[name] = _clean_int(r[j])
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "ksh_national_monthly.csv", index=False, encoding="utf-8")
    prov("ksh_national_monthly",
         source_file="data/raw/ksh/stadat_ege0060.xlsx",
         source_citation="KSH STADAT 4.2.1.1 -- A bejelentett fontosabb fertozo betegsegek havonta",
         source_url="https://www.ksh.hu/stadat_files/ege/hu/ege0060.html",
         source_year=2025, evidence_class="observed", confidence="high", rows=len(df))
    print(f"[3] KSH monthly diseases: {len(df)} rows")


# --------------------------------------------------------------------------- #
# 4. KSH price indices -> health-sector deflator chained to 2025
# --------------------------------------------------------------------------- #
def acquire_price_indices() -> None:
    grp = RAW / "ksh" / "price_cpi_by_group.xlsx"
    head = RAW / "ksh" / "price_headline_cpi.xlsx"
    if not grp.exists():
        BROKEN.append({"dataset": "ksh_price_indices", "reason": "price_cpi_by_group.xlsx missing"})
        return
    g = pd.read_excel(grp, header=None)
    yr_row = g.iloc[1].tolist()
    years = {j: int(v) for j, v in enumerate(yr_row) if re.fullmatch(r"\d{4}(\.0)?", str(v).strip())}
    health_row = None
    total_row = None
    for _, r in g.iterrows():
        lab = norm(r[1])
        if lab == "egeszsegugy":
            health_row = r
        if lab in ("mindosszesen", "osszesen"):
            total_row = r
    recs = []
    for j, y in years.items():
        rec = {"year": y}
        if health_row is not None:
            rec["health_cpi_yoy"] = pd.to_numeric(health_row[j], errors="coerce")
        if total_row is not None:
            rec["total_cpi_yoy"] = pd.to_numeric(total_row[j], errors="coerce")
        recs.append(rec)
    df = pd.DataFrame(recs).sort_values("year").reset_index(drop=True)
    if head.exists():
        h = pd.read_excel(head, header=None)
        hh = {}
        for _, r in h.iloc[2:].iterrows():
            y = re.sub(r"[^\d]", "", str(r[0]))
            if y and 1990 <= int(y) <= 2035:
                hh[int(y)] = pd.to_numeric(r[1], errors="coerce")
        df["headline_cpi_yoy"] = df["year"].map(hh)
    # chained index, base = latest year = 100
    def chain(col):
        idx = {}
        acc = 100.0
        for y in sorted(df["year"], reverse=True):
            idx[y] = acc
            prev = df.loc[df["year"] == y, col]
            if len(prev) and pd.notna(prev.iloc[0]) and prev.iloc[0]:
                acc = acc / (prev.iloc[0] / 100.0)
        return df["year"].map(idx)

    for c in ("health_cpi_yoy", "total_cpi_yoy", "headline_cpi_yoy"):
        if c in df:
            df[c.replace("_yoy", "_idx2025")] = chain(c)
    df.to_csv(OUT / "ksh_price_indices.csv", index=False, encoding="utf-8")
    prov("ksh_price_indices",
         source_file="data/raw/ksh/price_cpi_by_group.xlsx, price_headline_cpi.xlsx",
         source_citation="KSH STADAT 1.1.1.1 / 1.1.1.3 -- fogyasztoiar-indexek, COICOP 6. csoport (Egeszsegugy)",
         source_url="https://www.ksh.hu/stadat_files/ara/hu/ara0043.html",
         source_year=2025, evidence_class="observed", confidence="high",
         note="A *_idx2025 oszlopok a lancolt indexek, 2025 = 100. A 2024->2025 "
              "egeszsegugyi deflator = health_cpi_idx2025[2024]/100.")
    row24 = df.loc[df["year"] == 2024]
    hd = row24["health_cpi_idx2025"].iloc[0] / 100 if len(row24) else float("nan")
    print(f"[4] KSH price indices: {len(df)} years; health deflator 2024->2025 = {hd:.4f}")


# --------------------------------------------------------------------------- #
# 5. OSAP county annual rotavirus (observed cross-check)
# --------------------------------------------------------------------------- #
def acquire_osap_county() -> None:
    cands = sorted((INTER / "nngyk").glob("osap_*table9.parquet"))
    if not cands:
        BROKEN.append({"dataset": "osap_county_annual_rotavirus", "reason": "no osap table9 parquet"})
        return
    src = cands[-1]
    yr_m = re.search(r"osap_(\d{4})", src.name)
    year = int(yr_m.group(1)) if yr_m else None
    t = pd.read_parquet(src)
    hdr = t.iloc[0].tolist()
    rcol = next((j for j, h in enumerate(hdr) if norm(h).startswith("rotavirus")), None)
    if rcol is None:
        BROKEN.append({"dataset": "osap_county_annual_rotavirus", "reason": "no rotavirus column"})
        return
    rows = []
    for _, r in t.iloc[1:].iterrows():
        name = str(r[0]).strip()
        if not name or norm(name) in ("osszesen",):
            continue
        rows.append({"county_name": name, "year": year, "rotavirus_cases_osap": _clean_int(r[rcol])})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "osap_county_annual_rotavirus.csv", index=False, encoding="utf-8")
    prov("osap_county_annual_rotavirus",
         source_file=f"data/intermediate/nngyk/{src.name}",
         source_citation="NNGYK OSAP 1406 eves jelentes, 9. tabla (teruleti megoszlas)",
         source_url="https://www.nnk.gov.hu/",
         source_year=year, evidence_class="observed", confidence="high",
         rows=len(df), note="Fuggetlen kereszt-ellenorzes a heti NNGYK-osszegekre.")
    print(f"[5] OSAP county annual rotavirus {year}: {len(df)} counties, "
          f"total={int(df['rotavirus_cases_osap'].sum())}")


# --------------------------------------------------------------------------- #
# 6. best-effort network pulls
# --------------------------------------------------------------------------- #
def try_network() -> None:
    try:
        import requests
    except Exception:
        BROKEN.append({"dataset": "network", "reason": "requests unavailable"})
        return
    ua = {"User-Agent": "ROTAVIRUS-research/1.0 (academic; contact via repo)"}

    # 6a. district boundary GeoJSON (for choropleth + Moran's I)
    boundary_urls = [
        "https://raw.githubusercontent.com/vizeieva/hungary-geojson/master/jaras.geojson",
        "https://raw.githubusercontent.com/ondrejnepozitek/hungary-geojson/master/districts.geojson",
        "https://raw.githubusercontent.com/deldersveld/topojson/master/countries/hungary/hungary-counties.json",
    ]
    got = False
    for u in boundary_urls:
        try:
            r = requests.get(u, headers=ua, timeout=25)
            if r.ok and r.headers.get("content-type", "").lower().startswith(("application/json", "text/plain")) \
               and r.text.lstrip().startswith("{"):
                j = r.json()
                if j.get("type") in ("FeatureCollection", "Topology") and (j.get("features") or j.get("objects")):
                    (OUT / "district_boundaries.geojson").write_text(r.text, encoding="utf-8")
                    prov("district_boundaries", source_url=u, evidence_class="observed",
                         confidence="medium", source_year=TODAY[:4],
                         note="Kozossegi hatarallomany; csak vizualizaciohoz es szomszedsagi "
                              "matrixhoz (Moran-I), szamszaki eredmenyt nem befolyasol.")
                    print(f"[6a] district boundaries: OK from {u}")
                    got = True
                    break
        except Exception as e:  # noqa: BLE001
            BROKEN.append({"dataset": "district_boundaries", "url": u, "reason": str(e)[:160]})
    if not got:
        BROKEN.append({"dataset": "district_boundaries", "reason": "no candidate URL returned usable GeoJSON"})
        print("[6a] district boundaries: not acquired (choropleth stays disabled)")

    # 6b. KSH population by age group x county x year (STADAT 22.1.2.2). Gives a
    #     real child-population (0-14) denominator per county -- far better than the
    #     working-age proxy for a childhood disease.
    census_urls = ["https://www.ksh.hu/stadat_files/nep/hu/nep0035.csv"]
    for u in census_urls:
        try:
            r = requests.get(u, headers=ua, timeout=25)
            if r.ok and len(r.content) > 500 and "html" not in r.headers.get("content-type", ""):
                _parse_ksh_pop_by_age(r.content, u)
        except Exception as e:  # noqa: BLE001
            BROKEN.append({"dataset": "ksh_pop_by_age", "url": u, "reason": str(e)[:160]})


_AGE_GROUPS = {"0": "age_0_14", "15": "age_15_64", "65": "age_65_plus"}
_COUNTY_LEVELS = {"vármegye", "vármegye, régió", "főváros, régió"}


def _parse_ksh_pop_by_age(content: bytes, url: str) -> None:
    txt = content.decode("cp1250", errors="replace")
    lines = [ln.split(";") for ln in txt.splitlines()]
    cols = lines[1]
    year_cols = {j: int(v) for j, v in enumerate(cols) if re.fullmatch(r"\d{4}", v.strip())}
    grp = None
    recs = []
    for p in lines[2:]:
        if len(p) < 3:
            continue
        first = p[0].strip()
        if p[1].strip() == "" and first:
            m = re.match(r"\s*(\d+)", first.replace("\x96", "-"))
            grp = _AGE_GROUPS.get(m.group(1)) if m else None
            continue
        if grp is None or p[1].strip() not in _COUNTY_LEVELS:
            continue
        cty = first.strip()
        for j, y in year_cols.items():
            val = re.sub(r"[^\d]", "", p[j]) if j < len(p) else ""
            if val:
                recs.append({"county_name": cty, "year": y, "age_group": grp, "population": int(val)})
    df = pd.DataFrame(recs)
    # tag Budapest / harmonise county spelling to the pipeline's county names
    df["county_name"] = df["county_name"].str.replace(r"\s+$", "", regex=True)
    df.to_csv(OUT / "ksh_county_population_by_age.csv", index=False, encoding="utf-8")
    prov("ksh_county_population_by_age",
         source_file=None, source_url=url,
         source_citation="KSH STADAT 22.1.2.2 -- A lakonepesseg korcsoport, varmegye es regio szerint, januar 1.",
         source_year=2026, evidence_class="observed", confidence="high",
         rows=len(df),
         note="Varmegyei 0-14 / 15-64 / 65+ nepesseg evente (2001-2026). A jarasi "
              "gyermeknepesseg = varmegyei 0-14 * (jarasi munkavallalasi koru / varmegyei "
              "munkavallalasi koru); a korszerkezet varmegyen beluli homogenitasat felteve.")
    n_cty = df["county_name"].nunique()
    print(f"[6b] KSH pop by age: {len(df)} rows, {n_cty} county units, "
          f"years {df['year'].min()}-{df['year'].max()}")


# --------------------------------------------------------------------------- #
def main() -> None:
    geo_d = pd.read_parquet(ROOT / "data" / "processed" / "geo_districts.parquet")
    acquire_290(geo_d)
    acquire_ksh_annual()
    acquire_ksh_monthly()
    acquire_price_indices()
    acquire_osap_county()
    try_network()
    (OUT / "_provenance.json").write_text(
        json.dumps(PROV, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "_broken.json").write_text(
        json.dumps(BROKEN, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {len(PROV)} datasets to {OUT}")
    if BROKEN:
        print(f"{len(BROKEN)} best-effort item(s) skipped -> analysis/data/_broken.json")


if __name__ == "__main__":
    main()
