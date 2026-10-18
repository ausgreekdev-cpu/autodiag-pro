"""Ford SGW seed-key algorithm tests."""

from __future__ import annotations

import pytest

from autodiag.services.sgw_keys import (
    compute_key,
    ford_hmac_key,
    ford_legacy_key,
)

# -- Algorithm 0: LFSR -----------------------------------------------------------


def test_legacy_key_basic():
    key = ford_legacy_key(b"\x12\x34\x56", b"\x01\x02\x03\x04\x05")
    assert len(key) == 3
    assert key == bytes.fromhex("0ef7c5")


def test_legacy_key_wrong_lengths():
    with pytest.raises(ValueError, match="3-byte challenge"):
        ford_legacy_key(b"\x12\x34", b"\x01\x02\x03\x04\x05")
    with pytest.raises(ValueError, match="3-byte challenge"):
        ford_legacy_key(b"\x12\x34\x56", b"\x01\x02\x03")


def test_legacy_key_deterministic():
    k1 = ford_legacy_key(b"\x00\x00\x01", b"\x00\x00\x00\x00\x01")
    k2 = ford_legacy_key(b"\x00\x00\x01", b"\x00\x00\x00\x00\x01")
    assert k1 == k2


def test_legacy_key_different_secrets_differ():
    k1 = ford_legacy_key(b"\x12\x34\x56", b"\x01\x02\x03\x04\x05")
    k2 = ford_legacy_key(b"\x12\x34\x56", b"\x01\x02\x03\x04\x06")
    assert k1 != k2


# -- Algorithm 1: HMAC zaCK -------------------------------------------------------


def test_hmac_mode1_basic():
    key = ford_hmac_key(1, b"0" * 16, b"0" * 12)
    assert len(key) == 16
    assert key == bytes.fromhex("66c8b006745f85d262ec19ed38eb833f")


def test_hmac_mode2_basic():
    key = ford_hmac_key(2, b"0" * 16, b"0" * 12)
    assert len(key) == 18
    assert key == bytes.fromhex("b9926d20c8d364e500bd58c4ef62fe3722a5")


def test_hmac_wrong_lengths():
    with pytest.raises(ValueError, match="16-byte seed"):
        ford_hmac_key(1, b"0" * 15, b"0" * 12)
    with pytest.raises(ValueError, match="12-byte"):
        ford_hmac_key(1, b"0" * 16, b"0" * 11)


def test_hmac_bad_mode():
    with pytest.raises(ValueError, match="mode must be"):
        ford_hmac_key(3, b"0" * 16, b"0" * 12)


def test_hmac_mode1_vs_mode2_differ():
    k1 = ford_hmac_key(1, b"0" * 16, b"0" * 12)
    k2 = ford_hmac_key(2, b"0" * 16, b"0" * 12)
    assert k1 != k2


# -- compute_key dispatch ---------------------------------------------------------


def test_compute_key_dispatch():
    assert compute_key(0, b"\x12\x34\x56", b"\x01\x02\x03\x04\x05") == (
        ford_legacy_key(b"\x12\x34\x56", b"\x01\x02\x03\x04\x05")
    )
    assert compute_key(1, b"0" * 16, b"0" * 12) == ford_hmac_key(1, b"0" * 16, b"0" * 12)
    assert compute_key(2, b"0" * 16, b"0" * 12) == ford_hmac_key(2, b"0" * 16, b"0" * 12)


def test_compute_key_unknown_algorithm():
    with pytest.raises(ValueError, match="unknown algorithm"):
        compute_key(99, b"\x00\x00\x00", b"\x00\x00\x00\x00\x00")
