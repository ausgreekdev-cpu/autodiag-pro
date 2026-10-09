"""UDS (ISO 14229-1) request builders and response parsing.

Requests ride the existing ELM327 serial link as raw hex (like ``0100``);
physical addressing wraps the exchange in ``AT SH``/``AT CRA`` — the engine
job restores the functional default afterwards so normal OBD polling is
unaffected. Only read-oriented services are accepted here: write and
bi-directional services ($2E/$31/$2F) are a deliberate later milestone that
needs explicit safety warnings first.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from autodiag.obd import framing

# Common negative response codes (ISO 14229-1 table); unknown codes fall back
# to a numeric name in :func:`parse_response`.
NRC_MESSAGES: dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x78: "requestPending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
    0x81: "rpmTooLow",
    0x82: "rpmTooHigh",
    0x83: "engineNotRunning",
    0x84: "engineTooCold",
}

NEGATIVE_SID = 0x7F
POSITIVE_MIN = 0x40
POSITIVE_MAX = 0x7E

#: Services this milestone permits — reads only, no writes or actuation.
READ_ONLY_SERVICES = frozenset({0x10, 0x19, 0x22, 0x3E})

#: ISO 15765-4 11-bit physical header for the first ECU; responses come from
#: TX + 8 (``7E0`` → ``7E8``). Editable per ECU in the panel.
DEFAULT_TX_HEADER = "7E0"

#: Standardised DIDs (ISO 14229-1); OEMs may repurpose the non-VIN ones.
KNOWN_DIDS: dict[int, str] = {
    0xF190: "VIN",
    0xF191: "ECU software number",
    0xF192: "ECU software version",
    0xF193: "ECU hardware number",
    0xF194: "ECU serial number",
    0xF195: "System supplier ECU number",
}

# Same shape as vehicle.py's VIN matcher (DIDs carry the VIN as ASCII).
_VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")


class UdsError(Exception):
    """Negative or unparseable UDS response.

    ``sid``/``nrc`` carry the structured fields when available (negative
    responses), mirroring how :class:`ElmError` names its ``kind``.
    """

    def __init__(
        self, message: str, *, sid: int | None = None, nrc: int | None = None,
        raw: str = "",
    ) -> None:
        super().__init__(message)
        self.sid = sid
        self.nrc = nrc
        self.raw = raw


@dataclass(frozen=True)
class UdsResponse:
    """Positive response: response SID (request SID + 0x40) plus payload."""

    sid: int
    payload: bytes
    raw: str


# -- request builders (return ELM-ready hex, no spaces) ------------------------


def session_control(session: int) -> str:
    """``$10`` DiagnosticSessionControl (e.g. ``0x03`` extended session)."""
    return f"10{session:02X}"


def tester_present() -> str:
    """``$3E`` TesterPresent (sub-function 0x00, response not suppressed)."""
    return "3E00"


def read_data_by_identifier(dids: Sequence[int]) -> str:
    """``$22`` ReadDataByIdentifier — one or more 16-bit DIDs."""
    if not dids:
        raise ValueError("at least one DID is required")
    return "22" + "".join(f"{did:04X}" for did in dids)


def read_dtc_by_status_mask(mask: int = 0xFF) -> str:
    """``$19`` ReadDTCInformation sub-function 0x02 (by DTC status mask)."""
    return f"1902{mask:02X}"


def response_header(tx_header: str) -> str:
    """Expected response ID for a transmit header (TX + 8 on CAN 11-bit)."""
    return f"{int(tx_header, 16) + 8:03X}"


def validate_request(hex_request: str) -> str | None:
    """Guard for raw requests: message when it must not be sent (None = ok).

    Enforces the read-only service whitelist — write/actuation services are
    rejected before they ever reach the bus.
    """
    cleaned = "".join(hex_request.split()).upper()
    if not cleaned or len(cleaned) % 2 or any(c not in "0123456789ABCDEF" for c in cleaned):
        return "Request must be an even number of hex digits (e.g. 22F190)."
    sid = int(cleaned[:2], 16)
    if sid not in READ_ONLY_SERVICES:
        label = {
            0x2E: "WriteDataByIdentifier",
            0x31: "RoutineControl",
            0x2F: "IOControlByIdentifier",
        }.get(sid, f"service ${sid:02X}")
        return f"{label} writes or actuates — only read services are allowed here."
    return None


# -- response parsing ----------------------------------------------------------


def parse_response(text: str) -> UdsResponse:
    """Parse a cleaned adapter response into a :class:`UdsResponse`.

    Raises :class:`UdsError` for negative responses (``7F <sid> <nrc>``),
    empty output, or anything that is not a plausible UDS reply.
    """
    try:
        payload = framing.hex_to_bytes(framing.flatten_response(text))
    except ValueError as exc:
        raise UdsError(f"Response is not valid hex: {text!r}", raw=text) from exc
    if not payload:
        raise UdsError("Empty UDS response", raw=text)

    first = payload[0]
    if first == NEGATIVE_SID:
        if len(payload) < 3:
            raise UdsError(f"Truncated negative response: {text!r}", raw=text)
        sid, nrc = payload[1], payload[2]
        name = NRC_MESSAGES.get(nrc, f"NRC 0x{nrc:02X}")
        raise UdsError(
            f"{name} (NRC 0x{nrc:02X} for service ${sid:02X})",
            sid=sid,
            nrc=nrc,
            raw=text,
        )
    if POSITIVE_MIN <= first <= POSITIVE_MAX:
        return UdsResponse(sid=first, payload=bytes(payload[1:]), raw=text)
    raise UdsError(f"Unexpected UDS response byte 0x{first:02X}", raw=text)


def decode_did(did: int, payload: bytes) -> str:
    """Human-readable DID value: VIN/ASCII when printable, spaced hex otherwise."""
    trimmed = bytes(payload).rstrip(b"\x00")
    if did == 0xF190 and trimmed:
        ascii_text = "".join(chr(b) for b in trimmed if 0x20 <= b < 0x7F)
        match = _VIN_RE.search(ascii_text)
        if match:
            return match.group(0)
    if trimmed and all(0x20 <= b <= 0x7E for b in trimmed):
        return trimmed.decode("ascii")
    return " ".join(f"{b:02X}" for b in payload) or "(no data)"
