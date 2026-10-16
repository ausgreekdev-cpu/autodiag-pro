"""Security Gateway (SGW) unlock assistant — Ford-style $27 relay.

Modern gateways (e.g. the Ford SGM behind header 7E2) act as a firewall for
the modules behind them. Unlocking uses ISO 14229-1 ``$27`` security access
on the gateway itself: request a seed, compute the key with an authorized
tool, send the key back — the gateway then grants temporary access
(typically 30 minutes, or until ignition-off).

This service is a **relay**: it orchestrates the seed/key exchange but never
computes keys itself. ``Send`` is injectable so the flow is testable without
a vehicle; callers provide ``(hex_request, tx_header) -> response text``
(``None`` when the adapter failed).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from autodiag.obd import uds

Send = Callable[[str, str], "str | None"]

DEFAULT_GATEWAY_HEADER = "7E2"
UNLOCK_DURATION = timedelta(minutes=30)

#: Identity DIDs read while probing (ISO 14229-1 standardized range).
_IDENTITY_DIDS = (0xF194, 0xF192)


@dataclass(frozen=True)
class GatewayInfo:
    header: str
    ecu_serial: str | None
    software: str | None


@dataclass(frozen=True)
class SeedChallenge:
    header: str
    seed: bytes


@dataclass(frozen=True)
class UnlockResult:
    header: str
    ok: bool
    detail: str
    unlocked_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class UnlockState:
    """Session state after a successful unlock."""

    header: str
    unlocked_at: datetime
    expires_at: datetime

    @property
    def active(self) -> bool:
        return datetime.now(UTC) < self.expires_at


def _read_identity_did(send: Send, header: str, did: int) -> str | None:
    text = send(uds.read_data_by_identifier((did,)), header)
    if text is None:
        return None
    try:
        response = uds.parse_response(text)
    except uds.UdsError:
        return None
    # Positive $22 payload: DID echo + data (response SID is stripped).
    data = response.payload[2:]
    return uds.decode_did(did, data) or None


def probe_gateway(send: Send, header: str = DEFAULT_GATEWAY_HEADER) -> GatewayInfo | None:
    """Ping the gateway module and read its identity DIDs.

    Returns ``None`` when nothing answers (wrong bus, no gateway, or the
    adapter failed) — the caller should surface that as "not found".
    """
    text = send(uds.tester_present(), header)
    if text is None:
        return None
    try:
        uds.parse_response(text)
    except uds.UdsError:
        return None
    return GatewayInfo(
        header=header,
        ecu_serial=_read_identity_did(send, header, _IDENTITY_DIDS[0]),
        software=_read_identity_did(send, header, _IDENTITY_DIDS[1]),
    )


def request_seed(send: Send, header: str = DEFAULT_GATEWAY_HEADER) -> SeedChallenge | None:
    """``$27 01`` — ask the gateway for its security seed."""
    text = send(uds.security_access_request_seed(), header)
    if text is None:
        return None
    try:
        response = uds.parse_response(text)
    except uds.UdsError:
        return None
    if response.sid != 0x67:
        return None
    # Positive $27 payload: sub-function echo followed by the seed bytes.
    if len(response.payload) < 2 or response.payload[0] != 0x01:
        return None
    seed = bytes(response.payload[1:])
    return SeedChallenge(header=header, seed=seed) if seed else None


def send_key(send: Send, header: str, key: bytes) -> bool:
    """``$27 02`` — return the computed key; True when the gateway accepts it."""
    text = send(uds.security_access_send_key(key), header)
    if text is None:
        return False
    try:
        uds.parse_response(text)
    except uds.UdsError:
        return False
    return True


def unlock(
    send: Send,
    header: str,
    key_provider: Callable[[SeedChallenge], bytes | None],
    *,
    now: datetime | None = None,
) -> UnlockResult:
    """Full flow: probe → seed → ``key_provider`` → send key.

    ``key_provider`` is how an authorized tool plugs in: given the challenge
    it returns the key bytes, or ``None`` to abort.
    """
    if probe_gateway(send, header) is None:
        return UnlockResult(header=header, ok=False, detail="no gateway answered")
    challenge = request_seed(send, header)
    if challenge is None:
        return UnlockResult(header=header, ok=False, detail="seed request denied")
    key = key_provider(challenge)
    if key is None:
        return UnlockResult(header=header, ok=False, detail="no key provided")
    if not send_key(send, header, key):
        return UnlockResult(header=header, ok=False, detail="key rejected")
    moment = now or datetime.now(UTC)
    return UnlockResult(
        header=header,
        ok=True,
        detail="unlocked",
        unlocked_at=moment,
        expires_at=moment + UNLOCK_DURATION,
    )
