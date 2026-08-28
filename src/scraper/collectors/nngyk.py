"""NNGYK collector: weekly epidemiological bulletins (PDF) + annual OSAP 1561
reports (PDF).

Resolution reality (spec 2.1): the finest public rotavirus resolution is the
county (19 vármegye + Budapest), weekly, from 2014. Every record this collector
emits carries ``geo_level='county'`` and ``evidence_class='observed'``.

Surveillance break (spec 5.1): "Rotavírus-gastroenteritis" is a standalone
notifiable category only from 2014 (1/2014. (I. 16.) EMMI r.). Pre-2014 files are
still downloaded and archived, but no pre-2014 rotavirus row enters the panel;
the break is recorded in data/metadata/surveillance_breaks.json.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from scraper import METADATA_DIR
from scraper.collectors._discovery import iso_weeks_since
from scraper.collectors.base import Collector, Resource, ValidationReport
from scraper.core.errors import PDFExtractionError, SumMismatchError
from scraper.parsers.pdf_tables import extract_and_pick, write_extraction_artifacts

SURVEILLANCE_BREAKS = METADATA_DIR / "surveillance_breaks.json"
QUARANTINE_DIR = Path("data/intermediate/quarantine")

_INT_RE = re.compile(r"^-?\d[\d\s]*$")


def parse_cell(value: object) -> int | None:
    """NNGYK cell -> int. '-' / '' / '●' -> 0 is NOT assumed: dash means zero,
    blank/dot means 'no data' -> None."""
    s = str(value).strip().replace("\xa0", " ")
    if s in {"-", "–", "—"}:
        return 0
    if s in {"", "●", ".", "..", "n.a.", "N/A"}:
        return None
    s = s.replace(" ", "")
    if s.lstrip("-").isdigit():
        return int(s)
    return None


def iso_week_bounds(iso_year: int, iso_week: int) -> tuple[date, date]:
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    return monday, monday + timedelta(days=6)


class NNGYKCollector(Collector):
    name = "nngyk"
    source_config_key = "nngyk"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._disease = self.config.disease_names
        self._alias = self._disease.alias_lookup()
        self._county_alias = {k.strip().lower(): v for k, v in self._disease.county_name_aliases.items()}
        self._canon_counties = {c.strip().lower(): c for c in self._disease.county_table_rows}
        self._discovery_degraded = False

    # ------------------------------------------------------------------ #
    # discover
    # ------------------------------------------------------------------ #
    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        resources: list[Resource] = []

        # 1) try the JS file-list's backend (spec: to_discover). If unreachable,
        #    fall back to the verified URL patterns and flag degraded discovery.
        json_res = src.resource("weekly_list_json")
        if json_res.url:
            try:
                found = self._discover_via_json(json_res.url, since)
                if found:
                    return found
            except Exception as exc:
                self.log.warning("nngyk.discover.json_failed", error=str(exc))

        self._discovery_degraded = True
        self.log.warning(
            "nngyk.discover.degraded",
            reason="JS file list backend not reachable; using verified URL patterns",
        )

        # 2) weekly PDFs. Filename accents vary by vintage: recent years use the
        #    plain form, 2024 and earlier the fully-accented form. Try the more
        #    likely one first and fall back to the other via alt_urls (a 404 on
        #    the first variant is then silent, not a BROKEN_LINKS entry).
        pat_plain = src.resource("weekly_pdf_pattern_current").url
        pat_acc = src.resource("weekly_pdf_pattern_accented").url
        epinfo = src.resource("epinfo_weekly_pattern").url
        start = since or date(2014, 1, 1)
        for iso_year, iso_week in iso_weeks_since(start):
            if pat_plain and pat_acc:
                primary, alt = (
                    (pat_plain, pat_acc) if iso_year >= 2025 else (pat_acc, pat_plain)
                )
                resources.append(
                    Resource(
                        key=f"weekly_{iso_year}_{iso_week:02d}",
                        url=primary.format(year=iso_year, week=iso_week),
                        alt_urls=[alt.format(year=iso_year, week=iso_week)],
                        resource_type="weekly_pdf",
                        filename=f"weekly_{iso_year}_{iso_week:02d}.pdf",
                        year=iso_year,
                        week=iso_week,
                    )
                )
            if epinfo and iso_year <= 2016:
                resources.append(
                    Resource(
                        key=f"epinfo_{iso_year}_{iso_week:02d}",
                        url=epinfo.format(year=iso_year, week=iso_week),
                        resource_type="epinfo_pdf",
                        filename=f"epinfo_{iso_year}_{iso_week:02d}.pdf",
                        year=iso_year,
                        week=iso_week,
                    )
                )

        # 3) annual OSAP set
        osap = src.resource("osap_1561_annual")
        for yr, url in (osap.items or {}).items():
            yr_i = int(yr)
            if since and yr_i < since.year:
                continue
            resources.append(
                Resource(
                    key=f"osap_{yr_i}",
                    url=url,
                    resource_type="osap_annual_pdf",
                    filename=f"osap_{yr_i}.pdf",
                    year=yr_i,
                )
            )
        return resources

    def _discover_via_json(self, url: str, since: date | None) -> list[Resource]:
        res = self.http_client.fetch(url, rate_limit=self.rate_limit())
        data = json.loads(res.content.decode("utf-8", "replace"))
        items = data if isinstance(data, list) else data.get("files", data.get("data", []))
        out: list[Resource] = []
        for it in items:
            link = it.get("url") or it.get("href") or it.get("link")
            if not link or not link.lower().endswith(".pdf"):
                continue
            m = re.search(r"(\d{4})[.\s]+(\d{1,2})[.\s]*h[eé]t", it.get("name", link))
            yr = int(m.group(1)) if m else None
            wk = int(m.group(2)) if m else None
            if since and yr and yr < since.year:
                continue
            out.append(
                Resource(
                    key=f"weekly_{yr}_{wk}",
                    url=link,
                    resource_type="weekly_pdf",
                    filename=f"weekly_{yr}_{wk:02d}.pdf" if yr and wk else link.split("/")[-1],
                    year=yr,
                    week=wk,
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # parse
    # ------------------------------------------------------------------ #
    def parse(self, path: Path) -> pd.DataFrame:
        name = path.name
        if name.startswith("osap_"):
            return self._parse_osap(path)
        return self._parse_weekly(path)

    # -- weekly --------------------------------------------------------
    def _parse_weekly(self, path: Path) -> pd.DataFrame:
        m = re.search(r"_(\d{4})_(\d{2})\.pdf$", path.name)
        if not m:
            self.log.warning("nngyk.weekly.unparsed_name", file=path.name)
            return pd.DataFrame()
        iso_year, iso_week = int(m.group(1)), int(m.group(2))

        # surveillance break: archive but do not emit pre-2014 rotavirus
        break_year = int((self.source.model_extra or {}).get("surveillance_break_year", 2014))
        if iso_year < break_year:
            self._record_surveillance_break(break_year)
            self.log.info("nngyk.weekly.pre_break_archived", file=path.name, year=iso_year)
            return pd.DataFrame()

        try:
            picked, all_candidates = extract_and_pick(
                path, structure_check=self._county_structure_check, pages="all"
            )
        except PDFExtractionError as exc:
            self._queue_manual(path, str(exc))
            return pd.DataFrame()

        write_extraction_artifacts(self.intermediate_dir, path, picked, all_candidates)

        parsed = self._county_table_to_records(picked.df, iso_year, iso_week, path.name)
        if parsed is None:
            return pd.DataFrame()
        records, total_row = parsed
        df = pd.DataFrame(records)

        # sum check against the national table (page 2)
        national = self._national_current_week_rotavirus(path)
        county_sum = int(df.loc[df["variable"] == "rotavirus_cases", "value"].sum())
        mismatch = []
        if total_row is not None and total_row != county_sum:
            mismatch.append(f"county rows sum {county_sum} != table Total {total_row}")
        if national is not None and national != county_sum:
            mismatch.append(f"county rows sum {county_sum} != national current-week {national}")
        if mismatch:
            self._quarantine(df, path, "; ".join(mismatch))
            self.report.quarantined.append(path.name)
            raise SumMismatchError(f"{path.name}: {'; '.join(mismatch)}")

        df["quality_flag"] = ""
        return df

    def _county_structure_check(self, df: pd.DataFrame) -> tuple[bool, dict]:
        detail: dict = {"rows": len(df), "cols": df.shape[1]}
        if df.shape[1] < 3 or len(df) < 18:
            detail["reason"] = "too small"
            return False, detail
        first_col = df.iloc[:, 0].astype(str).str.strip().str.lower()
        hits = sum(
            1
            for v in first_col
            if v in self._canon_counties or v in self._county_alias
        )
        detail["county_row_hits"] = hits
        rota_col = self._find_disease_column(df, "rotavirus_gastroenteritis")
        detail["rotavirus_col"] = rota_col
        if hits < 18:
            detail["reason"] = "fewer than 18 recognisable county rows"
            return False, detail
        if rota_col is None:
            detail["reason"] = "no rotavirus column in header"
            return False, detail
        return True, detail

    def _find_disease_column(self, df: pd.DataFrame, canonical: str) -> int | None:
        header = list(df.columns)
        # header may also be repeated as row 0 with wrapped text
        candidates = [header] + ([list(df.iloc[0])] if len(df) else [])
        for row in candidates:
            for i, cell in enumerate(row):
                text = re.sub(r"\s+", " ", str(cell)).strip().lower()
                if not text:
                    continue
                key = self._alias.get(text)
                if key == canonical:
                    return i
                if canonical == "rotavirus_gastroenteritis" and "rotav" in text:
                    return i
        return None

    def _county_table_to_records(
        self, df: pd.DataFrame, iso_year: int, iso_week: int, source_file: str
    ) -> tuple[list[dict], int | None] | None:
        rota_col = self._find_disease_column(df, "rotavirus_gastroenteritis")
        if rota_col is None:
            self._queue_manual(Path(source_file), "rotavirus column not located post-pick")
            return None

        p_start, p_end = iso_week_bounds(iso_year, iso_week)
        records: list[dict] = []
        total_value: int | None = None
        for _, row in df.iterrows():
            raw_name = re.sub(r"\s+", " ", str(row.iloc[0])).strip()
            low = raw_name.lower()
            if low.startswith(("összesen", "total", "előző hét", "previous")):
                if low.startswith(("összesen", "total")):
                    total_value = parse_cell(row.iloc[rota_col])
                continue
            county = self._canon_counties.get(low) or self._county_alias.get(low)
            if county is None:
                continue
            val = parse_cell(row.iloc[rota_col])
            if val is None:
                continue
            records.append(
                {
                    "geo_level": "county",
                    "geo_name": county,
                    "variable": "rotavirus_cases",
                    "value": val,
                    "iso_year": iso_year,
                    "iso_week": iso_week,
                    "period_start": p_start,
                    "period_end": p_end,
                    "evidence_class": "observed",
                    "source_id": "nngyk",
                    "source_file": source_file,
                    "collector": self.name,
                }
            )
        if not records:
            return None
        return records, total_value

    def _national_current_week_rotavirus(self, path: Path) -> int | None:
        try:
            import pdfplumber
        except Exception:  # pragma: no cover
            return None
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    low = line.lower()
                    if "rotav" in low and "gastroenteritis" in low:
                        # drop the disease label (which itself contains a hyphen),
                        # then take the first standalone numeric token = current week
                        tail = low.split("gastroenteritis", 1)[1]
                        for tok in tail.split():
                            v = parse_cell(tok)
                            if v is not None:
                                return v
        return None

    # -- OSAP annual -------------------------------------------------
    def _parse_osap(self, path: Path) -> pd.DataFrame:
        """OSAP 1561 annual volume. Tables 1 (national), 7-8 (county count/rate),
        11-12 (age-group count/rate). Cross-table sum checks: table 7 county sum
        == table 11 age-group sum == table 1 national value.

        Full multi-table OSAP parsing is layout-sensitive and varies by year;
        this emits the county annual totals (table 7) when locatable, and queues
        the file for manual extraction otherwise (spec 17) — it never invents a
        number.
        """
        year_m = re.search(r"osap_(\d{4})", path.name)
        year = int(year_m.group(1)) if year_m else None
        try:
            # OSAP volumes are 100+ pages; running camelot lattice+stream over all
            # of them twice is very slow. Use the pure-python pdfplumber strategies
            # first; camelot is only a last resort here.
            picked, cands = extract_and_pick(
                path,
                structure_check=self._osap_county_check,
                pages="all",
                strategies=("pdfplumber_lines", "pdfplumber_text", "camelot_stream"),
            )
        except PDFExtractionError as exc:
            self._queue_manual(path, f"OSAP county table not auto-extractable: {exc}")
            return pd.DataFrame()

        write_extraction_artifacts(self.intermediate_dir, path, picked, cands)

        rota_col = self._find_disease_column(picked.df, "rotavirus_gastroenteritis")
        if rota_col is None:
            self._queue_manual(path, "OSAP: rotavirus column not found")
            return pd.DataFrame()

        recs: list[dict] = []
        for _, row in picked.df.iterrows():
            low = re.sub(r"\s+", " ", str(row.iloc[0])).strip().lower()
            county = self._canon_counties.get(low) or self._county_alias.get(low)
            if county is None:
                continue
            val = parse_cell(row.iloc[rota_col])
            if val is None:
                continue
            recs.append(
                {
                    "geo_level": "county",
                    "geo_name": county,
                    "variable": "rotavirus_cases_annual",
                    "value": val,
                    "iso_year": year,
                    "iso_week": None,
                    "period_start": date(year, 1, 1) if year else None,
                    "period_end": date(year, 12, 31) if year else None,
                    "evidence_class": "observed",
                    "source_id": "nngyk",
                    "source_file": path.name,
                    "collector": self.name,
                    "quality_flag": "",
                }
            )
        return pd.DataFrame(recs)

    def _osap_county_check(self, df: pd.DataFrame) -> tuple[bool, dict]:
        detail: dict = {"rows": len(df), "cols": df.shape[1]}
        if df.empty or df.shape[1] < 2:
            return False, detail
        first_col = df.iloc[:, 0].astype(str).str.strip().str.lower()
        hits = sum(1 for v in first_col if v in self._canon_counties or v in self._county_alias)
        detail["county_row_hits"] = hits
        detail["rotavirus_col"] = self._find_disease_column(df, "rotavirus_gastroenteritis")
        return (hits >= 15 and detail["rotavirus_col"] is not None), detail

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    def validate(self, df: pd.DataFrame) -> ValidationReport:
        rep = super().validate(df)
        if df.empty:
            return rep
        if (df["value"] < 0).any():
            rep.error("negative case counts present")
        pre = df["period_start"].map(lambda d: d is not None and d < date(2014, 1, 1))
        if pre.any():
            rep.error("rotavirus records before the 2014 surveillance break")
        if (df["geo_level"] == "district").any():
            rep.error("district-level observed rotavirus record (forbidden outside nngyk_foia)")
        dup = df.duplicated(subset=["geo_name", "variable", "period_start"])
        if dup.any():
            rep.error(f"{int(dup.sum())} duplicate (county, variable, period) rows")
        return rep

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _record_surveillance_break(self, break_year: int) -> None:
        payload = {
            "schema": 1,
            "breaks": [
                {
                    "variable": "rotavirus_cases",
                    "break_date": f"{break_year}-01-01",
                    "kind": "category_split",
                    "description": (
                        "Rotavírus-gastroenteritis became a standalone notifiable "
                        "category. Before this, diarrhoeal disease was reported under "
                        "the 'Enteritis infectiosa' umbrella and is not comparable."
                    ),
                    "legal_reference": "1/2014. (I. 16.) EMMI rendelet",
                    "legal_url": "https://njt.jog.gov.hu/jogszabaly/2014-1-20-5H",
                }
            ],
        }
        SURVEILLANCE_BREAKS.parent.mkdir(parents=True, exist_ok=True)
        SURVEILLANCE_BREAKS.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _queue_manual(self, path: Path, reason: str) -> None:
        self.report.errors.append(f"manual extraction: {path.name} ({reason})")
        queue = Path("MANUAL_EXTRACTION_QUEUE.md")
        line = (
            f"- `{path.name}` — {reason} "
            f"(logged {datetime.now(UTC).isoformat()})\n"
        )
        with queue.open("a", encoding="utf-8") as fh:
            if fh.tell() == 0:
                fh.write("# Manual extraction queue\n\n")
            fh.write(line)
        self.log.error("nngyk.manual_queue", file=path.name, reason=reason)

    def _quarantine(self, df: pd.DataFrame, path: Path, reason: str) -> None:
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        out = QUARANTINE_DIR / f"{path.stem}__quarantine.parquet"
        df.assign(quality_flag="table_sum_mismatch", quarantine_reason=reason).to_parquet(out, index=False)
        with Path("SUM_MISMATCH_LOG.md").open("a", encoding="utf-8") as fh:
            if fh.tell() == 0:
                fh.write("# Sum-mismatch log\n\n")
            fh.write(f"- `{path.name}` — {reason} ({datetime.now(UTC).isoformat()})\n")
        self.log.error("nngyk.quarantine", file=path.name, reason=reason)
