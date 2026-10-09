"""compare_reports / format_comparison: diffing two session reports."""

from __future__ import annotations

from autodiag.services.compare import (
    compare_reports,
    format_comparison,
    has_changes,
)


def _report(**overrides) -> dict:
    base = {
        "vehicle": {"vin": "1D4GP00R56B123457"},
        "dtcs": {},
        "readiness": None,
        "mode06": [],
        "mode05": [],
        "live_data": [],
    }
    base.update(overrides)
    return base


def _format(diff: dict) -> str:
    return format_comparison(
        diff, baseline_name="session-a.json", current_name="session-b.json"
    )


def test_identical_reports_have_no_differences():
    def build():
        return _report(
            dtcs={"stored": [{"code": "P0301", "description": "Cylinder 1"}]},
            live_data=[
                {"pid": "0C", "name": "Engine RPM", "unit": "rpm", "value": 812.0}
            ],
        )

    diff = compare_reports(build(), build())
    assert has_changes(diff) is False
    assert (
        _format(diff)
        == "Comparing session-a.json → session-b.json\n"
        "No differences found between these sessions."
    )


def test_dtcs_added_and_removed_per_source():
    baseline = _report(
        dtcs={
            "stored": [{"code": "P0301", "description": "Cylinder 1 Misfire Detected"}],
            "pending": [{"code": "P0420", "description": "Cat efficiency low"}],
        }
    )
    current = _report(
        dtcs={
            "stored": [
                {"code": "P0301", "description": "Cylinder 1 Misfire Detected"},
                {"code": "P0420", "description": "Cat efficiency low"},
            ],
            "pending": [],
        }
    )
    diff = compare_reports(baseline, current)
    assert [e["code"] for e in diff["dtcs"]["added"]["stored"]] == ["P0420"]
    assert [e["code"] for e in diff["dtcs"]["removed"]["pending"]] == ["P0420"]
    assert has_changes(diff) is True

    text = _format(diff)
    assert "New trouble codes:" in text
    assert "stored: P0420 — Cat efficiency low" in text
    assert "Resolved trouble codes:" in text
    assert "pending: P0420" in text


def test_readiness_flips():
    baseline = _report(
        readiness={
            "mil_on": True,
            "monitors": [
                {"name": "Catalyst", "supported": True, "complete": False},
                {"name": "O2 sensor", "supported": True, "complete": True},
            ],
        }
    )
    current = _report(
        readiness={
            "mil_on": False,
            "monitors": [
                {"name": "Catalyst", "supported": True, "complete": True},
                {"name": "O2 sensor", "supported": True, "complete": True},
            ],
        }
    )
    diff = compare_reports(baseline, current)
    assert diff["readiness"]["mil"] == (True, False)
    assert diff["readiness"]["monitors"] == [("Catalyst", "not ready", "ready")]

    text = _format(diff)
    assert "MIL: on → off" in text
    assert "Catalyst: not ready → ready" in text
    assert "O2 sensor" not in text  # unchanged monitors stay hidden


def test_readiness_skipped_when_either_side_missing():
    with_ready = _report(
        readiness={"mil_on": False, "monitors": [{"name": "C", "supported": True,
                                                  "complete": True}]}
    )
    diff = compare_reports(with_ready, _report())
    assert diff["readiness"] is None
    assert "Readiness:" not in _format(diff)


def test_mode06_transitions():
    def test(mid, tid, result, name="Sensor test"):
        return {
            "mid": mid,
            "tid": tid,
            "test": name,
            "value": 1,
            "unit": "count",
            "result": result,
        }

    baseline = _report(mode06=[test("01", "01", "PASS"), test("01", "02", "FAIL")])
    current = _report(
        mode06=[test("01", "01", "FAIL"), test("01", "02", "PASS"),
                test("01", "03", "FAIL", "Brand new test")]
    )
    diff = compare_reports(baseline, current)
    assert [t["tid"] for t in diff["mode06"]["now_failing"]] == ["01"]
    assert [t["tid"] for t in diff["mode06"]["recovered"]] == ["02"]
    assert has_changes(diff) is True

    text = _format(diff)
    assert "now FAIL: MID 01 TID 01" in text
    assert "now PASS: MID 01 TID 02" in text
    assert "Brand new test" not in text  # unmatched new MIDs are ignored


def _o2_test(sensor, tid, result, name="Rich-to-lean threshold"):
    return {
        "sensor": sensor,
        "sensor_name": "Bank 1 - Sensor 1",
        "tid": tid,
        "test": name,
        "value": 0.45,
        "min": 0.1,
        "max": 0.9,
        "unit": "V",
        "result": result,
    }


