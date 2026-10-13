"""NHTSA service + integration tests — fakes injected, no network."""

from __future__ import annotations

import urllib.error
from typing import Any

from autodiag.services import nhtsa
from autodiag.services.export import build_report, report_to_csv, report_to_html
from autodiag.services.history import describe_report, record_has_data
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.ui.panels.vehicle import VehicleInfoPanel

VIN = "1FMCU9J94LUA12345"


def _decode_payload(**overrides: Any) -> dict:
    payload = {
        "Results": [
            {
                "ErrorCode": "0",
                "ErrorText": "",
                "Make": "Ford",
                "Model": "Escape",
                "ModelYear": "2020",
                "BodyClass": "Sport Utility Vehicle (SUV)/Crossover",
                "EngineCylinders": "4",
                "DisplacementL": "2.5",
                "FuelTypePrimary": "Gasoline",
                "Trim": "SE",
            }
        ]
    }
    payload["Results"][0].update(overrides)
    return payload


def _recalls_payload() -> dict:
    return {
        "Count": 2,
        "Message": "2 results found",
        "results": [
            {
                "NHTSACampaignNumber": "20V314000",
                "Component": "FUEL SYSTEM, GASOLINE",
                "ReportReceivedDate": "2020-05-21",
                "Summary": "Ford is recalling certain Escape vehicles.",
                "Consequence": "A fuel pump failure can cause a stall.",
                "Remedy": "Dealers will replace the fuel pump.",
            },
            {
                "NHTSACampaignNumber": "21E012000",
                "Component": "EQUIPMENT",
                "ReportReceivedDate": "2021-02-01",
                "Summary": "Aftermarket winch.",
                "Consequence": "",
                "Remedy": "Inspect and replace.",
            },
        ],
    }


def _routed_fetch(routes: dict[str, object]):
    def fake(url: str, timeout: float) -> object:
        for fragment, payload in routes.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL: {url}")

    return fake


# -- decode_vin ----------------------------------------------------------------


def test_decode_vin_success():
    seen: list[str] = []

    def fake(url: str, _timeout: float) -> dict:
        seen.append(url)
        return _decode_payload()

    result = nhtsa.decode_vin(VIN.lower(), fetch=fake)
    assert result.ok
    assert result.make == "Ford"
    assert result.model == "Escape"
    assert result.year == "2020"
    assert result.body_class.startswith("Sport Utility")
    assert result.cylinders == "4"
    assert result.displacement_l == "2.5"
    assert result.fuel == "Gasoline"
    assert result.trim == "SE"
    assert result.warning is None
    assert result.engine_text == "4-cyl · 2.5 L · Gasoline"
    assert seen and VIN.upper() in seen[0]  # upper-cased before use
    assert "format=json" in seen[0]


def test_decode_vin_partial_vin_warning():
    payload = _decode_payload(ErrorCode="6,11", ErrorText="Incomplete VIN")
    result = nhtsa.decode_vin(VIN, fetch=lambda _u, _t: payload)
    assert result.ok
    assert result.warning == "Incomplete VIN"


def test_decode_vin_no_data_is_error():
    payload = _decode_payload(Make="")
    result = nhtsa.decode_vin(VIN, fetch=lambda _u, _t: payload)
    assert not result.ok
    assert result.status == "error"
    assert "no data" in (result.message or "")


def test_decode_vin_network_error_is_soft():
    def fake(_url: str, _timeout: float) -> dict:
        raise urllib.error.URLError("dns down")

    result = nhtsa.decode_vin(VIN, fetch=fake)
    assert result.status == "error"
    assert "network error" in (result.message or "")
    assert result.vin == VIN


def test_decode_vin_bad_payload_is_error():
    result = nhtsa.decode_vin(VIN, fetch=lambda _u, _t: {"Nope": []})
    assert result.status == "error"
    assert "unexpected response" in (result.message or "")


def test_decode_vin_empty_vin_is_error():
    result = nhtsa.decode_vin("   ", fetch=lambda _u, _t: {})
    assert result.status == "error"
    assert result.message == "no VIN to decode"


def test_decode_vin_url_encodes_specials():
    seen: list[str] = []
    nhtsa.decode_vin(
        "12/34", fetch=lambda url, _t: (seen.append(url), _decode_payload())[1]
    )
    assert "%2F" in seen[0]
    assert "/" not in seen[0].split("DecodeVinValues/")[1].split("?")[0]


# -- fetch_recalls ---------------------------------------------------------------


def _decoded_ok(**overrides: Any) -> nhtsa.DecodeResult:
    base: dict[str, Any] = {
        "status": "ok",
        "vin": VIN,
        "make": "Ford",
        "model": "Escape",
        "year": "2020",
    }
    base.update(overrides)
    return nhtsa.DecodeResult(**base)


