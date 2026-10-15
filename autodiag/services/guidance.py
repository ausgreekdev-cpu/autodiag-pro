"""Local repair guidance: DTC causes/checks + freeze-frame context.

Offline heuristics only — no network, no LLM. Exact-code entries come from
the bundled ``dtc_guidance.json``; anything else falls back to a code-family
entry, then to a generic pointer at OEM documentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from autodiag.data import read_text

if TYPE_CHECKING:
    from autodiag.services.record import ScanRecord


@dataclass(frozen=True)
class Guidance:
    """Likely causes and first checks for one DTC."""

    code: str
    severity: str  # high | medium | low | info
    source: str  # code | family | generic
    causes: tuple[str, ...]
    checks: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "source": self.source,
            "causes": list(self.causes),
            "checks": list(self.checks),
        }


@lru_cache(maxsize=1)
def load_guidance() -> dict[str, Any]:
    """Bundled guidance data (cached after first load)."""
    return json.loads(read_text("dtc_guidance.json"))


_GENERIC = {
    "severity": "info",
    "causes": [
        "No bundled guidance for this code — it may be manufacturer-specific",
        "Confirm the exact description against OEM documentation",
    ],
    "checks": [
        "Inspect connectors and wiring for the affected system",
        "Look up OEM service procedures for this exact code",
    ],
}


def _family_entry(families: dict[str, Any], code: str) -> dict[str, Any] | None:
    for width in (3, 2, 1):
        entry = families.get(code[:width])
        if entry is not None:
            return entry
    return None


def guidance_for(code: str) -> Guidance | None:
    """Best-available guidance for a DTC (exact → family → generic)."""
    clean = (code or "").strip().upper()
    if len(clean) < 5 or clean[0] not in "PBCU":
        return None
    data = load_guidance()
    entry = data.get("codes", {}).get(clean)
    source = "code"
    if entry is None:
        entry = _family_entry(data.get("families", {}), clean)
        source = "family"
    if entry is None:
        entry = _GENERIC
        source = "generic"
    return Guidance(
        code=clean,
        severity=entry["severity"],
        source=source,
        causes=tuple(entry["causes"]),
        checks=tuple(entry["checks"]),
    )


def freeze_hints(record: ScanRecord | None) -> list[str]:
    """One-line hints from the freeze frame captured when the DTC was set."""
    hints: list[str] = []
    frame = (record.freeze or {}).get(0) if record is not None else None
    if not frame:
        return hints
    coolant = frame.get(0x05)
    if coolant is not None:
        if coolant < 70:
            hints.append(
                f"Coolant was {coolant:g}°C when the fault was set — "
                "cold-start / warmup conditions"
            )
        elif coolant > 105:
            hints.append(
                f"Coolant was {coolant:g}°C when the fault was set — engine was hot"
            )
    rpm = frame.get(0x0C)
    if rpm is not None:
        if rpm > 3500:
            hints.append(f"Engine speed was {rpm:g} rpm — fault occurred under load")
        elif rpm < 900:
            hints.append(f"Engine speed was {rpm:g} rpm — fault occurred near idle")
    speed = frame.get(0x0D)
    if speed is not None:
        if speed == 0:
            hints.append("Vehicle was stationary when the fault was set")
        elif speed > 100:
            hints.append(
                f"Vehicle speed was {speed:g} km/h — fault occurred at highway speed"
            )
    load = frame.get(0x04)
    if load is not None and load > 70:
        hints.append(f"Engine load was {load:g}% — fault occurred under high load")
    throttle = frame.get(0x11)
    if throttle is not None and throttle > 60:
        hints.append(
            f"Throttle was {throttle:g}% open — fault occurred during acceleration"
        )
    return hints


def readiness_hint(record: ScanRecord | None) -> str | None:
    """Drive-cycle reminder when monitors are still incomplete."""
    monitors = record.monitors if record is not None else None
    if monitors is None:
        return None
    pending = [m for m in monitors.monitors if m.supported and not m.complete]
    if not pending:
        return None
    return (
        f"{len(pending)} readiness monitor(s) not complete — "
        "drive a full cycle after repair to verify the fix"
    )


def hints_for(record: ScanRecord | None) -> list[str]:
    """Freeze-frame + readiness context for the session."""
    hints = freeze_hints(record)
    note = readiness_hint(record)
    if note:
        hints.append(note)
    return hints
