"""Bundled DTC dictionary structure and coverage tests."""

import json
import re

from autodiag.data import read_text
from autodiag.obd import dictionary

CODE_RE = re.compile(r"[PCBU][0-9A-F]{4}$")

WELL_KNOWN = (
    "P0171 P0300 P0301 P0401 P0420 P0455 P0500 P0560 P0600 P0700 P1000 P0299"
    " P0129 P2002 P2015 P2455 P2463 P2563 P3410"
    " B0001 B0010 B0014 B0100"
    " C0035 C0040 C0050 C0161 C0201"
    " U0100 U0101 U0121 U0140 U0401 U0607 U1000 U3000"
).split()


def test_source_json_has_no_duplicate_keys():
    pairs = json.loads(read_text("dtc_dictionary.json"), object_pairs_hook=lambda p: p)
    codes = [k for k, _ in pairs]
    assert len(codes) == len(set(codes))


def test_all_keys_are_wellformed_codes():
    for code in dictionary.load_dictionary():
        assert CODE_RE.match(code), code


def test_descriptions_are_clean_text():
    for code, desc in dictionary.load_dictionary().items():
        assert desc and desc == desc.strip(), code
        assert "  " not in desc, code
        assert not any(ord(ch) < 32 for ch in desc), code


def test_dictionary_size_is_pinned():
    assert len(dictionary.load_dictionary()) == 10_497


def test_well_known_codes_are_covered():
    d = dictionary.load_dictionary()
    for code in WELL_KNOWN:
        assert code in d, code


def test_gap_filled_codes_have_descriptions():
    # gap fill (v0.15.0): OBDex CC0 titles
    assert dictionary.describe("B0014") == "Driver Knee Airbag Deployment Control"
    assert dictionary.describe("C0050") == "Right Rear Wheel Speed Sensor Circuit Malfunction"
    assert dictionary.describe("C0161") == "ABS/TCS Brake Switch Circuit"
    assert dictionary.describe("C0201") == "Brake Fluid Level Switch Circuit"
    assert dictionary.describe("P0FFF") == "Reserved Powertrain Fault"
    # gap fill: Wal33D MIT-only body/chassis additions
    assert dictionary.describe("B1318") == "Battery Voltage Low"
    assert dictionary.describe("C1200") == "ABS Inlet Valve Coil LF Circuit Short To Battery"
