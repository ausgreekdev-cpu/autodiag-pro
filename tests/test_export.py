"""Scan record + JSON/CSV report export tests."""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.mode05 import parse_tid_values
from autodiag.obd.mode06 import parse_test_results
from autodiag.obd.readiness import parse_monitor_status
from autodiag.obd.uds import UdsError, parse_response
from autodiag.services.export import (
    build_report,
    report_text,
    report_to_csv,
    report_to_html,
    report_to_json,
    write_report,
)
from autodiag.services.history import describe_report
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
    html_path = write_report(record, tmp_path / "scan.html")

    assert json.loads(json_path.read_text(encoding="utf-8"))["vehicle"]["vin"]
    assert csv_path.read_text(encoding="utf-8").startswith("section,")
    assert html_path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_report_html_contains_sections():
    report = build_report(make_record(), now=_NOW)
    text = report_to_html(report)

    assert text.startswith("<!DOCTYPE html>")
    assert "<style>" in text
    assert "<script" not in text
    assert "1D4GP00R56B123457" in text
    assert "P0301" in text
    assert html.escape(report["dtcs"]["stored"][0]["description"]) in text
    assert html.escape(report["readiness"]["monitors"][0]["name"]) in text
    assert report["mode06"][0]["result"] in text
    assert report["mode05"][0]["result"] in text
    assert "Rich-to-lean sensor threshold voltage" in text
    assert "Engine RPM" in text
    assert "badge pass" in text or "badge fail" in text


def test_report_html_escapes_markup():
    report = {
        "app": {"name": "AutoDiag Pro", "version": "0.17.0"},
        "generated_at": "2026-01-01T00:00:00+00:00",
        "adapter": {"name": "ELM327", "protocol": None, "voltage": 12.0},
        "vehicle": {
            "vin": "<script>alert(1)</script>",
            "calibration_ids": [],
            "cvn": [],
            "obd_standard": "EOBD",
            "fuel_type": "Petrol & gas",
        },
        "readiness": None,
        "dtcs": {"stored": [{"code": "P0301", "description": "<b>boom</b>"}]},
        "freeze_frame": [],
        "mode06": [],
        "mode05": [],
        "live_data": [],
    }
    text = report_to_html(report)

    assert "<script" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "&lt;b&gt;boom&lt;/b&gt;" in text
    assert "Petrol &amp; gas" in text


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


def test_build_report_includes_uds_exchanges():
    record = make_record()
    response = parse_response("62F1903144344750303052353642313233343537")
    error = UdsError(
        "requestOutOfRange (NRC 0x31 for service $22)",
        sid=0x22,
        nrc=0x31,
        raw="7F2231",
    )
    record.record_event("uds", (("22F190", response),))
    record.record_event("uds", (("22F191", error),))

    report = build_report(record, now=_NOW)
    entries = report["uds"]
    assert len(entries) == 2
    assert entries[0]["ok"] is True
    assert entries[0]["request"] == "22F190"
    assert entries[0]["result"] == "1D4GP00R56B123457"
    assert entries[0]["raw"] == "62F1903144344750303052353642313233343537"
    assert entries[0]["time"]
    assert entries[1]["ok"] is False
    assert "requestOutOfRange" in entries[1]["result"]

    html_doc = report_to_html(report)
    assert "UDS requests" in html_doc
    assert "22F190" in html_doc and "1D4GP00R56B123457" in html_doc
    assert "requestOutOfRange" in html_doc
    assert html.escape("7F2231") in html_doc

    csv_text = report_to_csv(report)
    assert "uds,22F190" in csv_text
    assert "OK: 1D4GP00R56B123457" in csv_text
    assert "ERR: requestOutOfRange" in csv_text

    json.loads(report_to_json(report))  # stays JSON-serializable


def test_report_omits_uds_section_when_no_requests():
    report = build_report(make_record(), now=_NOW)
    assert report["uds"] == []
    assert "UDS requests" not in report_to_html(report)


