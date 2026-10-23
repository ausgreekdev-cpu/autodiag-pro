"""Session history store: save/list/load/export/delete, pruning, tolerance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.uds import parse_response
from autodiag.services.export import build_report
from autodiag.services.history import (
    KEEP,
    SessionStore,
    default_directory,
    describe_report,
    record_from_report,
    record_has_data,
)
from autodiag.services.record import ScanRecord
from tests.test_export import make_record


def _report() -> dict:
    return build_report(make_record(), now=datetime(2026, 10, 3, tzinfo=UTC))


def test_default_directory_ends_in_sessions():
    path = default_directory()
    assert path.name == "sessions"
    assert path.is_absolute()


def test_save_list_load_round_trip(tmp_path):
    store = SessionStore(tmp_path)
    saved = store.save(_report(), when=datetime(2026, 10, 3, 12, 30, 45, tzinfo=UTC))

    assert saved.name == "session-20261003-123045.json"
    assert saved.exists()

    summaries = store.list()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["name"] == saved.name
    assert summary["vin"] == "1D4GP00R56B123457"
    assert summary["adapter"] == "ELM327 v1.5"
    assert summary["dtcs"] == 1
    assert summary["tests"] == 1
    assert summary["pids"] == 1

    loaded = store.load(saved.name)
    assert loaded is not None
    assert loaded["vehicle"]["vin"] == "1D4GP00R56B123457"
    assert loaded["dtcs"]["stored"][0]["code"] == "P0301"
    assert loaded == json.loads(saved.read_text(encoding="utf-8"))


def test_save_same_second_gets_collision_suffix(tmp_path):
    store = SessionStore(tmp_path)
    when = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
    first = store.save(_report(), when=when)
    second = store.save(_report(), when=when)
    third = store.save(_report(), when=when)

    assert first.name == "session-20261003-120000.json"
    assert second.name == "session-20261003-120000-1.json"
    assert third.name == "session-20261003-120000-2.json"
    assert len(store.list()) == 3


def test_prune_keeps_newest_fifty(tmp_path):
    store = SessionStore(tmp_path)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for hour in range(KEEP + 5):  # 55 sessions, one per hour
        store.save(_report(), when=start + timedelta(hours=hour))

    summaries = store.list()
    assert len(summaries) == KEEP
    names = [s["name"] for s in summaries]
    # newest first; the five oldest hours were pruned
    assert names[0] == "session-20260103-060000.json"  # hour 54
    assert store.load("session-20260101-000000.json") is None
    assert store.load("session-20260101-040000.json") is None
    assert store.load("session-20260101-050000.json") is not None


def test_list_skips_corrupt_and_foreign_files(tmp_path):
    store = SessionStore(tmp_path)
    (tmp_path / "session-broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "session-list.json").write_text("[1, 2, 3]", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    good = store.save(_report(), when=datetime(2026, 10, 3, tzinfo=UTC))

    summaries = store.list()
    assert [s["name"] for s in summaries] == [good.name]
    assert store.load("session-broken.json") is None
    assert store.load("session-list.json") is None


def test_load_rejects_unsafe_names(tmp_path):
    store = SessionStore(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text('{"generated_at": "x"}', encoding="utf-8")

    assert store.load("../outside.json") is None
    assert store.load("outside.json") is None
    assert store.load("session-20261003-120000.json.txt") is None
    assert store.load("") is None
    assert store.delete("../outside.json") is False
    assert outside.exists()  # traversal attempt left it alone


def test_delete(tmp_path):
    store = SessionStore(tmp_path)
    saved = store.save(_report(), when=datetime(2026, 10, 3, tzinfo=UTC))
    assert store.delete(saved.name) is True
    assert not saved.exists()
    assert store.delete(saved.name) is False  # already gone
    assert store.list() == []


def test_export_csv_and_json(tmp_path):
    store = SessionStore(tmp_path)
    saved = store.save(_report(), when=datetime(2026, 10, 3, tzinfo=UTC))

    csv_path = store.export(saved.name, tmp_path / "out.csv")
    assert csv_path is not None
    csv_text = csv_path.read_text(encoding="utf-8")
    assert csv_text.startswith("section,key,name,value")
    assert "1D4GP00R56B123457" in csv_text
    assert "P0301" in csv_text

    json_path = store.export(saved.name, tmp_path / "out.json")
    assert json_path is not None
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["vehicle"]["vin"] == "1D4GP00R56B123457"

    html_path = store.export(saved.name, tmp_path / "out.html")
    assert html_path is not None
    html_text = html_path.read_text(encoding="utf-8")
    assert html_text.startswith("<!DOCTYPE html>")
    assert "1D4GP00R56B123457" in html_text
    assert "P0301" in html_text

    assert store.export("session-19990101-000000.json", tmp_path / "no.csv") is None


def test_describe_report_highlights(tmp_path):
    text = describe_report(_report())
    assert "VIN: 1D4GP00R56B123457" in text
    assert "Adapter: ELM327 v1.5" in text
    assert "P0301" in text
    assert "Mode $06: 1 test(s)" in text
    assert "Engine RPM: 1726" in text

    empty = describe_report({"generated_at": "2026-10-03T00:00:00+00:00"})
    assert "No trouble codes recorded." in empty
    assert "VIN:" not in empty


def test_summary_and_describe_include_live_log(tmp_path):
    record = make_record()
    record.log_file = "log-20261003-120000.csv"
    record.log_rows = 1234
    report = build_report(record, now=datetime(2026, 10, 3, tzinfo=UTC))

    store = SessionStore(tmp_path)
    store.save(report, when=datetime(2026, 10, 3, tzinfo=UTC))
    assert store.list()[0]["log_rows"] == 1234

    text = describe_report(report)
    assert "Log: log-20261003-120000.csv (1,234 rows)" in text
    assert "Log:" not in describe_report(_report())  # absent → no line


def test_record_has_data_gates_auto_save():
    record = ScanRecord()
    assert record_has_data(record) is False

    record.record_event(
        "connected",
        (  # session info alone is not worth saving
            SessionInfo(
                adapter="ELM327", voltage=12.0, protocol="AUTO", protocol_number="A7"
            ),
        ),
    )
    assert record_has_data(record) is False

    record.record_event("pid_value", (0x0C, 1726.0, 1.0))
    assert record_has_data(record) is True


def test_record_has_data_accepts_uds_only_session():
    record = ScanRecord()
    record.record_event(
        "uds",
        (("22F190", parse_response("62F1903144344750303052353642313233343537")),),
    )
    assert record_has_data(record) is True


def test_describe_report_summarizes_uds():
    report = _report()
    report["uds"] = [
        {"request": "22F190", "ok": True, "result": "1D4GP00R56B123457"},
        {"request": "1902FF", "ok": False, "result": "serviceNotSupported"},
    ]
    text = describe_report(report)
    assert "UDS: 2 request(s)" in text
    assert "1 negative response(s)" in text

    plain = _report()
    assert "UDS:" not in describe_report(plain)


def test_update_rewrites_session_in_place(tmp_path):
    store = SessionStore(tmp_path)
    saved = store.save(_report(), when=datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    report = store.load(saved.name)
    assert report is not None
    report["work_order"] = {"customer": "Sam Rivera", "job": "Misfire diagnosis"}

    updated = store.update(saved.name, report)
    assert updated == saved
    reloaded = store.load(saved.name)
    assert reloaded is not None
    assert reloaded["work_order"]["customer"] == "Sam Rivera"

    assert store.update("session-99990101-000000.json", report) is None
    assert store.update("not-a-session.txt", report) is None


def test_describe_report_shows_work_order():
    report = _report()
    assert report["work_order"] == {}
    assert "Customer:" not in describe_report(report)

    report["work_order"] = {
        "customer": "Sam Rivera",
        "job": "Misfire diagnosis",
        "phone": "",
    }
    text = describe_report(report)
    assert "Customer: Sam Rivera" in text
    assert "Job: Misfire diagnosis" in text


# -- crash recovery (M39) -------------------------------------------------------


def test_crash_recovery_round_trip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    report = _report()
    path = store.save_crash_recovery(report)
    assert path.name == "crash-recovery.json"
    loaded = store.load_crash_recovery()
    assert loaded is not None
    assert loaded["vehicle"]["vin"] == report["vehicle"]["vin"]


def test_crash_recovery_clear(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.save_crash_recovery(_report())
    assert store.load_crash_recovery() is not None
    store.clear_crash_recovery()
    assert store.load_crash_recovery() is None
    store.clear_crash_recovery()  # clearing twice is safe


def test_crash_recovery_load_when_missing(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    assert store.load_crash_recovery() is None


def test_crash_recovery_overwrites_previous(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    report1 = _report()
    report2 = build_report(make_record(), now=datetime(2026, 11, 1, tzinfo=UTC))
    store.save_crash_recovery(report1)
    store.save_crash_recovery(report2)
    loaded = store.load_crash_recovery()
    assert loaded is not None
    assert loaded["generated_at"] == report2["generated_at"]


def test_crash_recovery_not_pruned_by_save(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    store.save_crash_recovery(_report())
    # A normal save must not delete the recovery file
    store.save(_report())
    assert store.load_crash_recovery() is not None


# -- record_from_report (M39) ----------------------------------------------------


def test_record_from_report_round_trip(tmp_path):
    original = make_record()
    report = build_report(original)
    restored = record_from_report(report)

    assert restored.vin == original.vin
    assert restored.cal_ids == original.cal_ids
    assert restored.cvns == original.cvns
    assert restored.obd_standard == original.obd_standard
    assert restored.fuel_type == original.fuel_type
    assert restored.dtcs == original.dtcs
    assert restored.active_tests == original.active_tests
    assert restored.nhtsa == original.nhtsa
    assert restored.log_file == original.log_file
    assert restored.log_rows == original.log_rows


def test_record_from_report_freeze(tmp_path):
    original = make_record()
    original.record_event("freeze_all", (0, {0x05: 83.0, 0x0C: 1726.0}))
    report = build_report(original)
    restored = record_from_report(report)
    assert restored.freeze == original.freeze


def test_record_from_report_monitors(tmp_path):
    original = make_record()
    report = build_report(original)
    restored = record_from_report(report)
    assert restored.monitors is not None
    assert restored.monitors.mil_on == original.monitors.mil_on
    assert len(restored.monitors.monitors) == len(original.monitors.monitors)


def test_record_from_report_pids(tmp_path):
    original = make_record()
    report = build_report(original)
    restored = record_from_report(report)
    assert 0x0C in restored.pids
    assert restored.pids[0x0C][0] == 1726.0


def test_record_from_report_mode06(tmp_path):
    original = make_record()
    report = build_report(original)
    restored = record_from_report(report)
    assert len(restored.mode06) == len(original.mode06)
    if restored.mode06:
        assert restored.mode06[0].mid == original.mode06[0].mid
        assert restored.mode06[0].tid == original.mode06[0].tid


def test_record_from_report_rebuild_report_identical(tmp_path):
    """Round-trip: record → report → record → report produces same report."""
    original = make_record()
    report1 = build_report(original)
    restored = record_from_report(report1)
    report2 = build_report(restored)
    assert report1["vehicle"] == report2["vehicle"]
    assert report1["dtcs"] == report2["dtcs"]
    assert report1["active_tests"] == report2["active_tests"]
    assert report1["freeze_frame"] == report2["freeze_frame"]


def test_record_from_report_handles_empty(tmp_path):
    record = record_from_report({})
    assert record.vin is None
    assert record.dtcs == {}
    assert record.monitors is None
    assert record.active_tests == []
