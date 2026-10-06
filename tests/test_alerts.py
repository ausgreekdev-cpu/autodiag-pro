"""Alerts: watchlist transitions + capped breach event log (pure, no Qt)."""

from __future__ import annotations

from autodiag.services.alerts import MAX_EVENTS, AlertLog, Threshold, Watchlist


def _two_sided() -> Watchlist:
    return Watchlist({0x0C: Threshold(0x0C, low=800.0, high=6000.0)})


# -- Watchlist ---------------------------------------------------------------


def test_unwatched_pid_is_ignored():
    watchlist = _two_sided()
    assert watchlist.evaluate(0x05, 5000.0, 1.0) is None
    assert watchlist.breaching == frozenset()


def test_high_side_breach_clear_and_rearm():
    watchlist = _two_sided()
    event = watchlist.evaluate(0x0C, 6500.0, 1.0)
    assert event is not None
    assert (event.kind, event.limit, event.direction) == ("breach", 6000.0, "high")
    assert event.pid == 0x0C and event.value == 6500.0
    assert watchlist.breaching == frozenset({0x0C})

    # still outside → no new event (one per excursion)
    assert watchlist.evaluate(0x0C, 6600.0, 2.0) is None

    # back inside → clear, re-armed
    cleared = watchlist.evaluate(0x0C, 2000.0, 3.0)
    assert cleared is not None and cleared.kind == "clear"
    assert cleared.limit is None and cleared.direction == ""
    assert watchlist.breaching == frozenset()

    again = watchlist.evaluate(0x0C, 7000.0, 4.0)
    assert again is not None and again.kind == "breach"


def test_low_side_breach():
    watchlist = _two_sided()
    event = watchlist.evaluate(0x0C, 750.0, 1.0)
    assert event is not None
    assert (event.kind, event.limit, event.direction) == ("breach", 800.0, "low")


def test_bounds_are_inclusive():
    watchlist = _two_sided()
    assert watchlist.evaluate(0x0C, 800.0, 1.0) is None
    assert watchlist.evaluate(0x0C, 6000.0, 2.0) is None


def test_one_sided_thresholds():
    high_only = Watchlist({0x0D: Threshold(0x0D, high=200.0)})
    assert high_only.evaluate(0x0D, 199.0, 1.0) is None
    assert high_only.evaluate(0x0D, 0.0, 2.0) is None  # no low bound
    event = high_only.evaluate(0x0D, 201.0, 3.0)
    assert event is not None and event.direction == "high"

    low_only = Watchlist({0x05: Threshold(0x05, low=80.0)})
    assert low_only.evaluate(0x05, 80.0, 1.0) is None
    assert low_only.evaluate(0x05, 999.0, 2.0) is None  # no high bound
    event = low_only.evaluate(0x05, 79.0, 3.0)
    assert event is not None and event.direction == "low"


def test_set_get_remove_and_as_dict_round_trip():
    watchlist = Watchlist()
    watchlist.set(Threshold(0x0C, low=800.0, high=6000.0))
    watchlist.set(Threshold(0x05, high=120.0))
    assert watchlist.get(0x0C) == Threshold(0x0C, low=800.0, high=6000.0)
    assert watchlist.thresholds() == [
        Threshold(0x05, high=120.0),
        Threshold(0x0C, low=800.0, high=6000.0),
    ]

    restored = Watchlist(
        {pid: Threshold(pid, low, high) for pid, (low, high) in watchlist.as_dict().items()}
    )
    assert restored.as_dict() == watchlist.as_dict()

    watchlist.remove(0x0C)
    assert watchlist.get(0x0C) is None
    assert watchlist.evaluate(0x0C, 9999.0, 1.0) is None
    watchlist.remove(0x0C)  # idempotent


def test_remove_clears_breach_state():
    watchlist = _two_sided()
    watchlist.evaluate(0x0C, 6500.0, 1.0)
    assert watchlist.breaching == frozenset({0x0C})
    watchlist.remove(0x0C)
    assert watchlist.breaching == frozenset()


# -- AlertLog ----------------------------------------------------------------


def test_alert_log_records_breaches_and_fans_out():
    received: list = []
    log = AlertLog(
        Watchlist({0x0C: Threshold(0x0C, high=6000.0)}), on_event=received.append
    )
    log.evaluate(0x0C, 6500.0, 1.0)
    log.evaluate(0x0C, 6600.0, 2.0)  # same excursion → nothing
    log.evaluate(0x0C, 2000.0, 3.0)  # clear → callback but not stored
    assert [event.kind for event in received] == ["breach", "clear"]
    assert len(log.events) == 1
    assert log.events[0].kind == "breach"


def test_event_cap_keeps_newest_first():
    log = AlertLog(Watchlist({0x0C: Threshold(0x0C, high=6000.0)}))
    for i in range(MAX_EVENTS + 25):
        log.evaluate(0x0C, 5000.0, float(i))  # inside → arm
        log.evaluate(0x0C, 6100.0 + i, float(i))  # outside → breach
    assert len(log.events) == MAX_EVENTS
    assert log.events[0].value == 6100.0 + MAX_EVENTS + 24  # newest first
    assert log.events[-1].value == 6100.0 + 25  # oldest kept


def test_clear_keeps_thresholds():
    watchlist = _two_sided()
    log = AlertLog(watchlist)
    log.evaluate(0x0C, 6500.0, 1.0)
    log.clear()
    assert log.events == []
    assert watchlist.get(0x0C) == Threshold(0x0C, low=800.0, high=6000.0)


def test_export_csv(tmp_path):
    log = AlertLog(Watchlist({0x0C: Threshold(0x0C, high=6000.0)}))
    log.evaluate(0x0C, 6500.0, 1.0)
    log.evaluate(0x0C, 2000.0, 2.0)  # clear → not exported
    path = log.export_csv(tmp_path / "alerts")
    assert path.suffix == ".csv" and path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "time,pid,parameter,value,limit,direction"
    assert len(lines) == 2  # header + the breach
    time_text, pid, parameter, value, limit, direction = lines[1].split(",")
    assert pid == "0C"
    assert parameter == "0C — Engine RPM [rpm]"
    assert value == "6500" and limit == "6000" and direction == "high"
    assert len(time_text) == 8 and time_text.count(":") == 2
