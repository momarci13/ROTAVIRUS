"""Match name-only / postal-code-only sources (OKFŐ, municipal decrees) to
KSH codes.

Rule order (spec 6):
    (a) exact match on normalised name
    (b) match on postal code
    (c) fuzzy match above a threshold  -> NEVER auto-applied. Written to
        config/crosswalk_manual.csv with status='pending' and the run warns.
Unmatched rows are also recorded there (status='pending', no candidate) — never
dropped silently.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

import pandas as pd

from scraper import CONFIG_DIR
from scraper.core.config import Config
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.geography.crosswalk")

MANUAL_CSV = CONFIG_DIR / "crosswalk_manual.csv"
_MANUAL_HEADER = [
    "source_id",
    "raw_value",
    "raw_kind",
    "candidate_district_id",
    "candidate_district_name",
    "match_score",
    "status",
    "decided_by",
    "decided_at",
    "notes",
]


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalise_name(name: str, cfg: Config) -> str:
    rules = cfg.geography.crosswalk.get("name_normalisation", {})
    s = str(name)
    if rules.get("lowercase", True):
        s = s.lower()
    if rules.get("collapse_whitespace", True):
        s = " ".join(s.split())
    for tok in rules.get("drop_tokens", []):
        s = s.replace(str(tok).lower(), "")
    s = " ".join(s.split()).strip(" -,.")
    if rules.get("strip_accents", False):
        s = strip_accents(s)
    return s


def _token_sort_ratio(a: str, b: str) -> float:
    a2 = " ".join(sorted(a.split()))
    b2 = " ".join(sorted(b.split()))
    return SequenceMatcher(None, a2, b2).ratio() * 100.0


@dataclass(slots=True)
class MatchResult:
    raw_value: str
    raw_kind: str
    district_id: str | None
    district_name: str | None
    method: str  # exact_name | postal | fuzzy | none
    score: float
    status: str  # confirmed | pending


class Crosswalk:
    def __init__(self, settlements: pd.DataFrame, districts: pd.DataFrame, config: Config) -> None:
        self.config = config
        self.threshold = config.geography.fuzzy_threshold
        self._districts = districts

        s = settlements.copy()
        s["_norm"] = s["settlement_name"].map(lambda n: normalise_name(n, config))
        self._by_name: dict[str, str] = dict(zip(s["_norm"], s["district_id"]))

        d = districts.copy()
        d["_norm"] = d["district_name"].map(lambda n: normalise_name(n, config))
        # district-name direct hits too (municipal decrees often name the district)
        for norm, did in zip(d["_norm"], d["district_id"]):
            self._by_name.setdefault(norm, did)

        self._by_postal: dict[str, str] = {}
        for codes, did in zip(s.get("postal_codes", pd.Series([""] * len(s))), s["district_id"]):
            for code in str(codes).split(";"):
                code = code.strip()
                if code:
                    self._by_postal.setdefault(code, did)

        self._did_name = dict(zip(districts["district_id"], districts["district_name"]))
        self._manual = self._load_manual()

    # -- manual review file ------------------------------------------------
    def _load_manual(self) -> dict[tuple[str, str], dict]:
        out: dict[tuple[str, str], dict] = {}
        if not MANUAL_CSV.exists():
            return out
        with MANUAL_CSV.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(_decomment(fh)):
                if not row.get("raw_value"):
                    continue
                out[(row["raw_value"].strip().lower(), row.get("raw_kind", "name"))] = row
        return out

    def _append_manual(self, res: MatchResult, source_id: str, note: str) -> None:
        new_file = not MANUAL_CSV.exists()
        with MANUAL_CSV.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(_MANUAL_HEADER)
            w.writerow(
                [
                    source_id,
                    res.raw_value,
                    res.raw_kind,
                    res.district_id or "",
                    res.district_name or "",
                    f"{res.score:.1f}",
                    "pending",
                    "",
                    datetime.now(UTC).isoformat(),
                    note,
                ]
            )

    # -- matching --------------------------------------------------------
    def match(self, raw_value: str, *, kind: str = "name", source_id: str = "unknown") -> MatchResult:
        key = (str(raw_value).strip().lower(), kind)
        manual = self._manual.get(key)
        if manual and manual.get("status") == "confirmed" and manual.get("candidate_district_id"):
            did = manual["candidate_district_id"]
            return MatchResult(raw_value, kind, did, self._did_name.get(did), "manual", 100.0, "confirmed")
        if manual and manual.get("status") == "rejected":
            return MatchResult(raw_value, kind, None, None, "none", 0.0, "pending")

        if kind == "postal":
            code = str(raw_value).strip()
            did = self._by_postal.get(code)
            if did:
                return MatchResult(raw_value, kind, did, self._did_name.get(did), "postal", 100.0, "confirmed")
            return self._fuzzy_or_none(raw_value, kind, source_id)

        norm = normalise_name(raw_value, self.config)
        did = self._by_name.get(norm)
        if did:
            return MatchResult(raw_value, kind, did, self._did_name.get(did), "exact_name", 100.0, "confirmed")
        return self._fuzzy_or_none(raw_value, kind, source_id)

    def _fuzzy_or_none(self, raw_value: str, kind: str, source_id: str) -> MatchResult:
        norm = normalise_name(raw_value, self.config)
        best_id, best_score = None, 0.0
        for cand_norm, did in self._by_name.items():
            score = _token_sort_ratio(norm, cand_norm)
            if score > best_score:
                best_id, best_score = did, score
        if best_id is not None and best_score >= self.threshold:
            res = MatchResult(
                raw_value, kind, best_id, self._did_name.get(best_id), "fuzzy", best_score, "pending"
            )
            if (raw_value.strip().lower(), kind) not in self._manual:
                self._append_manual(res, source_id, "auto fuzzy candidate; needs human confirmation")
                log.warning(
                    "crosswalk.fuzzy_pending",
                    raw=raw_value,
                    candidate=best_id,
                    score=round(best_score, 1),
                )
            return res
        res = MatchResult(raw_value, kind, None, None, "none", best_score, "pending")
        if (raw_value.strip().lower(), kind) not in self._manual:
            self._append_manual(res, source_id, "no match; needs manual assignment")
            log.warning("crosswalk.unmatched", raw=raw_value, kind=kind)
        return res

    def match_frame(
        self, df: pd.DataFrame, *, column: str, kind: str = "name", source_id: str = "unknown"
    ) -> pd.DataFrame:
        """Add district_id / crosswalk_method / crosswalk_status columns.

        Rows that only reach a fuzzy/none result get district_id = NA and are
        NOT dropped — the caller keeps them with quality_flag set downstream.
        """
        out = df.copy()
        results = [self.match(v, kind=kind, source_id=source_id) for v in out[column]]
        out["district_id"] = [r.district_id if r.status == "confirmed" else pd.NA for r in results]
        out["crosswalk_method"] = [r.method for r in results]
        out["crosswalk_status"] = [r.status for r in results]
        out["crosswalk_score"] = [r.score for r in results]
        n_pending = int((out["crosswalk_status"] == "pending").sum())
        if n_pending:
            log.warning("crosswalk.frame_pending", source_id=source_id, pending=n_pending, total=len(out))
        return out


def _decomment(fh):
    for line in fh:
        if line.lstrip().startswith("#"):
            continue
        yield line