def test_work_order_section_and_csv_rows():
    report = build_report(make_record(), now=_NOW)
    assert report["work_order"] == {}
    assert "Work order" not in report_to_html(report)

    report["work_order"] = {
        "customer": "Sam Rivera",
        "phone": "555-0100",
        "mileage": "184220",
        "job": "Check engine light",
        "notes": "",
    }
    html_doc = report_to_html(report)
    assert "Work order" in html_doc
    assert "Sam Rivera" in html_doc and "Check engine light" in html_doc
    assert "555-0100" in html_doc

    csv_text = report_to_csv(report)
    assert "work_order,customer" in csv_text
    assert "work_order,job" in csv_text
    assert "work_order,notes" not in csv_text  # empty fields omitted


def test_report_text_rejects_pdf_suffix():
    report = build_report(make_record(), now=_NOW)
    with pytest.raises(ValueError) as excinfo:
        report_text(report, ".pdf")
    assert "app" in str(excinfo.value)


# -- repair guidance (M33) ---------------------------------------------------------


def test_build_report_includes_guidance():
    report = build_report(make_record())
    stored = report["dtcs"]["stored"]
    assert stored[0]["guidance"]["severity"] == "high"
    assert stored[0]["guidance"]["source"] == "code"
    assert stored[0]["guidance"]["causes"]


def test_report_advice_hints_from_freeze():
    record = make_record()
    record.record_event("freeze_all", (0, {0x05: 50.0}))
    report = build_report(record)
    assert any("50°C" in hint for hint in report["advice"]["hints"])


def test_html_shows_guidance_and_hints():
    record = make_record()
    record.record_event("freeze_all", (0, {0x0D: 0.0}))
    html = report_to_html(build_report(record))
    assert "Likely causes" in html
    assert "First checks" in html
    assert "When the faults were set" in html
    assert "stationary" in html


def test_csv_guidance_rows():
    csv_text = report_to_csv(build_report(make_record()))
    assert "dtc.stored,P0301.severity,,high" in csv_text
    assert "dtc.stored,P0301.cause[0]," in csv_text
    assert "dtc.stored,P0301.check[0]," in csv_text


def test_describe_report_guidance_line():
    record = make_record()
    record.record_event("dtcs", ("stored", ["P0301", "P9999"]))
    description = describe_report(build_report(record))
    assert "Guidance: 1 of 2 code(s) with advice" in description


# -- active tests in reports (M37) ------------------------------------------------


def test_build_report_includes_active_tests():
    record = make_record()
    record.record_event("mode08", ("0806", "accepted"))
    record.record_event("mode08", ("0801", "rejected (NRC 0x22)"))
    report = build_report(record)
    assert len(report["active_tests"]) == 2
    assert report["active_tests"][0] == {"request": "0806", "outcome": "accepted"}
    assert report["active_tests"][1]["outcome"] == "rejected (NRC 0x22)"


def test_html_shows_active_tests_section():
    record = make_record()
    record.record_event("mode08", ("0806", "accepted"))
    html = report_to_html(build_report(record))
    assert "Active tests (Mode $08)" in html
    assert "0806" in html
    assert "accepted" in html


def test_csv_active_test_rows():
    record = make_record()
    record.record_event("mode08", ("0806", "accepted"))
    csv_text = report_to_csv(build_report(record))
    assert "active_test,[0].request,,0806" in csv_text
    assert "active_test,[0].outcome,,accepted" in csv_text


def test_describe_report_active_tests_line():
    record = make_record()
    record.record_event("mode08", ("0806", "accepted"))
    record.record_event("mode08", ("0801", "rejected (NRC 0x22)"))
    description = describe_report(build_report(record))
    assert "Active tests (Mode $08): 2 (1 accepted)" in description


def test_record_event_mode08():
    from autodiag.services.record import ScanRecord

    record = ScanRecord()
    record.record_event("mode08", (("0806", "accepted"),))
    assert record.active_tests == [("0806", "accepted")]
    record.record_event("mode08", (("0801", "rejected (NRC 0x22)"),))
    assert len(record.active_tests) == 2


def test_record_has_data_with_only_active_tests():
    from autodiag.services.history import record_has_data
    from autodiag.services.record import ScanRecord

    record = ScanRecord()
    assert not record_has_data(record)
    record.record_event("mode08", (("0806", "accepted"),))
    assert record_has_data(record)


# -- one time base, no formulas (review #9, #10) -----------------------------------


