"""Mode $01 PID decoding tests (SAE J1979 formulas, spec fixtures)."""

import pytest

from autodiag.obd import framing, pids


def test_decode_rpm():
    # 0x1AF8 = 6904 → /4 = 1726 rpm
    assert pids.decode_pid(0x0C, bytes.fromhex("1AF8")) == pytest.approx(1726)


def test_decode_speed_coolant_load():
    assert pids.decode_pid(0x0D, bytes.fromhex("3C")) == 60
    assert pids.decode_pid(0x05, bytes.fromhex("7B")) == 83  # 123 - 40
    assert pids.decode_pid(0x04, bytes.fromhex("7F")) == pytest.approx(49.8, abs=0.1)


def test_decode_fuel_trims():
    assert pids.decode_pid(0x06, bytes.fromhex("80")) == pytest.approx(0.0, abs=0.01)
    assert pids.decode_pid(0x06, bytes.fromhex("90")) == pytest.approx(12.5, abs=0.01)
    assert pids.decode_pid(0x07, bytes.fromhex("40")) == pytest.approx(-50.0, abs=0.01)


def test_decode_maf_throttle_voltage_o2():
    assert pids.decode_pid(0x10, bytes.fromhex("01F4")) == pytest.approx(5.0)
    assert pids.decode_pid(0x11, bytes.fromhex("FF")) == pytest.approx(100.0)
    assert pids.decode_pid(0x42, bytes.fromhex("3039")) == pytest.approx(12.345)
    assert pids.decode_pid(0x14, bytes.fromhex("9C80")) == pytest.approx(0.78)


def test_decode_unknown_and_truncated():
    assert pids.decode_pid(0xEE, b"\x01") is None
    assert pids.decode_pid(0x0C, bytes.fromhex("1A")) is None  # RPM needs 2 bytes


def test_parse_pid_value_from_response_text():
    assert pids.parse_pid_value("41 0C 1A F8", 0x0C) == pytest.approx(1726)
    assert pids.parse_pid_value("SEARCHING...\n4100BE3E", 0x0C) is None
    assert pids.parse_pid_value("41 0D 3C", 0x0C) is None


def test_parse_supported_pids_first_block():
    supported, nxt = pids.parse_supported_pids("4100BE3EA813")
    assert 0x01 in supported  # A = 1011 1110 → PID 01 supported
    assert 0x02 not in supported  # bit 6 clear
    assert 0x0C in supported  # RPM (byte B, bit 4 set)
    assert nxt is True  # PID 20 bit set → next block available
    assert 0x20 in supported


def test_parse_supported_pids_empty():
    assert pids.parse_supported_pids("") == (set(), False)


def test_registry_entries_are_sane():
    assert pids.PID_REGISTRY[0x0C].unit == "rpm"
    assert pids.PID_REGISTRY[0x05].unit == "°C"
    for definition in pids.PID_REGISTRY.values():
        assert 1 <= definition.data_bytes <= 13
        assert definition.name


def test_supported_mask_helper_direct():
    supported, nxt = framing.parse_supported_mask("4600BE3EA813", "4600", 0x00)
    assert 0x01 in supported
    assert nxt is True


def test_o2_pids_are_two_data_bytes():
    for pid in range(0x14, 0x1C):
        assert pids.PID_REGISTRY[pid].data_bytes == 2


def test_stft_companion_definitions():
    definition = pids.PID_REGISTRY[0x114]
    assert definition.name == "O2 sensor B1S1 STFT"
    assert definition.unit == "%"
    assert definition.decimals == 1
    assert pids.request_pid(0x114) == 0x14
    assert pids.request_pid(0x1B) == 0x1B
    assert pids.request_pid(0x14) == 0x14
    assert pids.request_pid(0x0C) == 0x0C
    assert {0x114 + i for i in range(8)} <= pids.PID_REGISTRY.keys()


