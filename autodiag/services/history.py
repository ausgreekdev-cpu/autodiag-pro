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

from autodiag.services.export import report_to_csv, report_to_json
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
        text = (
            report_to_csv(report)
            if target.suffix.lower() == ".csv"
            else report_to_json(report)
        )
        target.write_text(text, encoding="utf-8")
        return target

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
    if not any_dtc:
        lines.append("No trouble codes recorded.")

    tests = report.get("mode06") or []
    if tests:
        failures = [t for t in tests if t.get("result") == "FAIL"]
        lines.append(f"Mode $06: {len(tests)} test(s), {len(failures)} failed")
        for failure in failures:
            lines.append(
                f"  FAIL: {failure.get('monitor')} — {failure.get('test')} "
                f"({failure.get('value')} {failure.get('unit')})"
            )

    live = report.get("live_data") or []
    if live:
        lines.append(f"Live data: {len(live)} parameter(s)")
        for item in live[:12]:
            lines.append(f"  {item.get('name')}: {item.get('value')} {item.get('unit')}")
        if len(live) > 12:
            lines.append(f"  … +{len(live) - 12} more")

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
    )