def test_uds_rows_share_the_generated_at_time_base():
    record = ScanRecord()
    instant = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    record.uds.append((instant.timestamp(), "22F190", parse_response("62F1903144")))

    report = build_report(record, now=instant)
    entry = report["uds"][0]
    assert entry["time"] == "2026-03-04T05:06:07+00:00"
    assert entry["time"] == report["generated_at"]
    assert "uds,22F190,2026-03-04T05:06:07+00:00" in report_to_csv(report)


def test_uds_time_is_not_local_naive():
    record = ScanRecord()
    instant = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
    record.uds.append((instant.timestamp(), "22F190", parse_response("62F1903144")))
    text = build_report(record, now=instant)["uds"][0]["time"]

    parsed = datetime.fromisoformat(text)
    assert parsed.tzinfo is not None
    assert parsed == instant  # same instant, whatever the machine zone is


def test_naive_now_is_normalised_to_utc():
    report = build_report(make_record(), now=datetime(2026, 1, 1, 0, 0, 0))
    assert report["generated_at"] == "2026-01-01T00:00:00+00:00"


def test_offset_now_is_normalised_to_utc():
    local = datetime(2026, 3, 4, 10, 36, 7, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    report = build_report(make_record(), now=local)
    assert report["generated_at"] == "2026-03-04T05:06:07+00:00"


def test_html_shows_timestamps_in_local_time_with_offset():
    record = make_record()
    record.record_event("uds", (("22F190", parse_response("62F1903144")),))
    report = build_report(record, now=_NOW)
    doc = report_to_html(report)

    for iso in (report["generated_at"], report["uds"][0]["time"]):
        shown = datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        assert shown in doc
        assert iso not in doc  # storage form stays out of the human-facing page


def test_csv_neutralizes_formula_cells():
    report = build_report(make_record(), now=_NOW)
    report["work_order"] = {
        "customer": "=cmd|' /C calc'!A0",
        "phone": "+61400000000",
        "mileage": "-2+3",
        "job": "@SUM(1+1)",
        "notes": "\tHYPERLINK(\"http://example.test\")",
    }
    report["dtcs"]["stored"].append(
        {"code": "P9999", "description": "\n=cmd|' /C calc'!A0", "guidance": None}
    )
    report["uds"] = [
        {
            "time": "2026-01-01T00:00:00+00:00",
            "request": "=1+1",
            "ok": True,
            "result": "-1+1+cmd|' /C calc'!A0",
            "raw": "",
        }
    ]

    rows = list(csv.reader(io.StringIO(report_to_csv(report))))
    cells = {(row[0], row[1]): row[3] for row in rows[1:]}

    assert cells[("work_order", "customer")] == "'=cmd|' /C calc'!A0"
    assert cells[("work_order", "phone")] == "'+61400000000"
    assert cells[("work_order", "mileage")] == "'-2+3"
    assert cells[("work_order", "job")] == "'@SUM(1+1)"
    assert cells[("work_order", "notes")] == "'\tHYPERLINK(\"http://example.test\")"
    assert cells[("dtc.stored", "P9999")] == "'\n=cmd|' /C calc'!A0"
    # Section/key columns are user- and network-authored too.
    assert cells[("uds", "'=1+1")] == "OK: -1+1+cmd|' /C calc'!A0"
    report["active_tests"] = [{"request": "=1+1", "outcome": "-1+1+cmd|' /C calc'!A0"}]
    again = {
        (row[0], row[1]): row[3]
        for row in csv.reader(io.StringIO(report_to_csv(report)))
        if row[0] == "active_test"
    }
    assert again[("active_test", "[0].request")] == "'=1+1"
    assert again[("active_test", "[0].outcome")] == "'-1+1+cmd|' /C calc'!A0"

    # Nothing a spreadsheet could start evaluating survives, in any column.
    for key, value in cells.items():
        assert value == "" or value[0] not in "=+-@\t\r\n", key


def test_csv_keeps_negative_measurements_numeric():
    report = build_report(make_record(), now=_NOW)
    report["live_data"] = [
        {"pid": "0F", "name": "Intake air temperature", "unit": "°C", "value": -12.5}
    ]
    text = report_to_csv(report)
    assert "live_data,0F,Intake air temperature,-12.5 °C" in text
    assert "readiness,mil_on,,True" in text  # ordinary values untouched
