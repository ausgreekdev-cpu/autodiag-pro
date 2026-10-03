"""log_reader: parse LiveLog CSVs back into per-PID series."""

from __future__ import annotations

import pytest

from autodiag.services.log_reader import read_log

_HEADER = "timestamp,elapsed_s,pid,name,unit,value\n"
_ROWS = (
    "2026-10-03T12:00:00.000+00:00,0.000,0C,Engine RPM,rpm,812.0\n"
    "2026-10-03T12:00:00.250+00:00,0.250,0D,Vehicle speed,km/h,44.0\n"
    "2026-10-03T12:00:00.500+00:00,0.500,0C,Engine RPM,rpm,845.5\n"
    "2026-10-03T12:00:00.750+00:00,0.750,0C,Engine RPM,rpm,901.0\n"
)


def test_reads_series_in_first_seen_order(tmp_path):
    path = tmp_path / "log-20261003-120000.csv"
    path.write_text(_HEADER + _ROWS, encoding="utf-8")

    data = read_log(path)
    assert list(data.series) == [0x0C, 0x0D]
    assert data.rows == 4
    assert data.skipped == 0
    assert data.started_at == "2026-10-03T12:00:00.000+00:00"

    rpm = data.series[0x0C]
    assert rpm.name == "Engine RPM"
    assert rpm.unit == "rpm"
    assert rpm.xs == [0.0, 0.5, 0.75]
    assert rpm.ys == [812.0, 845.5, 901.0]

    speed = data.series[0x0D]
    assert speed.name == "Vehicle speed"
    assert speed.ys == [44.0]


def test_skips_malformed_rows(tmp_path):
    path = tmp_path / "log.csv"
    path.write_text(
        _HEADER
        + _ROWS
        + "2026-10-03T12:00:01.000+00:00,oops,0C,Engine RPM,rpm,100\n"
        + "2026-10-03T12:00:01.250+00:00,1.250,0C,Engine RPM,rpm,\n",
        encoding="utf-8",
    )
    data = read_log(path)
    assert data.rows == 4
    assert data.skipped == 2


def test_foreign_csv_raises_value_error(tmp_path):
    path = tmp_path / "other.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        read_log(path)


def test_empty_file_raises_value_error(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty log"):
        read_log(path)


def test_header_only_raises_value_error(tmp_path):
    path = tmp_path / "header.csv"
    path.write_text(_HEADER, encoding="utf-8")
    with pytest.raises(ValueError, match="empty log"):
        read_log(path)


def test_unknown_pid_uses_file_name_and_unit(tmp_path):
    path = tmp_path / "log.csv"
    path.write_text(
        _HEADER + "2026-10-03T12:00:00.000+00:00,0.000,99,Mystery,value,1.5\n",
        encoding="utf-8",
    )
    data = read_log(path)
    series = data.series[0x99]
    assert series.name == "Mystery"
    assert series.unit == "value"
