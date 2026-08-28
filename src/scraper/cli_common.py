"""Shared CLI wiring: env loading, config, logging, HTTP client, manifest."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from scraper.core.config import Config, load_config
from scraper.core.http import HTTPClient
from scraper.core.logging_setup import configure_logging, get_logger
from scraper.core.seeds import seed_everything


@dataclass(slots=True)
class Runtime:
    config: Config
    http: HTTPClient | None
    log_level: str
    use_cache: bool
    render: bool
    max_workers: int
    seed: int


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # pragma: no cover
        pass


def build_runtime(
    *,
    config_dir: Path | str | None = None,
    log_level: str = "INFO",
    use_cache: bool = True,
    render: bool = False,
    max_workers: int = 4,
    with_http: bool = True,
) -> Runtime:
    _load_dotenv()
    config = load_config(config_dir)
    configure_logging(config.logging, level=log_level)
    seed = seed_everything(config.seed() or None)
    get_logger("scraper.cli").info(
        "runtime.init", log_level=log_level, cache=use_cache, render=render, seed=seed
    )

    http: HTTPClient | None = None
    if with_http:
        contact = os.environ.get("CONTACT_EMAIL", "unset")
        http = HTTPClient(
            user_agent=config.sources.user_agent(contact),
            use_cache=use_cache,
            default_rate_limit=float(config.sources.defaults.get("rate_limit_seconds", 1.0)),
            max_retries=int(config.sources.defaults.get("max_retries", 5)),
            timeout=int(config.sources.defaults.get("timeout_seconds", 60)),
        )
    return Runtime(
        config=config,
        http=http,
        log_level=log_level,
        use_cache=use_cache,
        render=render,
        max_workers=max_workers,
        seed=seed,
    )


def command_string() -> str:
    parts = [Path(sys.argv[0]).name.replace(".py", ""), *sys.argv[1:]]
    return ("python -m " + " ".join(parts)).replace("scraper/", "scraper.")
