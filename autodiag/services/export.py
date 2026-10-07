"""Report building: JSON / CSV exports of a scan session."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autodiag import __version__
from autodiag.obd import dictionary
from autodiag.obd.pids import PID_REGISTRY
from autodiag.services.record import ScanRecord


def build_report(record: ScanRecord, *, now: datetime | None = None) -> dict[str, Any]:
    """Plain-data snapshot of everything known, ready for serialization."""
    session = record.session
    readiness: dict[str, Any] | None = None
    if record.monitors is not None:
        mon = record.monitors
        readiness = {
            "mil_on": mon.mil_on,
            "dtc_count": mon.dtc_count,
            "all_ready": mon.ready,
            "monitors": [
                {
                    "name": m.name,
                    "continuous": m.continuous,
                    "supported": m.supported,
                    "complete": m.complete,
                }
                for m in mon.monitors
            ],
        }

    dtcs = {
        source: [
            {"code": code, "description": dictionary.describe(code)}
            for code in codes
        ]
        for source, codes in record.dtcs.items()
    }

    freeze = []
    for frame, values in sorted(record.freeze.items()):
        for pid, value in sorted(values.items()):
            definition = PID_REGISTRY.get(pid)
            freeze.append(
                {
                    "frame": frame,
                    "pid": f"{pid:02X}",
                    "name": definition.name if definition else f"PID {pid:02X}",
                    "unit": definition.unit if definition else "",
                    "value": value,
                }
            )

    mode06 = []
    for result in record.mode06:
        mode06.append(
            {
                "mid": f"{result.mid:02X}",
                "tid": f"{result.tid:02X}",
                "test": result.test_name,
                "monitor": result.monitor_name,
                "value": result.value,
                "min": result.min_value,
                "max": result.max_value,
                "unit": result.unit,
                "result": _pass_label(result.passed),
            }
        )

    mode05 = []
    for result in record.mode05:
        mode05.append(
            {
                "tid": f"{result.tid:02X}",
                "sensor": f"{result.sensor:02X}",
                "sensor_name": result.sensor_label,
                "test": result.test_name,
                "value": result.value,
                "min": result.min_value,
                "max": result.max_value,
                "unit": result.unit,
                "result": _pass_label(result.passed),
            }
        )

    pids = []
    for pid, (value, _timestamp) in sorted(record.pids.items()):
        definition = PID_REGISTRY.get(pid)
        if definition is None:
            continue
        pids.append(
            {
                "pid": f"{pid:02X}",
                "name": definition.name,
                "unit": definition.unit,
                "value": value,
            }
        )

    generated = now or datetime.now(UTC)
    report: dict[str, Any] = {
        "app": {"name": "AutoDiag Pro", "version": __version__},
        "generated_at": generated.isoformat(timespec="seconds"),
        "adapter": {
            "name": session.adapter if session else None,
            "protocol": session.protocol if session else None,
            "voltage": session.voltage if session else None,
        },
        "vehicle": {
            "vin": record.vin,
            "calibration_ids": record.cal_ids,
            "cvn": record.cvns,
            "obd_standard": record.obd_standard,
            "fuel_type": record.fuel_type,
        },
        "readiness": readiness,
        "dtcs": dtcs,
        "freeze_frame": freeze,
        "mode06": mode06,
        "mode05": mode05,
        "live_data": pids,
    }
    if record.log_file:
        report["live_log"] = {"file": record.log_file, "rows": record.log_rows}
    return report


def report_to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False)


def report_to_csv(report: dict[str, Any]) -> str:
    """Flat ``section,key,name,value`` CSV (one row per fact)."""
    rows: list[tuple[str, str, str, str]] = []

    def add(section: str, key: str, name: str, value: object) -> None:
        rows.append((section, key, name, "" if value is None else str(value)))

    add("meta", "app_version", "", report["app"]["version"])
    add("meta", "generated_at", "", report["generated_at"])
    for key in ("name", "protocol", "voltage"):
        add("adapter", key, "", report["adapter"][key])
    vehicle = report["vehicle"]
    add("vehicle", "vin", "", vehicle["vin"] or "")
    add("vehicle", "obd_standard", "", vehicle["obd_standard"] or "")
    add("vehicle", "fuel_type", "", vehicle["fuel_type"] or "")
    for index, cal in enumerate(vehicle["calibration_ids"]):
        add("vehicle", f"calibration_id[{index}]", "", cal)
    for index, cvn in enumerate(vehicle["cvn"]):
        add("vehicle", f"cvn[{index}]", "", cvn)

    readiness = report["readiness"]
    if readiness:
        add("readiness", "mil_on", "", readiness["mil_on"])
        add("readiness", "dtc_count", "", readiness["dtc_count"])
        add("readiness", "all_ready", "", readiness["all_ready"])
        for mon in readiness["monitors"]:
            state = "not supported" if not mon["supported"] else (
                "ready" if mon["complete"] else "not ready"
            )
            add("readiness", "monitor", mon["name"], state)

    for source, codes in report["dtcs"].items():
        for entry in codes:
            add(f"dtc.{source}", entry["code"], "", entry["description"] or "")

    for item in report["freeze_frame"]:
        add(
            "freeze_frame",
            f"F{item['frame']}:{item['pid']}",
            item["name"],
            f"{item['value']} {item['unit']}",
        )

    for item in report["mode06"]:
        detail = (
            f"{item['test']}: {item['value']} {item['unit']} "
            f"[{item['min']} … {item['max']}] {item['result']}"
        )
        add("mode06", f"{item['mid']}-{item['tid']}", item["monitor"], detail)

    for item in report["mode05"]:
        detail = f"{item['test']}: {item['value']} {item['unit']}".rstrip()
        if item["min"] is not None and item["max"] is not None:
            detail += f" [{item['min']} … {item['max']}]"
        add(
            "mode05",
            f"{item['sensor']}-{item['tid']}",
            item["sensor_name"],
            f"{detail} {item['result']}",
        )

    for item in report["live_data"]:
        add("live_data", item["pid"], item["name"], f"{item['value']} {item['unit']}")

    live_log = report.get("live_log")
    if live_log:
        add("live_log", str(live_log["file"]), "", str(live_log["rows"]))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("section", "key", "name", "value"))
    writer.writerows(rows)
    return buffer.getvalue()


def write_report(record: ScanRecord, path: str | Path) -> Path:
    """Serialize to ``path`` (format from suffix: ``.json`` or ``.csv``)."""
    target = Path(path)
    report = build_report(record)
    suffix = target.suffix.lower()
    if suffix == ".csv":
        target.write_text(report_to_csv(report), encoding="utf-8")
    else:
        target.write_text(report_to_json(report), encoding="utf-8")
    return target


def _pass_label(passed: bool | None) -> str:
    if passed is None:
        return "NOT RUN"
    return "PASS" if passed else "FAIL"
