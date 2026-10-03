"""Randomized robustness: every decoder must survive garbage input.

Fixed seed → reproducible. For each input a decoder either returns its
documented type or (``hex_to_bytes`` only) raises ``ValueError``; nothing
else may escape. This is a crash/contract fuzz, not a correctness oracle —
exact-value behaviour is covered by the targeted unit tests.
"""

from __future__ import annotations

import random
import string

import pytest

from autodiag.obd import (
    dictionary,
    dtc,
    framing,
    freeze_frame,
    mode06,
    pids,
    readiness,
    vehicle,
)

_SEED = 0x0BDDE5
_ROUNDS = 300
_HEX = "0123456789ABCDEFabcdef"
_PREFIXES = ("43 ", "410C ", "4101 ", "4902 ", "4904 ", "06 01 ", "0: ", "12: ")


def _random_bytes(rng: random.Random) -> bytes:
    return bytes(rng.randrange(256) for _ in range(rng.randrange(0, 16)))


def _random_hex(rng: random.Random) -> str:
    data = _random_bytes(rng).hex()
    # sprinkle the separators ELM327 output contains
    out = []
    for ch in data:
        out.append(ch)
        roll = rng.random()
        if roll < 0.25:
            out.append(" ")
        elif roll < 0.30:
            out.append("\r")
        elif roll < 0.33:
            out.append("\n")
    if rng.random() < 0.3:
        out.append(rng.choice(_PREFIXES))
    if rng.random() < 0.2:
        out.insert(0, f"{rng.randrange(16):X}: ")
    return "".join(out)


def _random_text(rng: random.Random) -> str:
    kind = rng.randrange(5)
    if kind == 0:
        return _random_hex(rng)
    if kind == 1:
        return rng.choice(("", ">", "NO DATA", "SEARCHING...", "?", "\r\n", " \t "))
    if kind == 2:
        length = rng.randrange(1, 40)
        return "".join(rng.choice(string.printable) for _ in range(length))
    if kind == 3:
        # structured: plausible header + random tail
        return rng.choice(_PREFIXES) + _random_hex(rng)
    return "43 " * rng.randrange(1, 40)  # repetitive worst case


def test_fuzz_text_decoders_never_crash():
    rng = random.Random(_SEED)
    for _ in range(_ROUNDS):
        text = _random_text(rng)

        assert isinstance(framing.strip_prompt(text), str)
        assert isinstance(framing.drop_searching(text), str)
        kind, cleaned = framing.classify(text, rng.choice(("", "03", "010C")))
        assert kind is None or isinstance(kind, str)
        assert isinstance(cleaned, str)
        flat = framing.flatten_response(text)
        assert isinstance(flat, str)
        payload = framing.extract_payload(text, "410C")
        assert payload is None or isinstance(payload, str)
        supported, more = framing.parse_supported_mask(text, "4100", 0)
        assert isinstance(supported, set) and isinstance(more, bool)
        try:
            decoded = framing.hex_to_bytes(text)
        except ValueError:
            pass
        else:
            assert isinstance(decoded, bytes)

        for can in (None, True, False):
            codes = dtc.parse_dtcs(text, can=can)
            assert isinstance(codes, list)
            assert all(isinstance(c, str) for c in codes)
        assert dtc.parse_clear_success(text) in (True, False)

        value = pids.parse_pid_value(text, 0x0C)
        assert value is None or isinstance(value, float)
        values = pids.parse_pid_values(text, 0x14)
        assert isinstance(values, dict)
        assert all(isinstance(k, int) and isinstance(v, float) for k, v in values.items())
        supported, more = pids.parse_supported_pids(text, 0x00)
        assert isinstance(supported, set) and isinstance(more, bool)

        status = readiness.parse_monitor_status(text)
        assert status is None or isinstance(status.ready, bool)

        vin = vehicle.parse_vin(text)
        assert vin is None or isinstance(vin, str)
        assert isinstance(vehicle.parse_cal_ids(text), list)
        assert isinstance(vehicle.parse_cvns(text), list)

        frame = freeze_frame.parse_freeze_frame(text, 0x0C, rng.randrange(3))
        assert frame is None or isinstance(frame.value, float)

        results = mode06.parse_test_results(text)
        assert isinstance(results, list)
        for result in results:
            assert isinstance(result.value, float)
            assert isinstance(result.passed, bool | type(None))
        supported, more = mode06.parse_supported_mids(text, 0x00)
        assert isinstance(supported, set) and isinstance(more, bool)


def test_fuzz_binary_decoders_never_crash():
    rng = random.Random(_SEED + 1)
    for _ in range(_ROUNDS):
        data = _random_bytes(rng)

        pid = rng.randrange(0x00, 0x200)
        value = pids.decode_pid(pid, data)
        assert value is None or isinstance(value, float)

        high, low = rng.randrange(256), rng.randrange(256)
        code = dtc.decode_dtc(high, low)
        assert code is None or (isinstance(code, str) and len(code) == 5)

        assert isinstance(framing.parse_supported_mask(
            data.hex(), f"41{rng.randrange(256):02X}", 0
        ), tuple)

        uasid = rng.randrange(0x100)
        raw = rng.randrange(0x10000)
        assert isinstance(mode06.scale_value(uasid, raw), float)
        assert isinstance(mode06.uasid_unit(uasid), str)
        assert isinstance(mode06.mid_name(rng.randrange(-8, 0x400)), str)
        assert isinstance(mode06.tid_name(rng.randrange(-8, 0x400)), str)

        assert isinstance(pids.request_pid(rng.randrange(0x1000)), int)
        assert isinstance(pids.pid_def(pid), pids.PidDef | type(None))


def test_fuzz_dictionary_never_crashes():
    rng = random.Random(_SEED + 2)
    for _ in range(_ROUNDS):
        code = rng.choice("PCBU") + f"{rng.randrange(0x10000):04X}"
        described = dictionary.describe(code)
        assert described is None or isinstance(described, str)


def test_fuzz_large_input_stays_fast():
    # pathological bulk input must not blow up (linear scans only)
    big = "43 01 33 00 00 00 00\r" * 2000
    codes = dtc.parse_dtcs(big)
    assert codes == ["P0133"]
    assert isinstance(framing.flatten_response(big), str)
    assert isinstance(mode06.parse_test_results("46 01 01 " + "0A " * 5000), list)


def test_fuzz_every_decoder_type_contract_smoke():
    # sanity: the curated happy-path input still decodes after fuzz guards
    assert dtc.parse_dtcs("43 03 01 33 02 45 03 67") == ["P0133", "P0245", "P0367"]
    assert pids.parse_pid_value("41 0C 1A F8", 0x0C) == pytest.approx(1726)
