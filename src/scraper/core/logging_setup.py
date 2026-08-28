"""structlog configuration: JSON lines to ``logs/`` and human-readable console."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

import structlog

from scraper import LOGS_DIR
from scraper.core.config import LoggingConfig

_CONFIGURED = False


def configure_logging(cfg: LoggingConfig | None = None, *, level: str | None = None) -> None:
    """Idempotently configure structlog + stdlib logging from ``LoggingConfig``."""
    global _CONFIGURED
    cfg = cfg or LoggingConfig()
    lvl_name = (level or cfg.level or "INFO").upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    ts_key = cfg.timestamps.get("key", "timestamp")
    use_utc = bool(cfg.timestamps.get("utc", True))

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=use_utc, key=ts_key),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    for k, v in (cfg.extra_context or {}).items():
        shared.append(_bind_static(k, v))

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(lvl),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(lvl)

    if cfg.console.get("enabled", True):
        console = logging.StreamHandler(sys.stderr)
        console_fmt = structlog.stdlib.ProcessorFormatter(
            processor=(
                structlog.dev.ConsoleRenderer(colors=bool(cfg.console.get("colours", True)))
                if cfg.console.get("format", "human") == "human"
                else structlog.processors.JSONRenderer()
            ),
            foreign_pre_chain=shared,
        )
        console.setFormatter(console_fmt)
        root.addHandler(console)

    if cfg.file.get("enabled", True):
        directory = Path(cfg.file.get("directory", LOGS_DIR))
        directory.mkdir(parents=True, exist_ok=True)
        tmpl = cfg.file.get("filename_template", "run_{date}.jsonl")
        fpath = directory / tmpl.format(date=date.today().isoformat())
        fh = logging.FileHandler(fpath, encoding="utf-8")
        fh.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),
                foreign_pre_chain=shared,
            )
        )
        root.addHandler(fh)

    _CONFIGURED = True


def _bind_static(key: str, value: Any):
    def processor(_logger, _name, event_dict):
        event_dict.setdefault(key, value)
        return event_dict

    return processor


def get_logger(name: str = "scraper", **initial: Any) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name).bind(**initial)