def test_mode05_transitions():
    baseline = _report(mode05=[_o2_test("01", 1, "PASS"), _o2_test("01", 5, "FAIL")])
    current = _report(
        mode05=[
            _o2_test("01", 1, "FAIL"),
            _o2_test("01", 5, "PASS"),
            _o2_test("02", 1, "FAIL", "Brand new sensor test"),
        ]
    )
    diff = compare_reports(baseline, current)
    assert [t["tid"] for t in diff["mode05"]["now_failing"]] == [1]
    assert [t["tid"] for t in diff["mode05"]["recovered"]] == [5]
    assert has_changes(diff) is True

    text = _format(diff)
    assert "Mode $05:" in text
    assert "now FAIL: Bank 1 - Sensor 1 TID 1 — Rich-to-lean threshold" in text
    assert "now PASS: Bank 1 - Sensor 1 TID 5" in text
    assert "Brand new sensor test" not in text  # unmatched sensors ignored


def test_mode05_not_run_results_never_flip():
    baseline = _report(mode05=[_o2_test("01", 1, "NOT RUN")])
    current = _report(
        mode05=[_o2_test("01", 1, "NOT RUN"), _o2_test("01", 5, "PASS")]
    )
    diff = compare_reports(baseline, current)
    assert diff["mode05"] == {"now_failing": [], "recovered": []}
    assert has_changes(diff) is False
    assert "Mode $05:" not in _format(diff)


def _freeze(frame, pid, value, name="Engine RPM", unit="rpm"):
    return {"frame": frame, "pid": pid, "name": name, "unit": unit, "value": value}


def test_freeze_frame_changed_values():
    baseline = _report(freeze_frame=[_freeze(0, "0C", 1726.0)])
    current = _report(freeze_frame=[_freeze(0, "0C", 1801.0)])
    diff = compare_reports(baseline, current)
    (entry,) = diff["freeze_frame"]["changed"]
    assert entry["frame"] == 0
    assert entry["pid"] == "0C"
    assert entry["old"] == 1726.0
    assert entry["new"] == 1801.0
    assert entry["delta"] == 75.0
    assert has_changes(diff) is True

    text = _format(diff)
    assert "Freeze frame:" in text
    assert "Engine RPM (frame 0): 1726 → 1801 rpm (+75)" in text


def test_freeze_frame_unchanged_and_unmatched_hidden():
    baseline = _report(
        freeze_frame=[_freeze(0, "0C", 1726.0), _freeze(0, "05", 83.0, "Fuel level")]
    )
    current = _report(freeze_frame=[_freeze(0, "0C", 1726.0)])
    diff = compare_reports(baseline, current)  # 05 only in baseline → ignored
    assert diff["freeze_frame"] == {"changed": []}
    assert has_changes(diff) is False
    assert "Freeze frame:" not in _format(diff)


def test_freeze_frame_skipped_when_missing():
    with_freeze = _report(freeze_frame=[_freeze(0, "0C", 1726.0)])
    diff = compare_reports(with_freeze, _report())  # session that never read freeze
    assert diff["freeze_frame"] == {"changed": []}
    assert has_changes(diff) is False
    assert "Freeze frame:" not in _format(diff)


def test_live_data_deltas_with_zero_baseline():
    baseline = _report(
        live_data=[
            {"pid": "0C", "name": "Engine RPM", "unit": "rpm", "value": 1726.0},
            {"pid": "0D", "name": "Vehicle speed", "unit": "km/h", "value": 0.0},
        ]
    )
    current = _report(
        live_data=[
            {"pid": "0C", "name": "Engine RPM", "unit": "rpm", "value": 1801.0},
            {"pid": "0D", "name": "Vehicle speed", "unit": "km/h", "value": 60.0},
        ]
    )
    diff = compare_reports(baseline, current)
    rpm, speed = diff["live_data"]
    assert rpm["delta"] == 75.0
    assert rpm["pct"] is not None and abs(rpm["pct"] - 4.345) < 0.01
    assert speed["delta"] == 60.0
    assert speed["pct"] is None  # old == 0 → no percentage

    text = _format(diff)
    assert "Engine RPM: 1726 → 1801 rpm (+75, +4." in text
    assert "Vehicle speed: 0 → 60 km/h (+60)" in text


def test_vin_mismatch_is_a_warning():
    baseline = _report(vehicle={"vin": "1D4GP00R56B123457"})
    current = _report(vehicle={"vin": "5YJSA1E14HF000000"})
    diff = compare_reports(baseline, current)
    assert diff["vin_mismatch"] == "1D4GP00R56B123457 → 5YJSA1E14HF000000"
    assert has_changes(diff) is True
    assert (
        "WARNING: different vehicles "
        "(1D4GP00R56B123457 → 5YJSA1E14HF000000)" in _format(diff)
    )


def test_missing_keys_are_tolerated():
    diff = compare_reports({}, {})  # older/minimal reports
    assert has_changes(diff) is False
    assert "No differences found" in _format(diff)
