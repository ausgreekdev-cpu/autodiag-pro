"""Mode $09 vehicle information tests (VIN, cal IDs, CVN)."""

from autodiag.obd import vehicle

# VIN "1D4GP00R56B123457" split across ISO-TP lines with padding
_VIN_LINES = (
    "0: 49 02 01 31 44 34 47 50\n"
    "1: 30 30 52 35 36 42 31 32\n"
    "2: 33 34 35 37 00 00 00 00"
)


def test_parse_vin_multiline():
    assert vehicle.parse_vin(_VIN_LINES) == "1D4GP00R56B123457"


def test_parse_vin_single_line():
    # count byte (01) filtered as non-printable, NULs stripped
    text = "49 02 01 31 44 34 47 50 30 30 52 35 36 42 31 32 33 34 35 37"
    assert vehicle.parse_vin(text) == "1D4GP00R56B123457"


def test_parse_vin_missing_or_garbage():
    assert vehicle.parse_vin("") is None
    assert vehicle.parse_vin("49 02 01 41 42 43") is None  # too short / invalid
    assert vehicle.parse_vin("41 0C 1A F8") is None  # wrong mode


def test_parse_cal_ids():
    # count byte then an ASCII run
    text = "49 04 01 45 43 4D 31 41 32 2E 33 34 00 00"
    ids = vehicle.parse_cal_ids(text)
    assert ids == ["ECM1A2.34"]


def test_parse_cal_ids_multiline():
    text = "0: 49 04 02 45 43 4D 31 41 32\n1: 2E 33 34 00 45 43 4D 32 42 00"
    ids = vehicle.parse_cal_ids(text)
    assert ids == ["ECM1A2.34", "ECM2B"]


def test_parse_cal_ids_empty():
    assert vehicle.parse_cal_ids("") == []


def test_parse_cvn():
    text = "49 06 01 1B 2C 3D 4E"
    assert vehicle.parse_cvns(text) == ["1B2C3D4E"]


def test_parse_cvn_two():
    text = "49 06 02 1B 2C 3D 4E AA BB CC DD"
    assert vehicle.parse_cvns(text) == ["1B2C3D4E", "AABBCCDD"]


def test_parse_cvn_empty():
    assert vehicle.parse_cvns("") == []
