"""Curated UDS preset library ($2F IO control, $31 routine control).

Pure Python, no Qt. Presets come from the bundled ``uds_presets.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from autodiag.data import read_text


@dataclass(frozen=True)
class UdsPreset:
    """One named bi-directional control preset."""

    name: str
    service: str  # "2F" or "31"
    request: str
    description: str
    oem: str
    tier: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "service": self.service,
            "request": self.request,
            "description": self.description,
            "oem": self.oem,
            "tier": self.tier,
        }


@lru_cache(maxsize=1)
def load_presets() -> tuple[UdsPreset, ...]:
    """Bundled preset list (cached after first load)."""
    data = json.loads(read_text("uds_presets.json"))
    return tuple(
        UdsPreset(
            name=item["name"],
            service=item["service"],
            request=item["request"],
            description=item["description"],
            oem=item["oem"],
            tier=item["tier"],
        )
        for item in data.get("presets", [])
    )


def presets_for(service: str) -> tuple[UdsPreset, ...]:
    """Presets for one service code (e.g. ``"2F"`` or ``"31"``)."""
    return tuple(p for p in load_presets() if p.service == service.upper())


def preset_by_name(name: str) -> UdsPreset | None:
    """Look up a preset by its display name."""
    for preset in load_presets():
        if preset.name == name:
            return preset
    return None


def preset_names(service: str | None = None) -> tuple[str, ...]:
    """Display names, optionally filtered by service."""
    if service is None:
        return tuple(p.name for p in load_presets())
    return tuple(p.name for p in presets_for(service))
