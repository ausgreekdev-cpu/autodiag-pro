"""LiveLog: time-series CSV writer behavior (no Qt, no hardware)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from autodiag.services.live_log import KEEP, LiveLog

# engine RPM definition lives in PID_REGISTRY under 0x0C
_RPM_PID = 0x0C
_RPM_VALUE = 812.0


def _read(path: Path) -> list[list[str]]:
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_no_file_until_armed_and_first_sample(tmp_path):
    log = LiveLog(tmp_path)
    log.set_armed(True)
    assert log.path is None
    log.add(_RPM_PID, _RPM_VALUE, 1.0)
    log.add(_RPM_PID, _RPM_VALUE, 1.25)
    assert log.path is not None
    assert log.row_count == 2
    files = list(tmp_path.glob("log-*.csv"))
    assert len(files) == 1


def test_header_written_once_and_row_format(tmp_path):
    log = LiveLog(tmp_path)
    log.set_armed(True)
    log.add(_RPM_PID, _RPM_VALUE, 10.0)
    log.add(_RPM_PID, 820.5, 10.25)
    log.close()

    rows = _read(log.path)
    assert rows[0] == ["timestamp", "elapsed_s", "pid", "name", "unit", "value"]
    assert len(rows) == 3  # header + 2 samples

    first, second = rows[1], rows[2]
    datetime.fromisoformat(first[0])  # valid ISO wall clock
    assert first[1] == "0.000"
    assert first[2] == "0C"
    assert first[3] == "Engine RPM"
    assert first[4] == "rpm"
    assert first[5] == str(_RPM_VALUE)
    assert second[1] == "0.250"  # elapsed from monotonic timestamps
    assert second[5] == "820.5"


def test_unknown_pid_falls_back(tmp_path):
    log = LiveLog(tmp_path)
    log.set_armed(True)
    log.add(0x99, 1.5, 1.0)
    log.close()
    row = _read(log.path)[1]
    assert row[2] == "99"
    assert row[3] == "PID 99"
    assert row[4] == ""


def test_disarmed_writes_nothing(tmp_path):
    log = LiveLog(tmp_path)
    log.add(_RPM_PID, _RPM_VALUE, 1.0)
    assert log.path is None
    assert log.row_count == 0
    assert list(tmp_path.glob("*.csv")) == []


def test_disarm_freezes_file_and_rearm_starts_new(tmp_path):
    log = LiveLog(tmp_path)
    log.set_armed(True)
    log.add(_RPM_PID, 1.0, 1.0)
    log.close()  # flushes so the file can be read back
    first_path = log.path
    rows_before = _read(first_path)

    log.set_armed(False)
    log.add(_RPM_PID, 2.0, 2.0)
    assert _read(first_path) == rows_before  # frozen
    assert log.path == first_path and log.row_count == 1  # retained for display

    log.set_armed(True)
    assert log.path is None and log.row_count == 0  # fresh state
    log.add(_RPM_PID, 3.0, 3.0)
    assert log.path is not None
    if len(list(tmp_path.glob("log-*.csv"))) > 1:
        assert log.path != first_path  # distinct file (collision suffix if same second)
    log.close()


def test_on_change_reports_progress(tmp_path):
    seen: list[tuple[str, int]] = []
    log = LiveLog(tmp_path, on_change=lambda path, rows: seen.append(
        (path.name if path else "", rows)
    ))
    log.set_armed(True)
    log.add(_RPM_PID, 1.0, 1.0)
    log.add(_RPM_PID, 2.0, 2.0)
    assert [count for _, count in seen] == [1, 2]
    assert seen[0][0].startswith("log-")


def test_write_error_disables_without_raising(tmp_path):
    errors: list[str] = []
    log = LiveLog(tmp_path, on_error=errors.append)
    log.set_armed(True)
    log.add(_RPM_PID, 1.0, 1.0)

    class _Boom:  # csv.writer is a C type — swap in a stub that raises
        @staticmethod
        def writerow(_row):
            raise OSError("disk full")

    log._writer = _Boom()
    log.add(_RPM_PID, 2.0, 2.0)  # must not raise
    assert errors and errors[0].startswith("Live log disabled: ")
    rows_after_fail = log.row_count
    log.add(_RPM_PID, 3.0, 3.0)  # disabled → no-op
    assert log.row_count == rows_after_fail


def test_prune_keeps_newest_files(tmp_path):
    for index in range(KEEP + 5):
        (tmp_path / f"log-20200101-0000{index:02d}.csv").write_text(
            "x\n", encoding="utf-8"
        )
    log = LiveLog(tmp_path)
    log.set_armed(True)
    log.add(_RPM_PID, 1.0, 1.0)
    log.close()
    remaining = list(tmp_path.glob("log-*.csv"))
    assert len(remaining) == KEEP  # 5 pruned, new one created


def test_close_retains_path_and_count(tmp_path):
    log = LiveLog(tmp_path)
    log.set_armed(True)
    log.add(_RPM_PID, 1.0, 1.0)
    path, count = log.path, log.row_count
    log.close()
    assert log.path == path
    assert log.row_count == count
    assert path.exists()
