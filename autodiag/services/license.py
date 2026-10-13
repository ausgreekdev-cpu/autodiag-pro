"""Freemium licensing: tiers, feature gates, signed license keys.

The app ships a **Free** tier (generic OBD-II read/clear, live gauges) with
**Pro** and **Workshop** tiers unlocked by a signed license key file today
and by Microsoft Store purchases in a later milestone. Verification is
pure-local (Ed25519 over the payload) — nothing ever leaves the machine.

Tier order is monotonic: a Workshop license satisfies Pro features.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace
from datetime import date
from enum import IntEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

#: Ed25519 public key verifying license files (private key never ships).
LICENSE_PUBLIC_KEY_B64 = "vPIr/q8T49+MeUtFRAFEns0zJZUroQZ1nysYB8d6JeU="

#: Bump when the EULA text changes — every existing user is re-prompted.
EULA_VERSION = "1"

#: Free tier keeps only the newest sessions in history.
HISTORY_FREE_LIMIT = 10


class Tier(IntEnum):
    """Ordered license tiers (higher value satisfies lower requirements)."""

    FREE = 0
    PRO = 1
    WORKSHOP = 2


TIER_LABELS = {
    Tier.FREE: "Free",
    Tier.PRO: "Pro",
    Tier.WORKSHOP: "Workshop",
}

#: feature id → minimum tier (unlisted features are free).
FEATURE_TIERS: dict[str, Tier] = {
    "history.full": Tier.PRO,
    "pdf.export": Tier.PRO,
    "uds.read": Tier.PRO,
    "uds.write": Tier.WORKSHOP,
    "work_order": Tier.WORKSHOP,
}

FEATURE_LABELS: dict[str, str] = {
    "history.full": "Full session history",
    "pdf.export": "PDF reports",
    "uds.read": "UDS module reads",
    "uds.write": "UDS write services",
    "work_order": "Work orders",
}

LICENSE_FORMAT = 1
_KEY_FILENAME = "license.json"


class LicenseError(Exception):
    """A license file is missing, malformed, expired or fails verification."""


def tier_label(tier: Tier) -> str:
    return TIER_LABELS[tier]


def feature_tier(feature: str) -> Tier:
    return FEATURE_TIERS.get(feature, Tier.FREE)


@dataclass(frozen=True)
class LicenseState:
    """The outcome of verifying one license file."""

    tier: Tier
    source: str = "default"  # default | key | store (store arrives in M36)
    licensee: str | None = None
    expires: date | None = None

    def effective_tier(self, today: date | None = None) -> Tier:
        """Tier after applying key expiry (expired keys fall back to Free)."""
        if self.expires is not None and (today or date.today()) > self.expires:
            return Tier.FREE
        return self.tier

    def allows(self, feature: str, today: date | None = None) -> bool:
        return self.effective_tier(today) >= feature_tier(feature)

    def history_limit(self, today: date | None = None) -> int | None:
        """Max visible sessions; ``None`` = unlimited."""
        if self.effective_tier(today) >= Tier.PRO:
            return None
        return HISTORY_FREE_LIMIT


FREE_STATE = LicenseState(Tier.FREE)


def _canonical_bytes(payload: dict) -> bytes:
    body = {key: payload[key] for key in sorted(payload) if key != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_date(text: object, field: str) -> date:
    if not isinstance(text, str):
        raise LicenseError(f"license {field} must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise LicenseError(f"license {field} is not a valid date: {text!r}") from exc


def _load_state(text: str, today: date | None = None) -> LicenseState:
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise LicenseError("license file is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise LicenseError("license file must contain a JSON object")
    if payload.get("format") != LICENSE_FORMAT:
        raise LicenseError(f"unsupported license format: {payload.get('format')!r}")

    raw_tier = payload.get("tier")
    if not isinstance(raw_tier, str):
        raise LicenseError("license tier is missing")
    try:
        tier = Tier[raw_tier.upper()]
    except KeyError as exc:
        raise LicenseError(f"unknown tier: {raw_tier!r}") from exc

    licensee = payload.get("licensee")
    if not isinstance(licensee, str) or not licensee.strip():
        raise LicenseError("license licensee is missing")

    issued = _parse_date(payload.get("issued"), "issued")
    effective_today = today or date.today()
    if issued > effective_today:
        raise LicenseError("license was issued in the future")

    expires: date | None = None
    if payload.get("expires") is not None:
        expires = _parse_date(payload.get("expires"), "expires")
        if expires <= issued:
            raise LicenseError("license expires before it was issued")
        if expires <= effective_today:
            raise LicenseError("license has expired")

    signature = payload.get("sig")
    if not isinstance(signature, str):
        raise LicenseError("license signature is missing")
    try:
        raw_sig = base64.b64decode(signature, validate=True)
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(LICENSE_PUBLIC_KEY_B64)
        )
        public.verify(raw_sig, _canonical_bytes(payload))
    except (InvalidSignature, ValueError) as exc:
        raise LicenseError("license signature is invalid") from exc

    return LicenseState(
        tier, source="key", licensee=licensee.strip(), expires=expires
    )


def sign_license(private_key_pem: bytes, payload: dict) -> str:
    """Sign a license payload (Ed25519) and return the base64 signature.

    Used by ``packaging/make_license.py`` and tests — never by the app.
    """
    private = _deserialize_private_key(private_key_pem)
    return base64.b64encode(private.sign(_canonical_bytes(payload))).decode("ascii")


def _deserialize_private_key(pem: bytes) -> Ed25519PrivateKey:
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LicenseError("signing key is not an Ed25519 private key")
    return key


def load_license_text(text: str, today: date | None = None) -> LicenseState:
    """Parse + verify license file text (raises :class:`LicenseError`)."""
    return _load_state(text, today)


def default_key_path():
    """Per-user license location beside the session store (AppData)."""
    from pathlib import Path

    from PySide6.QtCore import QStandardPaths

    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(base) / _KEY_FILENAME


class LicenseManager:
    """Resolves and mutates the active license for this install."""

    def __init__(self, key_path=None, state: LicenseState | None = None) -> None:
        from pathlib import Path

        if key_path is None:
            self._key_path = default_key_path()
        else:
            self._key_path = Path(key_path)
        if state is not None:
            # explicit state (tests / providers) — skip the on-disk key
            self._state = state
        else:
            self._state = FREE_STATE
            self.refresh()

    @property
    def key_path(self):
        return self._key_path

    def refresh(self) -> LicenseState:
        """Re-read the key file from disk (missing/invalid → Free)."""
        try:
            if self._key_path.is_file():
                self._state = _load_state(
                    self._key_path.read_text(encoding="utf-8")
                )
            else:
                self._state = FREE_STATE
        except (LicenseError, OSError):
            self._state = FREE_STATE
        return self._state

    def current(self) -> LicenseState:
        return self._state

    def install_key(self, path) -> LicenseState:
        """Validate the license file at ``path`` and persist it."""
        from pathlib import Path

        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise LicenseError(f"cannot read {source.name}") from exc
        state = _load_state(text)  # raises → caller shows the error
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_text(text, encoding="utf-8")
        self._state = state
        return state

    def remove_key(self) -> None:
        try:
            self._key_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._state = FREE_STATE


_MANAGER: LicenseManager | None = None


def get_license() -> LicenseManager:
    """Process-wide manager (tests and the Store provider swap it out)."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LicenseManager()
    return _MANAGER


def set_license(manager: LicenseManager | None) -> None:
    global _MANAGER
    _MANAGER = manager


def upgraded_state(manager: LicenseManager, tier: Tier) -> LicenseState:
    """Helper for tests/providers: a FREE state elevated to ``tier``."""
    return replace(FREE_STATE, tier=tier)
