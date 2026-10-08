"""Report building: JSON / CSV / HTML exports of a scan session."""

from __future__ import annotations

import csv
import html
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


_HTML_STYLE = """\
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 16px;
  background: #fff;
  color: #1a1d21;
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 2px; }
h1 .ver { color: #6b7280; font-size: 13px; font-weight: 500; }
h2 { font-size: 15px; margin: 0 0 6px; }
.meta { color: #6b7280; font-size: 12px; margin: 0 0 8px; }
.cards { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
.card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 6px 14px; }
.card .label { color: #6b7280; font-size: 11px; text-transform: uppercase; }
.card .value { font-size: 17px; font-weight: 600; }
section { margin: 22px 0; }
.cols { display: flex; flex-wrap: wrap; gap: 16px; }
.cols .col { flex: 1 1 300px; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #e5e7eb; padding: 5px 8px; text-align: left;
  vertical-align: top; font-size: 13px; }
th { background: #f3f4f6; font-weight: 600; }
tbody tr:nth-child(even) { background: #f9fafb; }
.badge { display: inline-block; border-radius: 999px; padding: 0 8px;
  font-size: 11px; font-weight: 700; }
.badge.pass { background: #dcfce7; color: #166534; }
.badge.fail { background: #fee2e2; color: #991b1b; }
.badge.nrun { background: #f3f4f6; color: #6b7280; }
.badge.mil-on { background: #fee2e2; color: #991b1b; }
.badge.mil-off { background: #dcfce7; color: #166534; }
footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #e5e7eb;
  color: #9ca3af; font-size: 11px; }
@media print {
  body { padding: 0; }
  section, tr { break-inside: avoid; }
}
"""


