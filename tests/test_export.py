"""Scan record + JSON/CSV report export tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.mode05 import parse_tid_values
from autodiag.obd.mode06 import parse_test_results
from autodiag.obd.readiness import parse_monitor_status
from autodiag.services.export import build_report, report_to_csv, report_to_json, write_report
from autodiag.services.record import ScanRecord

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_record() -> ScanRecord:
    record = ScanRecord()
    record.record_event(
        "connected",
        (
            SessionInfo(
                adapter="ELM327 v1.5",
                voltage=12.6,
                protocol="AUTO, ISO 15765-4 (CAN 11/500)",
                protocol_number="A7",
            ),
        ),
    )
    record.record_event("pid_value", (0x0C, 1726.0, 1.0))
    record.record_event("dtcs", ("stored", ["P0301"]))
    record.record_event("monitors", (parse_monitor_status("41 01 86 07 E5 87"),))
    record.record_event(
        "vehicle",
        (
            {
                "vin": "1D4GP00R56B123457",
                "cal_ids": ["ECM1A2.34"],
                "cvns": ["1B2C3D4E"],
                "obd_standard": "EOBD (Europe)",
                "fuel_type": "Diesel",
            },
        ),
    )
    record.record_event("freeze_all", (0, {0x0C: 1726.0}))
    record.record_event("freeze_all", (1, {0x05: 83.0}))  # per-frame merge
    record.record_event("mode06", (parse_test_results("46 01 01 0A 06 60 06 60 06 60"),))
    record.record_event(
        "mode05", (parse_tid_values("45 05 01 12 00 19", 0x05, 0x01),)
    )
    return record


def test_build_report_content():
    report = build_report(make_record(), now=_NOW)

    assert report["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert report["adapter"]["name"] == "ELM327 v1.5"
    assert report["adapter"]["voltage"] == 12.6
    assert report["vehicle"]["vin"] == "1D4GP00R56B123457"
    assert report["vehicle"]["calibration_ids"] == ["ECM1A2.34"]
    assert report["vehicle"]["obd_standard"] == "EOBD (Europe)"
    assert report["vehicle"]["fuel_type"] == "Diesel"

    assert report["readiness"]["mil_on"] is True
    assert report["readiness"]["dtc_count"] == 6
    assert report["readiness"]["all_ready"] is False

    stored = report["dtcs"]["stored"]
    assert stored[0]["code"] == "P0301"
    assert stored[0]["description"] == "Cylinder 1 Misfire Detected"

    assert report["freeze_frame"][0]["name"] == "Engine RPM"
    assert report["freeze_frame"][0]["frame"] == 0
    assert {item["frame"] for item in report["freeze_frame"]} == {0, 1}
    assert report["mode06"][0]["result"] == "PASS"
    assert (
        report["mode06"][0]["test"]
        == "Rich-to-lean sensor threshold voltage (constant)"
    )
    assert report["mode05"][0]["tid"] == "05"
    assert report["mode05"][0]["sensor"] == "01"
    assert report["mode05"][0]["sensor_name"] == "Bank 1 - Sensor 1"
    assert round(report["mode05"][0]["value"], 3) == 0.072
    assert report["mode05"][0]["result"] == "PASS"
    assert report["live_data"][0]["pid"] == "0C"
    assert report["live_data"][0]["value"] == 1726.0


def test_build_report_links_live_log():
    record = make_record()
    assert "live_log" not in build_report(record)

    record.log_file = "log-20260101-120000.csv"
    record.log_rows = 42
    report = build_report(record, now=_NOW)
    assert report["live_log"] == {"file": "log-20260101-120000.csv", "rows": 42}
    assert '"log-20260101-120000.csv"' in report_to_json(report)
    assert "live_log" in report_to_csv(report)


def test_report_json_roundtrip():
    text = report_to_json(build_report(make_record(), now=_NOW))
    data = json.loads(text)
    assert data["app"]["name"] == "AutoDiag Pro"
    assert data["vehicle"]["vin"] == "1D4GP00R56B123457"


def test_report_csv_sections():
    text = report_to_csv(build_report(make_record(), now=_NOW))
    lines = text.splitlines()
    assert lines[0] == "section,key,name,value"
    assert any(line.startswith("dtc.stored,P0301") for line in lines)
    assert any(line.startswith("live_data,0C") for line in lines)
    assert any(line.startswith("readiness,mil_on") for line in lines)
    assert any(line.startswith("mode06,01-01") for line in lines)
    assert any(line.startswith("mode05,01-05,") for line in lines)
    assert any(
        "Rich-to-lean sensor threshold voltage" in line for line in lines
    )
    assert any(line.startswith("freeze_frame,F0:0C") for line in lines)
    assert any(line.startswith("freeze_frame,F1:05") for line in lines)
    assert any(
        line == "vehicle,obd_standard,,EOBD (Europe)" for line in lines
    )
    assert any(line == "vehicle,fuel_type,,Diesel" for line in lines)


def test_write_report_selects_format_by_suffix(tmp_path):
    record = make_record()
    json_path = write_report(record, tmp_path / "scan.json")
    csv_path = write_report(record, tmp_path / "scan.csv")

    assert json.loads(json_path.read_text(encoding="utf-8"))["vehicle"]["vin"]
    assert csv_path.read_text(encoding="utf-8").startswith("section,")


def test_record_keeps_vehicle_data_after_disconnect():
    record = make_record()
    record.record_event("disconnected", ("Adapter unplugged",))
    assert record.session is None
    assert record.vin == "1D4GP00R56B123457"
    assert record.obd_standard == "EOBD (Europe)"
    assert record.fuel_type == "Diesel"
    assert record.updated_at is not None


def test_record_vehicle_tolerates_missing_standard_keys():
    record = ScanRecord()
    record.record_event("vehicle", ({"vin": "1D4GP00R56B123457"},))
    assert record.vin == "1D4GP00R56B123457"
    assert record.obd_standard is None
    assert record.fuel_type is None


def test_record_ignores_unrelated_events():
    record = ScanRecord()
    record.record_event("status", ("hello",))
    record.record_event("error", ("boom",))
    assert record.updated_at is None
    assert record.session is None
