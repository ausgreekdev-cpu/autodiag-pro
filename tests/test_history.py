"""Session history store: save/list/load/export/delete, pruning, tolerance."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from autodiag.obd.elm327 import SessionInfo
from autodiag.services.export import build_report
from autodiag.services.history import (
    KEEP,
    SessionStore,
    default_directory,
    describe_report,
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
