"""Exception hierarchy for the pipeline.

Every failure mode the spec calls out has a dedicated type so callers (and tests)
can distinguish "stop the run" from "flag and continue".
"""

from __future__ import annotations


class ScraperError(Exception):
    """Base class for every error raised by this package."""


# --------------------------------------------------------------------- config ---
class ConfigError(ScraperError):
    """A config file is missing, malformed, or fails pydantic validation."""


# ------------------------------------------------------------------ collectors ---
class CollectorError(ScraperError):
    """Generic collector failure."""


class DiscoveryError(CollectorError):
    """A listing / directory index could not be parsed to enumerate resources."""


class DownloadError(CollectorError):
    """An HTTP download failed after retries (non-404) or returned unusable bytes."""


class BrokenLinkError(CollectorError):
    """A configured URL returned 404. Logged to BROKEN_LINKS.md; run continues."""


class RenderRequiredError(CollectorError):
    """The page needs a JS renderer and neither --render nor a manual export is available."""


class ManualExportMissingError(CollectorError):
    """A robots-disallowed / registration-gated source needs a manual export that is absent."""


# --------------------------------------------------------------------- parsing ---
class ParseError(ScraperError):
    """A downloaded file could not be parsed into the expected shape."""


class PDFExtractionError(ParseError):
    """Every PDF table-extraction strategy failed the structure check."""


class SumMismatchError(ParseError):
    """A cross-table sum check failed. The record is quarantined, not dropped."""


class SchemaDriftError(ParseError):
    """A source's column fingerprint changed. Reported and flagged; run continues."""


# ------------------------------------------------------------------ validation ---
class ValidationError(ScraperError):
    """A validation rule failed hard (rules that must stop the run)."""


class EvidenceClassViolation(ValidationError):
    """district + observed + rotavirus without the nngyk_foia collector, or similar."""


class SurveillanceBreakViolation(ValidationError):
    """A rotavirus record with period_start before the 2014 surveillance break."""


class PriceYearMixError(ValidationError):
    """A computed cost field mixes components with different price_year without deflation."""


# ----------------------------------------------------------------------- costs ---
class MissingParameterError(ScraperError):
    """A required cost parameter is null. Names the parameter and its source_url.

    NEVER caught-and-defaulted: the cost model must halt.
    """


# ------------------------------------------------------------------ allocation ---
class AllocationError(ScraperError):
    """Budget constraint violated, unknown scenario, or an unresolvable symbol."""