def test_parse_pid_values_emits_base_and_stft():
    values = pids.parse_pid_values("41 14 9C 80", 0x14)
    assert values[0x14] == pytest.approx(0.78)
    assert values[0x114] == pytest.approx(0.0, abs=0.01)  # 0x80 → centered trim

    values = pids.parse_pid_values("41 15 7A 90", 0x15)
    assert values[0x15] == pytest.approx(0.61)
    assert values[0x115] == pytest.approx(12.5)


def test_parse_pid_values_stft_sentinel_omits_channel():
    # B == 0xFF: sensor not used in trim calculation (J1979)
    values = pids.parse_pid_values("41 14 9C FF", 0x14)
    assert 0x114 not in values
    assert values[0x14] == pytest.approx(0.78)


def test_parse_pid_values_plain_pid_has_no_companions():
    values = pids.parse_pid_values("41 0C 1A F8", 0x0C)
    assert set(values) == {0x0C}
    assert values[0x0C] == pytest.approx(1726)
    assert pids.parse_pid_values("", 0x14) == {}


NEW_PIDS = (
    0x1C,
    0x22,
    0x23,
    *range(0x24, 0x2C),
    0x2C,
    0x2D,
    0x2E,
    0x30,
    0x32,
    0x3E,
    0x3F,
    0x48,
    0x49,
    0x4A,
    0x4B,
    0x4C,
    0x4D,
    0x4E,
    0x51,
    0x52,
    0x53,
    0x54,
    0x55,
    0x56,
    0x57,
    0x58,
    0x59,
    0x5A,
    0x5B,
    0x5D,
    0x61,
    0x63,
    0x7C,
    0x8D,
    0x8E,
    0xA2,
)

REMAINING_PIDS = (
    0x03,
    0x12,
    0x13,
    0x1D,
    0x1E,
    *range(0x34, 0x3C),
    0x4F,
    0x50,
    0x5F,
    0x64,
    0x65,
    0x66,
    0x67,
    0x68,
    0x69,
    0x6B,
    0x6C,
    0x6D,
    0x70,
    0x72,
    0x78,
    0x79,
    0x7D,
    0x7E,
    0x7F,
    0x84,
    0x9A,
    0x9D,
    0x9E,
    0x9F,
    0xA6,
)


def test_full_j1979_registry_coverage():
    assert set(NEW_PIDS) <= set(pids.PID_REGISTRY)
    assert set(REMAINING_PIDS) <= set(pids.PID_REGISTRY)
    assert len(pids.PID_REGISTRY) == 160  # 119 base + 41 companions
    assert len(pids._BASE_REGISTRY) == 119
    assert len(pids.COMPANION_PIDS) == 41
    for pid in NEW_PIDS:
        assert pids.PID_REGISTRY[pid].name
    for pid in REMAINING_PIDS:
        assert pids.PID_REGISTRY[pid].name


def test_rail_pressure_decodes():
    assert pids.decode_pid(0x22, bytes.fromhex("03E8")) == pytest.approx(79.0)
    assert pids.decode_pid(0x23, bytes.fromhex("03E8")) == pytest.approx(10000.0)


def test_wideband_o2_lambda_and_voltage():
    # 0x24: λ = (256A+B)/32768; volts = (256C+D)*8/65536
    assert pids.decode_pid(0x24, bytes.fromhex("40002000")) == pytest.approx(0.5)
    volts = pids.PID_REGISTRY[0x124].scale
    assert volts(bytes.fromhex("40002000")) == pytest.approx(1.0)


def test_evaporative_pressure_signed_decodes():
    assert pids.decode_pid(0x32, bytes.fromhex("FFF4")) == pytest.approx(-3.0)
    assert pids.decode_pid(0x54, bytes.fromhex("0006")) == pytest.approx(6.0)
    assert pids.decode_pid(0x53, bytes.fromhex("0FA0")) == pytest.approx(20.0)


