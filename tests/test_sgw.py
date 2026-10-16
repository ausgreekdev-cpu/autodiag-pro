"""SGW unlock service tests — fakes injected, no vehicle."""

from __future__ import annotations

from autodiag.services import sgw


def _scripted_send(responses: dict[str, str]):
    def send(request: str, _header: str) -> str | None:
        for fragment, text in responses.items():
            if fragment in request:
                return text
        return None

    return send


def test_probe_gateway_found():
    send = _scripted_send(
        {
            "3E00": "7E00",
            "22F194": "62F1945347574D31",
            "22F192": "62F19241424344",
        }
    )
    info = sgw.probe_gateway(send)
    assert info is not None
    assert info.header == "7E2"
    assert info.ecu_serial == "SGWM1"
    assert info.software == "ABCD"


def test_probe_gateway_not_found():
    assert sgw.probe_gateway(_scripted_send({})) is None


def test_probe_gateway_negative_response():
    assert sgw.probe_gateway(_scripted_send({"3E00": "7F3E11"})) is None


def test_request_seed():
    send = _scripted_send({"2701": "6701A1B2C3D4"})
    challenge = sgw.request_seed(send)
    assert challenge is not None
    assert challenge.seed == bytes.fromhex("A1B2C3D4")


def test_request_seed_denied():
    assert sgw.request_seed(_scripted_send({"2701": "7F2722"})) is None


def test_send_key_accepted():
    send = _scripted_send({"2702": "6702"})
    assert sgw.send_key(send, "7E2", bytes.fromhex("A1B2C3D4"))


def test_send_key_rejected():
    send = _scripted_send({"2702": "7F2722"})
    assert not sgw.send_key(send, "7E2", b"\x00")


def test_unlock_full_flow():
    send = _scripted_send(
        {
            "3E00": "7E00",
            "22F194": "62F1945347574D31",
            "2701": "6701A1B2C3D4",
            "2702": "6702",
        }
    )
    result = sgw.unlock(send, "7E2", lambda _challenge: bytes.fromhex("BEEF"))
    assert result.ok
    assert result.detail == "unlocked"
    assert result.expires_at is not None


def test_unlock_aborts_without_gateway():
    result = sgw.unlock(_scripted_send({}), "7E2", lambda _challenge: b"\x00")
    assert not result.ok
    assert result.detail == "no gateway answered"


def test_unlock_aborts_when_key_provider_declines():
    send = _scripted_send({"3E00": "7E00", "2701": "6701A1B2C3D4"})
    result = sgw.unlock(send, "7E2", lambda _challenge: None)
    assert not result.ok
    assert result.detail == "no key provided"
