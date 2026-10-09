"""UDS (ISO 14229-1) builders, response parsing, request validation."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from autodiag.obd import uds
from autodiag.obd.uds import UdsError, UdsResponse


def test_request_builders_emit_hex():
    assert uds.session_control(0x03) == "1003"
    assert uds.tester_present() == "3E00"
    assert uds.read_data_by_identifier([0xF190]) == "22F190"
    assert uds.read_data_by_identifier([0xF190, 0xF195]) == "22F190F195"
    assert uds.read_dtc_by_status_mask() == "1902FF"
    assert uds.read_dtc_by_status_mask(0x08) == "190208"
    with pytest.raises(ValueError):
        uds.read_data_by_identifier([])


def test_response_header_is_tx_plus_eight():
    assert uds.response_header("7E0") == "7E8"
    assert uds.response_header("7E1") == "7E9"
    assert uds.response_header("7e4") == "7EC"


def test_parse_positive_response_keeps_did_echo():
    response = uds.parse_response("62F19031444750")
    assert response.sid == 0x62
    assert response.payload == bytes.fromhex("F19031444750")
    assert response.raw == "62F19031444750"


def test_parse_positive_across_iso_tp_lines():
    response = uds.parse_response("0: 62 F1 90 31 44\r\n1: 47 50")
    assert response.sid == 0x62
    assert response.payload == bytes.fromhex("F19031444750")


def test_parse_negative_response_raises_with_nrc():
    with pytest.raises(UdsError) as excinfo:
        uds.parse_response("7F2231")
    error = excinfo.value
    assert error.sid == 0x22
    assert error.nrc == 0x31
    assert "requestOutOfRange" in str(error)
    assert "0x31" in str(error)


def test_parse_pending_and_unknown_nrc():
    with pytest.raises(UdsError) as pending:
        uds.parse_response("7F2278")
    assert pending.value.nrc == 0x78
    assert "requestPending" in str(pending.value)

    with pytest.raises(UdsError) as unknown:
        uds.parse_response("7F10AA")
    assert unknown.value.nrc == 0xAA
    assert "NRC 0xAA" in str(unknown.value)


def test_parse_rejects_garbage_and_empty():
    with pytest.raises(UdsError):
        uds.parse_response("")
    with pytest.raises(UdsError) as excinfo:
        uds.parse_response("NOT HEX AT ALL")
    assert "not valid hex" in str(excinfo.value)
    with pytest.raises(UdsError):
        uds.parse_response("05")  # plausible hex, not a UDS SID


def test_validate_request_whitelists_read_only_services():
    assert uds.validate_request("22F190") is None
    assert uds.validate_request(" 3e 00 ") is None
    assert uds.validate_request("1003") is None
    assert uds.validate_request("1902FF") is None

    write = uds.validate_request("2EF19000")
    assert write is not None and "WriteDataByIdentifier" in write
    routine = uds.validate_request("31010001")
    assert routine is not None and "RoutineControl" in routine
    iocontrol = uds.validate_request("2F0103")
    assert iocontrol is not None and "IOControlByIdentifier" in iocontrol
    other = uds.validate_request("14000000")
    assert other is not None and "$14" in other

    assert uds.validate_request("22F19") is not None  # odd length
    assert uds.validate_request("") is not None
    assert uds.validate_request("22ZZ") is not None


def test_decode_did_vin_ascii_and_hex_fallback():
    assert uds.decode_did(0xF190, b"1D4GP00R56B123457") == "1D4GP00R56B123457"
    assert uds.decode_did(0xF190, b"1D4GP00R56B123457\x00\x00") == "1D4GP00R56B123457"
    assert uds.decode_did(0xF191, b"SW1.2.3") == "SW1.2.3"
    assert uds.decode_did(0xF194, bytes.fromhex("00AABB")) == "00 AA BB"
    assert uds.decode_did(0xF191, b"") == "(no data)"


def test_response_dataclass_is_immutable():
    response = UdsResponse(sid=0x62, payload=b"\x01", raw="62")
    with pytest.raises(FrozenInstanceError):
        response.sid = 0x50  # type: ignore[misc]
