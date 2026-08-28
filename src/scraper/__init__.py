"""Hungarian district-level rotavirus data-collection and need-based
support-allocation pipeline.

The package is deliberately split so that *what* is computed (formulas, weights,
thresholds, prices, scenarios) lives in ``config/*.yaml`` and *how* it is
computed lives here. No parameter, weight, threshold, price or scenario
definition is hard-coded in Python.
"""

from __future__ import annotations

__version__ = "0.1.0"

# Repository layout anchors, resolved relative to this file so the CLI works
# regardless of the current working directory.
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
PROCESSED_DIR = DATA_DIR / "processed"
METADATA_DIR = DATA_DIR / "metadata"
LOGS_DIR = REPO_ROOT / "logs"

__all__ = [
    "CONFIG_DIR",
    "DATA_DIR",
    "INTERMEDIATE_DIR",
    "LOGS_DIR",
    "METADATA_DIR",
    "PACKAGE_ROOT",
    "PROCESSED_DIR",
    "RAW_DIR",
    "REPO_ROOT",
    "__version__",
]