def report_to_html(report: dict[str, Any]) -> str:
    """Single-file HTML report — inline styles, no scripts, print-friendly."""

    def h(value: object) -> str:
        if value is None or value == "":
            return "—"
        return html.escape(str(value))

    def badge(label: str, kind: str) -> str:
        return f'<span class="badge {kind}">{h(label)}</span>'

    def table(headers: list[str], rows: list[list[str]]) -> str:
        # Cells are pre-escaped HTML fragments; headers are plain text.
        head = "".join(f"<th>{h(name)}</th>" for name in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    def section(title: str, body: str) -> str:
        return f"<section><h2>{title}</h2>{body}</section>"

    def with_unit(value: object, unit: object) -> str:
        if value is None:
            return "—"
        text = html.escape(str(value))
        if unit:
            text += f" {html.escape(str(unit))}"
        return text

    def result_badge(item: dict[str, Any]) -> str:
        label = str(item.get("result") or "NOT RUN")
        return badge(label, {"PASS": "pass", "FAIL": "fail"}.get(label, "nrun"))

    def result_range(item: dict[str, Any]) -> str:
        low, high = item.get("min"), item.get("max")
        if low is None or high is None:
            return "—"
        return f"{h(low)} … {h(high)}"

    app = report["app"]
    adapter = report["adapter"]
    vehicle = report["vehicle"]
    readiness = report.get("readiness")
    dtcs = report.get("dtcs") or {}
    vin = vehicle.get("vin") or ""

    parts: list[str] = []
    parts.append(
        "<header>"
        f'<h1>AutoDiag Pro <span class="ver">v{h(app["version"])}</span></h1>'
        f'<p class="meta">Generated {h(report["generated_at"])}</p>'
        "</header>"
    )

    monitors = (readiness or {}).get("monitors") or []
    supported = [m for m in monitors if m.get("supported")]
    ready_count = sum(1 for m in supported if m.get("complete"))
    if readiness is None:
        mil_text = "—"
    else:
        mil_text = "ON" if readiness.get("mil_on") else "OFF"
    cards = [
        ("DTCs", str(sum(len(entries) for entries in dtcs.values()))),
        ("MIL", mil_text),
        ("Monitors", f"{ready_count}/{len(supported)} ready" if supported else "—"),
        ("Live PIDs", str(len(report.get("live_data") or []))),
    ]
    parts.append(
        '<div class="cards">'
        + "".join(
            f'<div class="card"><div class="label">{label}</div>'
            f'<div class="value">{h(value)}</div></div>'
            for label, value in cards
        )
        + "</div>"
    )

    voltage = adapter.get("voltage")
    adapter_rows = [
        ["Name", h(adapter.get("name"))],
        ["Protocol", h(adapter.get("protocol"))],
        ["Voltage", f"{voltage} V" if voltage is not None else "—"],
    ]
    vehicle_rows = [
        ["VIN", h(vin)],
        ["OBD standard", h(vehicle.get("obd_standard"))],
        ["Fuel type", h(vehicle.get("fuel_type"))],
        ["Calibration IDs", h(", ".join(vehicle.get("calibration_ids") or []))],
        ["CVN", h(", ".join(vehicle.get("cvn") or []))],
    ]
    parts.append(
        '<section class="cols">'
        f'<div class="col"><h2>Adapter</h2>{table(["Field", "Value"], adapter_rows)}</div>'
        f'<div class="col"><h2>Vehicle</h2>{table(["Field", "Value"], vehicle_rows)}</div>'
        "</section>"
    )

    if readiness:
        mil = badge(
            "MIL ON" if readiness.get("mil_on") else "MIL OFF",
            "mil-on" if readiness.get("mil_on") else "mil-off",
        )
        summary = (
            f"{mil} · {h(readiness.get('dtc_count'))} code(s) reported · "
            + ("all monitors ready" if readiness.get("all_ready") else "monitors incomplete")
        )
        rows = []
        for m in monitors:
            if not m.get("supported"):
                state = badge("not supported", "nrun")
            elif m.get("complete"):
                state = badge("ready", "pass")
            else:
                state = badge("not ready", "fail")
            kind = "continuous" if m.get("continuous") else "non-continuous"
            rows.append([h(m.get("name")), kind, state])
        parts.append(
            section(
                "Readiness",
                f'<p class="meta">{summary}</p>'
                + table(["Monitor", "Type", "State"], rows),
            )
        )

    for source, entries in dtcs.items():
        if not entries:
            continue
        rows = [
            [f"<b>{h(entry.get('code'))}</b>", h(entry.get("description"))]
            for entry in entries
        ]
        parts.append(
            section(f"Trouble codes — {h(source)}", table(["Code", "Description"], rows))
        )

    freeze = report.get("freeze_frame") or []
    if freeze:
        rows = [
            [
                h(item.get("frame")),
                h(item.get("pid")),
                h(item.get("name")),
                with_unit(item.get("value"), item.get("unit")),
            ]
            for item in freeze
        ]
        parts.append(
            section("Freeze frame", table(["Frame", "PID", "Parameter", "Value"], rows))
        )

    tests = report.get("mode06") or []
    if tests:
        rows = [
            [
                h(item.get("monitor")),
                h(item.get("test")),
                with_unit(item.get("value"), item.get("unit")),
                result_range(item),
                result_badge(item),
            ]
            for item in tests
        ]
        parts.append(
            section(
                "Mode $06 test results",
                table(["Monitor", "Test", "Value", "Range", "Result"], rows),
            )
        )

    o2_tests = report.get("mode05") or []
    if o2_tests:
        rows = [
            [
                h(item.get("sensor_name")),
                h(item.get("tid")),
                h(item.get("test")),
                with_unit(item.get("value"), item.get("unit")),
                result_range(item),
                result_badge(item),
            ]
            for item in o2_tests
        ]
        parts.append(
            section(
                "Mode $05 O2 sensor tests",
                table(["Sensor", "TID", "Test", "Value", "Range", "Result"], rows),
            )
        )

    pids = report.get("live_data") or []
    if pids:
        rows = [
            [
                h(item.get("pid")),
                h(item.get("name")),
                with_unit(item.get("value"), item.get("unit")),
            ]
            for item in pids
        ]
        parts.append(section("Live data", table(["PID", "Parameter", "Value"], rows)))

    live_log = report.get("live_log")
    if live_log:
        parts.append(
            section(
                "Live log",
                f'<p class="meta">{h(live_log.get("file"))} — '
                f'{h(live_log.get("rows"))} rows</p>',
            )
        )

    parts.append(f"<footer>Generated by AutoDiag Pro v{h(app['version'])}</footer>")
    title = f"AutoDiag Pro report — {vin}" if vin else "AutoDiag Pro report"
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{h(title)}</title>\n"
        f"<style>\n{_HTML_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        + "\n".join(parts)
        + "\n</main>\n</body>\n</html>\n"
    )


def report_text(report: dict[str, Any], suffix: str) -> str:
    """Serialize ``report`` by path suffix (``.json``, ``.csv`` or ``.html``)."""
    if suffix == ".csv":
        return report_to_csv(report)
    if suffix == ".html":
        return report_to_html(report)
    return report_to_json(report)


def write_report(record: ScanRecord, path: str | Path) -> Path:
    """Serialize to ``path`` (format from suffix: ``.json``, ``.csv`` or ``.html``)."""
    target = Path(path)
    report = build_report(record)
    target.write_text(report_text(report, target.suffix.lower()), encoding="utf-8")
    return target


def _pass_label(passed: bool | None) -> str:
    if passed is None:
        return "NOT RUN"
    return "PASS" if passed else "FAIL"
