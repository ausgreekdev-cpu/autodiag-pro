"""Bundled DTC description lookup (5,112 codes, Apache-2.0 — see LICENSE-dtc-data.txt)."""

from __future__ import annotations

import json
from functools import lru_cache

from autodiag.data import read_text


@lru_cache(maxsize=1)
def load_dictionary() -> dict[str, str]:
    """Code → description map (cached after first load)."""
    return json.loads(read_text("dtc_dictionary.json"))


def describe(code: str) -> str | None:
    """Plain-English description for a code like ``"P0301"``, or ``None``."""
    return load_dictionary().get(code.upper())
