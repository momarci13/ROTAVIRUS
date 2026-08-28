"""Deterministic seeding for every sampling step (PSA, Dirichlet weights, EB)."""

from __future__ import annotations

import os
import random

import numpy as np

_DEFAULT = 20260101


def resolve_seed(seed: int | None = None) -> int:
    if seed is not None:
        return int(seed)
    env = os.environ.get("ROTAVIRUS_SEED")
    if env:
        return int(env)
    return _DEFAULT


def seed_everything(seed: int | None = None) -> int:
    s = resolve_seed(seed)
    random.seed(s)
    np.random.seed(s % (2**32 - 1))
    os.environ["PYTHONHASHSEED"] = str(s)
    return s


def rng(seed: int | None = None) -> np.random.Generator:
    """A fresh, independent NumPy Generator for a specific sub-task."""
    return np.random.default_rng(resolve_seed(seed))