def test_fetch_recalls_success():
    seen: list[str] = []

    def fake(url: str, _timeout: float) -> dict:
        seen.append(url)
        return _recalls_payload()

    result = nhtsa.fetch_recalls(_decoded_ok(), fetch=fake)
    assert result.ok
    assert len(result.recalls) == 2
    first = result.recalls[0]
    assert first.campaign == "20V314000"
    assert first.component == "FUEL SYSTEM, GASOLINE"
    assert first.received == "2020-05-21"
    assert "fuel pump" in first.remedy.lower()
    assert seen and "make=Ford" in seen[0] and "modelYear=2020" in seen[0]
    assert "model=Escape" in seen[0]


def test_fetch_recalls_encodes_query():
    seen: list[str] = []
    vehicle = _decoded_ok(model="F-150 Raptor")
    nhtsa.fetch_recalls(
        vehicle, fetch=lambda url, _t: (seen.append(url), {"results": []})[1]
    )
    assert "model=F-150+Raptor" in seen[0]


def test_fetch_recalls_skipped_without_model():
    vehicle = _decoded_ok(model=None)
    result = nhtsa.fetch_recalls(vehicle, fetch=lambda _u, _t: {})
    assert result.status == "skipped"
    assert result.recalls == ()


def test_fetch_recalls_network_error_is_soft():
    def fake(_url: str, _timeout: float) -> dict:
        raise TimeoutError("timed out")

    result = nhtsa.fetch_recalls(_decoded_ok(), fetch=fake)
    assert result.status == "error"
    assert "timed out" in (result.message or "")


def test_fetch_recalls_bad_payload_is_error():
    result = nhtsa.fetch_recalls(
        _decoded_ok(), fetch=lambda _u, _t: {"results": "nope"}
    )
    assert result.status == "error"
    assert "unexpected response" in (result.message or "")


# -- lookup (decode + recalls) -----------------------------------------------------


def test_lookup_happy_path():
    fake = _routed_fetch(
        {"DecodeVinValues": _decode_payload(), "recallsByVehicle": _recalls_payload()}
    )
    decoded, recalls = nhtsa.lookup(VIN, fetch=fake)
    assert decoded.ok and recalls.ok
    assert len(recalls.recalls) == 2


def test_lookup_decode_failure_skips_recalls():
    fake = _routed_fetch({"DecodeVinValues": {"Results": []}})
    decoded, recalls = nhtsa.lookup(VIN, fetch=fake)
    assert decoded.status == "error"
    assert recalls.status == "skipped"
    assert recalls.message == "decode failed"


# -- record + reports --------------------------------------------------------------


def _record_with_nhtsa() -> ScanRecord:
    record = ScanRecord()
    record.record_event(
        "vehicle",
        ({'vin': VIN, 'cal_ids': ['X1'], 'cvns': ['Y1']},),
    )
    record.record_event(
        "nhtsa",
        (
            {
                "vin": VIN,
                "make": "Ford",
                "model": "Escape",
                "year": "2020",
                "body_class": "SUV",
                "engine_text": "4-cyl · 2.5 L · Gasoline",
                "trim": "SE",
                "warning": None,
                "status": "ok",
                "message": None,
                "recalls": [
                    {
                        "campaign": "20V314000",
                        "component": "FUEL SYSTEM, GASOLINE",
                        "received": "2020-05-21",
                        "summary": "Recall summary.",
                        "consequence": "Stall risk.",
                        "remedy": "Dealers will replace the fuel pump.",
                    }
                ],
                "recall_status": "ok",
                "recall_message": None,
            },
        ),
    )
    return record


def test_record_event_nhtsa_sets_and_clears():
    record = ScanRecord()
    record.record_event("nhtsa", ({"make": "Ford"},))
    assert record.nhtsa == {"make": "Ford"}
    record.record_event("nhtsa", (None,))
    assert record.nhtsa is None


def test_build_report_includes_nhtsa():
    report = build_report(_record_with_nhtsa())
    vehicle = report["vehicle"]
    assert vehicle["details"]["make"] == "Ford"
    assert vehicle["details"]["trim"] == "SE"
    assert len(vehicle["recalls"]) == 1
    assert vehicle["recalls"][0]["campaign"] == "20V314000"


def test_html_shows_details_and_recalls():
    html = report_to_html(build_report(_record_with_nhtsa()))
    assert "Make" in html and "Ford" in html
    assert "Safety recalls (NHTSA)" in html
    assert "20V314000" in html
    assert "Dealers will replace the fuel pump." in html


def test_html_without_nhtsa_has_no_section():
    record = ScanRecord()
    record.record_event("vehicle", ({"vin": VIN},))
    html = report_to_html(build_report(record))
    assert "Safety recalls" not in html
    assert build_report(record)["vehicle"]["details"] is None