def test_timing_and_fuel_rate_decodes():
    assert pids.decode_pid(0x5D, bytes.fromhex("6400")) == pytest.approx(-10.0)
    assert pids.decode_pid(0xA2, bytes.fromhex("0400")) == pytest.approx(32.0)


def test_temperatures_and_torque_style_decodes():
    assert pids.decode_pid(0x7C, bytes.fromhex("0FA0")) == pytest.approx(360.0)
    assert pids.decode_pid(0x61, bytes.fromhex("7D")) == pytest.approx(0.0)
    assert pids.decode_pid(0x8E, bytes.fromhex("8C")) == pytest.approx(15.0)


def test_catalyst_bank_naming():
    assert pids.PID_REGISTRY[0x3D].name == "Catalyst temperature B2S1"
    assert pids.PID_REGISTRY[0x3E].name == "Catalyst temperature B1S2"


def test_obd_standard_and_fuel_type_enums():
    assert pids.obd_standard_name(6) == "EOBD (Europe)"
    assert pids.obd_standard_name(7) == "EOBD and OBD-II"
    assert pids.obd_standard_name(34) == "OBD, OBD-II, and HD OBD"
    assert pids.obd_standard_name(99) == "OBD standard 99"
    assert pids.fuel_type_name(4) == "Diesel"
    assert pids.fuel_type_name(23) == "Bifuel (Diesel)"
    assert pids.fuel_type_name(40) == "Fuel type 40"
    assert pids.decode_pid(0x1C, bytes.fromhex("06")) == 6
    assert pids.decode_pid(0x51, bytes.fromhex("04")) == 4


def test_secondary_trim_companions():
    assert pids.request_pid(0x155) == 0x55
    assert pids.request_pid(0x158) == 0x58
    values = pids.parse_pid_values("41 55 80 C0", 0x55)
    assert values[0x55] == pytest.approx(0.0, abs=0.01)
    assert values[0x155] == pytest.approx(50.0)  # 0xC0/1.28 - 100


def test_parse_pid_values_wideband_pair():
    values = pids.parse_pid_values("41 24 40 00 20 00", 0x24)
    assert values[0x24] == pytest.approx(0.5)
    assert values[0x124] == pytest.approx(1.0)
    # FF in the λ low byte must not drop the companion (sentinel is STFT-only)
    values = pids.parse_pid_values("41 24 40 FF 20 00", 0x24)
    assert 0x124 in values
    assert values[0x124] == pytest.approx(1.0)


def test_status_pids_decode_raw():
    assert pids.decode_pid(0x03, bytes.fromhex("0200")) == 2
    assert pids.decode_pid(0x12, bytes.fromhex("02")) == 2
    assert pids.decode_pid(0x13, bytes.fromhex("F0")) == 240
    assert pids.decode_pid(0x1D, bytes.fromhex("05")) == 5
    assert pids.decode_pid(0x1E, bytes.fromhex("01")) == 1
    assert pids.decode_pid(0x5F, bytes.fromhex("0B")) == 11
    assert pids.decode_pid(0x65, bytes.fromhex("800F")) == 32783
    assert pids.decode_pid(0x7D, bytes.fromhex("01")) == 1
    assert pids.decode_pid(0x7E, bytes.fromhex("00")) == 0


def test_wideband_o2_lambda_and_current_companion():
    assert pids.decode_pid(0x34, bytes.fromhex("40008180")) == pytest.approx(0.5)
    values = pids.parse_pid_values("41 34 40 00 81 80", 0x34)
    assert values[0x34] == pytest.approx(0.5)
    assert values[0x134] == pytest.approx(1.5)
    assert pids.request_pid(0x134) == 0x34


def test_max_value_pids():
    assert pids.decode_pid(0x4F, bytes.fromhex("A5")) == 165
    assert pids.decode_pid(0x50, bytes.fromhex("19")) == 250


def test_torque_idle_decodes():
    assert pids.decode_pid(0x64, bytes.fromhex("7D")) == 0
    assert pids.decode_pid(0x64, bytes.fromhex("8C")) == 15


