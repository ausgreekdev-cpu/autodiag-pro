"""NHTSA lookups: VIN decode (vPIC) and open recalls — opt-in, press-triggered.

Two official, free, key-less US DOT services. Pure Python with an
injectable fetch (same pattern as :mod:`autodiag.services.update_check`) so
tests never leave the machine; nothing runs unless the user presses the
"Look up VIN (NHTSA)" button in the Vehicle info panel.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from autodiag import __version__

DECODE_URL = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/"
    "{vin}?format=json"
)
RECALLS_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
DEFAULT_TIMEOUT = 8.0

Fetch = Callable[[str, float], Any]

_DETAIL_KEYS = (
    "vin",
    "make",
    "model",
    "year",
    "body_class",
    "cylinders",
    "displacement_l",
    "fuel",
    "trim",
)


def fetch_json(url: str, timeout: float) -> Any:
    """GET ``url`` and parse the JSON body (stdlib only, like update_check)."""
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoints
        url,
        headers={
            "User-Agent": f"autodiag-pro/{__version__}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} from NHTSA"
    if isinstance(exc, urllib.error.URLError):
        return f"network error ({exc.reason})"
    if isinstance(exc, TimeoutError):
        return "request timed out"
    if isinstance(exc, (ValueError, KeyError, TypeError, IndexError)):
        return "unexpected response from NHTSA"
    return str(exc) or type(exc).__name__


@dataclass(frozen=True)
class DecodeResult:
    """VIN decode outcome; ``status`` is ``"ok"`` or ``"error"``."""

    status: str
    vin: str
    message: str | None = None  # failure reason (error status only)
    warning: str | None = None  # vPIC ErrorCode text (partial VIN, etc.)
    make: str | None = None
    model: str | None = None
    year: str | None = None
    body_class: str | None = None
    cylinders: str | None = None
    displacement_l: str | None = None
    fuel: str | None = None
    trim: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def engine_text(self) -> str | None:
        parts: list[str] = []
        if self.cylinders:
            parts.append(f"{self.cylinders}-cyl")
        if self.displacement_l:
            parts.append(f"{self.displacement_l} L")
        if self.fuel:
            parts.append(self.fuel)
        return " · ".join(parts) or None

    @property
    def spec(self) -> dict[str, Any]:
        """Flat dict for reports / ``record_event("nhtsa", …)`` payloads."""
        return {key: getattr(self, key) for key in _DETAIL_KEYS}


@dataclass(frozen=True)
class Recall:
    campaign: str
    component: str
    received: str
    summary: str
    consequence: str
    remedy: str


@dataclass(frozen=True)
class RecallResult:
    """Recall lookup outcome: ``"ok"``, ``"error"``, or ``"skipped"``."""

    status: str
    message: str | None = None
    recalls: tuple[Recall, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def decode_vin(
    vin: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch: Fetch | None = None,
) -> DecodeResult:
    """Decode ``vin`` through vPIC. Never raises — failures become ``status``."""
    cleaned = (vin or "").strip().upper()
    if not cleaned:
        return DecodeResult(status="error", vin="", message="no VIN to decode")
    get = fetch or fetch_json
    url = DECODE_URL.format(vin=urllib.parse.quote(cleaned, safe=""))
    try:
        payload = get(url, timeout)
        results = payload["Results"]
        first = results[0]
        if not isinstance(first, dict):
            raise TypeError("Results[0] is not an object")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
    ) as exc:
        return DecodeResult(status="error", vin=cleaned, message=_describe(exc))

    def text(key: str) -> str | None:
        value = first.get(key)
        if value is None:
            return None
        trimmed = str(value).strip()
        return trimmed or None

    code = text("ErrorCode")
    warning = text("ErrorText") if code and code != "0" else None
    make = text("Make")
    if not make:
        return DecodeResult(
            status="error",
            vin=cleaned,
            warning=warning,
            message=warning or "NHTSA has no data for this VIN",
        )
    return DecodeResult(
        status="ok",
        vin=cleaned,
        warning=warning,
        make=make,
        model=text("Model"),
        year=text("ModelYear"),
        body_class=text("BodyClass"),
        cylinders=text("EngineCylinders"),
        displacement_l=text("DisplacementL"),
        fuel=text("FuelTypePrimary"),
        trim=text("Trim"),
    )


def fetch_recalls(
    vehicle: DecodeResult,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch: Fetch | None = None,
) -> RecallResult:
    """Look up open recalls by decoded make/model/year (skips when incomplete)."""
    make = (vehicle.make or "").strip()
    model = (vehicle.model or "").strip()
    year = (vehicle.year or "").strip()
    if not (make and model and year):
        return RecallResult(
            status="skipped", message="make, model and year required"
        )
    get = fetch or fetch_json
    query = urllib.parse.urlencode(
        {"make": make, "model": model, "modelYear": year}
    )
    try:
        payload = get(f"{RECALLS_URL}?{query}", timeout)
        results = payload["results"]
        if not isinstance(results, list):
            raise TypeError("results is not a list")
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
    ) as exc:
        return RecallResult(status="error", message=_describe(exc))
    recalls = tuple(
        Recall(
            campaign=str(item.get("NHTSACampaignNumber") or "").strip(),
            component=str(item.get("Component") or "").strip(),
            received=str(item.get("ReportReceivedDate") or "").strip(),
            summary=str(item.get("Summary") or "").strip(),
            consequence=str(item.get("Consequence") or "").strip(),
            remedy=str(item.get("Remedy") or "").strip(),
        )
        for item in results
        if isinstance(item, dict)
    )
    return RecallResult(status="ok", recalls=recalls)


def lookup(
    vin: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch: Fetch | None = None,
) -> tuple[DecodeResult, RecallResult]:
    """Decode then (when possible) fetch recalls — one call for the worker."""
    decoded = decode_vin(vin, timeout=timeout, fetch=fetch)
    if not decoded.ok:
        return decoded, RecallResult(status="skipped", message="decode failed")
    return decoded, fetch_recalls(decoded, timeout=timeout, fetch=fetch)