def test_csv_rows_for_details_and_recalls():
    csv_text = report_to_csv(build_report(_record_with_nhtsa()))
    assert "vehicle,detail.make,,Ford" in csv_text
    assert "vehicle,detail.year,,2020" in csv_text
    assert "nhtsa.recall[0],campaign,,20V314000" in csv_text
    assert "nhtsa.recall[0],remedy,,Dealers will replace the fuel pump." in csv_text


def test_describe_report_recalls_line():
    description = describe_report(build_report(_record_with_nhtsa()))
    assert "Vehicle: 2020 Ford Escape" in description
    assert "Recalls: 1 open (NHTSA)" in description


def test_record_has_data_with_only_nhtsa():
    record = ScanRecord()
    assert not record_has_data(record)
    record.record_event("nhtsa", ({"make": "Ford"},))
    assert record_has_data(record)


# -- panel (UI flow, no threads, no network) -----------------------------------------


def _ok_payload(**overrides: Any) -> dict:
    payload: dict[str, Any] = {
        "vin": VIN,
        "make": "Ford",
        "model": "Escape",
        "year": "2020",
        "body_class": "SUV",
        "cylinders": "4",
        "displacement_l": "2.5",
        "fuel": "Gasoline",
        "trim": "SE",
        "engine_text": "4-cyl · 2.5 L · Gasoline",
        "warning": None,
        "status": "ok",
        "message": None,
        "recalls": [
            {
                "campaign": "20V314000",
                "component": "FUEL PUMP",
                "received": "2020-05-21",
                "summary": "s",
                "consequence": "c",
                "remedy": "Dealers will replace the fuel pump.",
            }
        ],
        "recall_status": "ok",
        "recall_message": None,
    }
    payload.update(overrides)
    return payload


def test_panel_lookup_flow_fills_widgets_and_record(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})
    assert panel._lookup_btn.isEnabled()

    panel._on_lookup_done({"gen": panel._generation, "payload": _ok_payload()})

    assert panel._detail_values["make"].text() == "Ford"
    assert panel._detail_values["engine_text"].text() == "4-cyl · 2.5 L · Gasoline"
    assert "2 open" not in panel._lookup_status.text()
    assert "1 open recall" in panel._lookup_status.text()
    assert "20V314000" in panel._recalls_edit.toPlainText()
    assert record.nhtsa is not None
    assert record.nhtsa["make"] == "Ford"


def test_panel_vin_change_clears_previous_lookup(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})
    panel._on_lookup_done({"gen": panel._generation, "payload": _ok_payload()})
    assert record.nhtsa is not None

    other = "1G1YY22G965100000"
    panel.on_vehicle({"vin": other, "cal_ids": [], "cvns": []})
    assert record.nhtsa is None
    assert panel._detail_values["make"].text() == "--"
    assert panel._recalls_edit.toPlainText() == ""
    assert panel._lookup_btn.isEnabled()


def test_panel_same_vin_reread_keeps_lookup(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})
    panel._on_lookup_done({"gen": panel._generation, "payload": _ok_payload()})

    panel.on_vehicle({"vin": VIN, "cal_ids": ["X"], "cvns": []})
    assert record.nhtsa is not None
    assert panel._detail_values["make"].text() == "Ford"


def test_panel_stale_result_dropped(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})

    panel._on_lookup_done({"gen": panel._generation + 5, "payload": _ok_payload()})
    assert panel._detail_values["make"].text() == "--"
    assert record.nhtsa is None


def test_panel_error_payload_reports_failure(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})

    payload = _ok_payload(
        status="error", message="network error (dns down)", make=None,
        recalls=[], recall_status="skipped", recall_message="decode failed",
    )
    panel._on_lookup_done({"gen": panel._generation, "payload": payload})
    assert "Lookup failed: network error (dns down)" in panel._lookup_status.text()
    assert panel._detail_values["make"].text() == "--"
    assert record.nhtsa is not None
    assert record.nhtsa["status"] == "error"


def test_panel_disconnect_clears_lookup_state(qapp):
    record = ScanRecord()
    panel = VehicleInfoPanel(ObdWorker(), record=record)
    panel.on_vehicle({"vin": VIN, "cal_ids": [], "cvns": []})
    panel._on_lookup_done({"gen": panel._generation, "payload": _ok_payload()})

    panel._reset()
    assert record.nhtsa is None
    assert panel._detail_values["make"].text() == "--"
    assert not panel._lookup_btn.isEnabled()
    assert panel._lookup_status.text() == ""


def test_panel_lookup_requires_vin(qapp):
    panel = VehicleInfoPanel(ObdWorker(), record=ScanRecord())
    panel.on_vehicle({"vin": None, "cal_ids": [], "cvns": []})
    assert not panel._lookup_btn.isEnabled()
    panel._start_lookup()  # no-op, must not raise or start a thread
    assert panel._lookup is None