def test_multi_sensor_pids_first_channel():
    assert pids.decode_pid(0x66, bytes.fromhex("8104000000")) == pytest.approx(32.0)
    assert pids.decode_pid(0x67, bytes.fromhex("815000")) == 40
    assert pids.decode_pid(0x68, bytes.fromhex("816400")) == 60
    assert pids.decode_pid(0x69, bytes.fromhex("80FF0000000000")) == pytest.approx(100.0)
    assert pids.decode_pid(0x6B, bytes.fromhex("815A000000")) == 50
    assert pids.decode_pid(0x6C, bytes.fromhex("80C8000000")) == pytest.approx(78.43, abs=0.01)
    assert pids.decode_pid(0x6D, bytes.fromhex("8103E80000000000000000")) == 10000
    assert pids.decode_pid(0x70, bytes.fromhex("81040000000000000000")) == pytest.approx(32.0)
    assert pids.decode_pid(0x72, bytes.fromhex("80FF000000")) == pytest.approx(100.0)


def test_second_channel_companions():
    values = pids.parse_pid_values("41 66 81 04 00 08 00", 0x66)
    assert values[0x66] == pytest.approx(32.0)
    assert values[0x166] == pytest.approx(64.0)
    values = pids.parse_pid_values("41 67 81 50 64", 0x67)
    assert values[0x67] == 40
    assert values[0x167] == 60
    values = pids.parse_pid_values("41 69 80 C8 64 00 00 00 00", 0x69)
    assert values[0x69] == pytest.approx(78.43, abs=0.01)
    assert values[0x169] == pytest.approx(39.22, abs=0.01)
    values = pids.parse_pid_values("41 6D 81 03 E8 07 D0 00 28 00 00 00 00", 0x6D)
    assert values[0x6D] == 10000
    assert values[0x16D] == 20000
    values = pids.parse_pid_values("41 70 81 04 00 08 00 00 00 00 00", 0x70)
    assert values[0x70] == pytest.approx(32.0)
    assert values[0x170] == pytest.approx(64.0)
    values = pids.parse_pid_values("41 03 01 04", 0x03)
    assert values[0x03] == 1
    assert values[0x103] == 4


def test_extended_temps_runtime_and_idle_time():
    assert pids.decode_pid(0x78, bytes.fromhex("810FA000000000000000")) == pytest.approx(360.0)
    assert pids.decode_pid(0x79, bytes.fromhex("81000000000000000000")) == -40
    assert pids.decode_pid(0x84, bytes.fromhex("50")) == 40
    values = pids.parse_pid_values(
        "41 7F 80 00 00 00 10 00 00 00 20 00 00 00 30", 0x7F
    )
    assert values[0x7F] == 16
    assert values[0x17F] == 32


def test_fuel_rates_hybrid_battery_and_odometer():
    values = pids.parse_pid_values("41 9D 0F A0 03 E8", 0x9D)
    assert values[0x9D] == 80
    assert values[0x19D] == 20
    assert pids.decode_pid(0x9E, bytes.fromhex("03E8")) == 200
    values = pids.parse_pid_values("41 9A C0 00 80 00 C0 00", 0x9A)
    assert values[0x9A] == pytest.approx(512.0)
    assert values[0x19A] == pytest.approx(-1638.4)
    assert pids.decode_pid(0xA6, bytes.fromhex("000186A0")) == 10000


def test_fuel_system_use_percent_companions():
    values = pids.parse_pid_values("41 9F 80 FF 80 00 00 00 00 00 00", 0x9F)
    assert values[0x9F] == pytest.approx(100.0)
    assert values[0x19F] == pytest.approx(50.2, abs=0.01)


def test_truncated_new_pids_return_none():
    for pid in (0x34, 0x66, 0x69, 0x78, 0x7F, 0x9A, 0x9F, 0xA6):
        assert pids.decode_pid(pid, b"\x01") is None
