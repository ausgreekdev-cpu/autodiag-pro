"""Session history: scan reports auto-saved to disk, browsable and exportable.

Each saved session is one self-contained JSON report (the same document the
manual JSON export produces), named ``session-YYYYMMDD-HHMMSS.json``. The
store never trusts files it did not name: loads validate the file name and
tolerate truncated/foreign JSON instead of crashing the browser.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QStandardPaths

from autodiag.services.export import report_text
from autodiag.services.record import ScanRecord

KEEP = 50  # sessions retained on disk (oldest pruned)
_NAME_RE = re.compile(r"^session-\d{8}-\d{6}(?:-\d+)?\.json$")


def default_directory() -> Path:
    """Per-user data dir (``~/.local/share/…/sessions`` on Linux)."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    return Path(base) / "sessions"


class SessionStore:
    def __init__(self, directory: Path | str | None = None) -> None:
        self._dir = Path(directory) if directory is not None else default_directory()

    @property
    def directory(self) -> Path:
        return self._dir

    # -- write -------------------------------------------------------------------

    def save(self, report: dict[str, Any], *, when: datetime | None = None) -> Path:
        """Persist ``report`` under a timestamped name; prune old sessions."""
        self._dir.mkdir(parents=True, exist_ok=True)
        stamp = (when or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
        path = self._dir / f"session-{stamp}.json"
        counter = 1
        while path.exists():
            path = self._dir / f"session-{stamp}-{counter}.json"
            counter += 1
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._prune()
        return path

    # -- crash recovery ----------------------------------------------------------

    _RECOVERY_NAME = "crash-recovery.json"

    @property
    def _recovery_path(self) -> Path:
        return self._dir / self._RECOVERY_NAME

    def save_crash_recovery(self, report: dict[str, Any]) -> Path:
        """Atomically persist the in-progress session (fixed filename)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._recovery_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(self._recovery_path)  # atomic on POSIX and Windows
        return self._recovery_path

    def load_crash_recovery(self) -> dict[str, Any] | None:
        """Return the last unsaved session report, or ``None``."""
        return self._read(self._recovery_path)

    def clear_crash_recovery(self) -> None:
        """Remove the crash-recovery file (graceful shutdown = clean state)."""
        try:
            self._recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    # -- read --------------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Summaries newest-first (name encodes the save time)."""
        summaries: list[dict[str, Any]] = []
        if not self._dir.is_dir():
            return summaries
        for path in sorted(self._dir.glob("session-*.json")):
            report = self._read(path)
            if report is not None:
                summaries.append(_summarize(path.name, report))
        summaries.sort(key=lambda item: item["name"], reverse=True)
        return summaries

    def load(self, name: str) -> dict[str, Any] | None:
        path = self._safe_path(name)
        return self._read(path) if path is not None else None

    def export(self, name: str, target: Path | str) -> Path | None:
        """Write a stored session to ``target`` (format from the suffix)."""
        report = self.load(name)
        if report is None:
            return None
        target = Path(target)
        target.write_text(report_text(report, target.suffix.lower()), encoding="utf-8")
        return target

    def update(self, name: str, report: dict[str, Any]) -> Path | None:
        """Rewrite a stored session in place (e.g. after editing a work order)."""
        path = self._safe_path(name)
        if path is None or not path.exists():
            return None
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def delete(self, name: str) -> bool:
        path = self._safe_path(name)
        if path is None:
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    # -- helpers --------------------------------------------------------------------

    def _safe_path(self, name: str) -> Path | None:
        if not _NAME_RE.match(name):
            return None  # rejects separators, "..", other extensions
        return self._dir / name

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _prune(self) -> None:
        if not self._dir.is_dir():
            return
        files = sorted(self._dir.glob("session-*.json"), reverse=True)
        for path in files[KEEP:]:
            try:
                path.unlink()
            except OSError:
                pass  # a locked/missing file must not fail the save


def _summarize(name: str, report: dict[str, Any]) -> dict[str, Any]:
    vehicle = report.get("vehicle") or {}
    dtcs = report.get("dtcs") or {}
    return {
        "name": name,
        "generated_at": str(report.get("generated_at") or ""),
        "vin": str(vehicle.get("vin") or ""),
        "adapter": str((report.get("adapter") or {}).get("name") or ""),
        "dtcs": sum(len(codes) for codes in dtcs.values() if isinstance(codes, list)),
        "tests": len(report.get("mode06") or []),
        "pids": len(report.get("live_data") or []),
        "log_rows": int((report.get("live_log") or {}).get("rows") or 0),
        "log_file": str((report.get("live_log") or {}).get("file") or ""),
    }


def describe_report(report: dict[str, Any]) -> str:
    """Human-readable multi-line summary for the history detail pane."""
    lines: list[str] = [f"Generated: {report.get('generated_at') or 'unknown'}"]

    adapter = report.get("adapter") or {}
    if adapter.get("name"):
        detail = f"Adapter: {adapter['name']} · {adapter.get('protocol') or 'protocol?'}"
        if adapter.get("voltage") is not None:
            detail += f" · {adapter['voltage']} V"
        lines.append(detail)

    vehicle = report.get("vehicle") or {}
    if vehicle.get("vin"):
        lines.append(f"VIN: {vehicle['vin']}")
    for cal in vehicle.get("calibration_ids") or []:
        lines.append(f"Cal ID: {cal}")
    details = vehicle.get("details") or {}
    if details.get("make"):
        spec = " ".join(
            part
            for part in (details.get("year"), details.get("make"), details.get("model"))
            if part
        )
        lines.append(f"Vehicle: {spec}")
    recalls = vehicle.get("recalls") or []
    if recalls:
        lines.append(f"Recalls: {len(recalls)} open (NHTSA)")

    work_order = report.get("work_order") or {}
    if any(work_order.values()):
        if work_order.get("customer"):
            lines.append(f"Customer: {work_order['customer']}")
        if work_order.get("job"):
            lines.append(f"Job: {work_order['job']}")

    readiness = report.get("readiness")
    if readiness:
        mil = "ON" if readiness.get("mil_on") else "off"
        ready = "ready" if readiness.get("all_ready") else "not ready"
        lines.append(
            f"MIL: {mil} · DTC count: {readiness.get('dtc_count')} · {ready}"
        )
        for mon in readiness.get("monitors") or []:
            if mon.get("supported"):
                state = "ready" if mon.get("complete") else "not ready"
                lines.append(f"  {mon.get('name')}: {state}")

    any_dtc = False
    for source, codes in (report.get("dtcs") or {}).items():
        for entry in codes:
            any_dtc = True
            line = f"DTC ({source}): {entry.get('code', '?')}"
            if entry.get("description"):
                line += f" — {entry['description']}"
            lines.append(line)
    if any_dtc:
        with_advice = sum(
            1
            for entries in (report.get("dtcs") or {}).values()
            for entry in entries
            if (entry.get("guidance") or {}).get("source") in ("code", "family")
        )
        total = sum(len(entries) for entries in (report.get("dtcs") or {}).values())
        lines.append(f"Guidance: {with_advice} of {total} code(s) with advice")
    else:
        lines.append("No trouble codes recorded.")
    for hint in (report.get("advice") or {}).get("hints") or []:
        lines.append(f"  When set: {hint}")

    tests = report.get("mode06") or []
    if tests:
        failures = [t for t in tests if t.get("result") == "FAIL"]
        lines.append(f"Mode $06: {len(tests)} test(s), {len(failures)} failed")
        for failure in failures:
            lines.append(
                f"  FAIL: {failure.get('monitor')} — {failure.get('test')} "
                f"({failure.get('value')} {failure.get('unit')})"
            )

    active_tests = report.get("active_tests") or []
    if active_tests:
        accepted = sum(1 for t in active_tests if t.get("outcome") == "accepted")
        lines.append(f"Active tests (Mode $08): {len(active_tests)} ({accepted} accepted)")

    live = report.get("live_data") or []
    if live:
        lines.append(f"Live data: {len(live)} parameter(s)")
        for item in live[:12]:
            lines.append(f"  {item.get('name')}: {item.get('value')} {item.get('unit')}")
        if len(live) > 12:
            lines.append(f"  … +{len(live) - 12} more")

    uds_requests = report.get("uds") or []
    if uds_requests:
        failures = sum(1 for item in uds_requests if not item.get("ok"))
        detail = f"UDS: {len(uds_requests)} request(s)"
        if failures:
            detail += f", {failures} negative response(s)"
        lines.append(detail)

    live_log = report.get("live_log")
    if live_log:
        rows = int(live_log.get("rows") or 0)
        lines.append(f"Log: {live_log.get('file')} ({rows:,} rows)")

    return "\n".join(lines)


def record_has_data(record: ScanRecord) -> bool:
    """True when the session holds anything worth auto-saving."""
    return bool(
        record.vin
        or record.dtcs
        or record.monitors
        or record.mode06
        or record.freeze
        or record.pids
        or record.uds
        or record.nhtsa
        or record.active_tests
    )


# Monitor keys by display name (readiness dict stores name, not key).
_MONITOR_KEYS = {
    "Misfire": "misfire",
    "Fuel system": "fuel",
    "Comprehensive components": "ccm",
    "Catalyst": "cat",
    "Heated catalyst": "hcat",
    "Evaporative system": "evap",
    "Secondary air system": "air",
    "A/C refrigerant": "acrf",
    "Oxygen sensor": "o2s",
    "Oxygen sensor heater": "htr",
    "EGR system": "egr",
}


def record_from_report(report: dict[str, Any]) -> ScanRecord:
    """Rebuild a :class:`ScanRecord` from a saved report (inverse of ``build_report``).

    Complex objects (mode $06/$05 results, UDS responses) are reconstructed
    with :class:`types.SimpleNamespace` carrying the attributes
    ``build_report`` reads — enough for a faithful round-trip save.
    """
    from types import SimpleNamespace

    from autodiag.obd.readiness import Monitor, MonitorStatus

    record = ScanRecord()

    vehicle = report.get("vehicle") or {}
    record.vin = vehicle.get("vin")
    record.cal_ids = list(vehicle.get("calibration_ids") or [])
    record.cvns = list(vehicle.get("cvn") or [])
    record.obd_standard = vehicle.get("obd_standard")
    record.fuel_type = vehicle.get("fuel_type")
    record.nhtsa = vehicle.get("details")

    adapter = report.get("adapter") or {}
    if adapter.get("name"):
        record.session = SimpleNamespace(
            adapter=adapter["name"],
            voltage=adapter.get("voltage"),
            protocol=adapter.get("protocol"),
            protocol_number=None,
        )

    record.dtcs = {
        source: [entry.get("code") for entry in entries if entry.get("code")]
        for source, entries in (report.get("dtcs") or {}).items()
    }

    readiness = report.get("readiness")
    if readiness is not None:
        monitors = []
        for entry in readiness.get("monitors") or []:
            name = str(entry.get("name") or "")
            monitors.append(
                Monitor(
                    key=_MONITOR_KEYS.get(name, name.lower().replace(" ", "_")),
                    name=name,
                    supported=bool(entry.get("supported")),
                    complete=bool(entry.get("complete")),
                    continuous=bool(entry.get("continuous")),
                )
            )
        record.monitors = MonitorStatus(
            mil_on=bool(readiness.get("mil_on")),
            dtc_count=int(readiness.get("dtc_count") or 0),
            monitors=tuple(monitors),
        )

    freeze: dict[int, dict[int, float]] = {}
    for item in report.get("freeze_frame") or []:
        try:
            frame = int(item.get("frame") or 0)
            pid = int(str(item.get("pid") or "0"), 16)
            value = float(item.get("value") or 0)
        except (ValueError, TypeError):
            continue
        freeze.setdefault(frame, {})[pid] = value
    record.freeze = freeze

    record.mode06 = [
        SimpleNamespace(
            mid=int(str(item.get("mid") or "0"), 16),
            tid=int(str(item.get("tid") or "0"), 16),
            uasid=0,
            raw_value=0,
            raw_min=0,
            raw_max=0,
            value=float(item.get("value") or 0),
            min_value=float(item.get("min") or 0),
            max_value=float(item.get("max") or 0),
            unit=str(item.get("unit") or ""),
            passed=item.get("result") == "PASS",
            sensor_label=str(item.get("sensor") or ""),
            test_name=str(item.get("test") or ""),
            monitor_name=str(item.get("monitor") or ""),
        )
        for item in report.get("mode06") or []
    ]

    record.mode05 = [
        SimpleNamespace(
            tid=int(str(item.get("tid") or "0"), 16),
            sensor=int(str(item.get("sensor") or "0"), 16),
            raw_value=0,
            raw_min=None,
            raw_max=None,
            value=float(item.get("value") or 0),
            min_value=float(item.get("min") or 0) if item.get("min") is not None else None,
            max_value=float(item.get("max") or 0) if item.get("max") is not None else None,
            unit=str(item.get("unit") or ""),
            via_pid_1d=False,
            name=str(item.get("name") or ""),
            tid_hex=str(item.get("tid") or ""),
            sensor_label=str(item.get("sensor_name") or ""),
            test_name=str(item.get("test") or ""),
            passed=item.get("result") == "PASS",
            result=str(item.get("result") or ""),
        )
        for item in report.get("mode05") or []
    ]

    from datetime import datetime as _dt

    record.uds = [
        (
            _dt.fromisoformat(str(item.get("time") or "1970-01-01T00:00:00")).timestamp(),
            str(item.get("request") or ""),
            SimpleNamespace(
                sid=0x00,
                payload=b"",
                raw=str(item.get("raw") or ""),
            )
            if item.get("ok")
            else SimpleNamespace(
                message=str(item.get("result") or ""),
                raw=str(item.get("raw") or ""),
            ),
        )
        for item in report.get("uds") or []
    ]

    record.active_tests = [
        (str(item.get("request") or ""), str(item.get("outcome") or ""))
        for item in report.get("active_tests") or []
    ]

    record.pids = {
        int(str(item.get("pid") or "0"), 16): (float(item.get("value") or 0), 0.0)
        for item in report.get("live_data") or []
    }

    log = report.get("live_log") or {}
    record.log_file = log.get("file")
    record.log_rows = int(log.get("rows") or 0)

    return record
