"""Diff two session reports (codes, readiness, tests, live values)."""

from __future__ import annotations

from typing import Any


def _monitor_state(entry: dict[str, Any]) -> str:
    if not entry.get("supported"):
        return "not supported"
    return "ready" if entry.get("complete") else "not ready"


def compare_reports(baseline: dict, current: dict) -> dict[str, Any]:
    """Structural diff of two ``build_report()`` dicts (A → B)."""
    vin_a = str((baseline.get("vehicle") or {}).get("vin") or "")
    vin_b = str((current.get("vehicle") or {}).get("vin") or "")
    vin_mismatch = f"{vin_a} → {vin_b}" if vin_a and vin_b and vin_a != vin_b else None

    dtcs_a = baseline.get("dtcs") or {}
    dtcs_b = current.get("dtcs") or {}
    added: dict[str, list[dict]] = {}
    removed: dict[str, list[dict]] = {}
    for source in sorted(set(dtcs_a) | set(dtcs_b)):
        codes_a = {e["code"]: e for e in dtcs_a.get(source) or []}
        codes_b = {e["code"]: e for e in dtcs_b.get(source) or []}
        new_codes = [codes_b[code] for code in codes_b if code not in codes_a]
        gone_codes = [codes_a[code] for code in codes_a if code not in codes_b]
        if new_codes:
            added[source] = new_codes
        if gone_codes:
            removed[source] = gone_codes

    readiness = None
    ready_a, ready_b = baseline.get("readiness"), current.get("readiness")
    if ready_a is not None and ready_b is not None:
        mil = None
        if bool(ready_a.get("mil_on")) != bool(ready_b.get("mil_on")):
            mil = (bool(ready_a.get("mil_on")), bool(ready_b.get("mil_on")))
        monitors_a = {m.get("name"): m for m in ready_a.get("monitors") or []}
        monitors_b = {m.get("name"): m for m in ready_b.get("monitors") or []}
        flips = []
        for name in sorted(set(monitors_a) & set(monitors_b)):
            state_a = _monitor_state(monitors_a[name])
            state_b = _monitor_state(monitors_b[name])
            if state_a != state_b:
                flips.append((str(name), state_a, state_b))
        readiness = {"mil": mil, "monitors": flips}

    tests_a = {(t.get("mid"), t.get("tid")): t for t in baseline.get("mode06") or []}
    tests_b = {(t.get("mid"), t.get("tid")): t for t in current.get("mode06") or []}
    now_failing = []
    recovered = []
    for key in tests_b:  # current-report order; only matched pairs count
        if key not in tests_a:
            continue
        was = tests_a[key].get("result")
        is_now = tests_b[key].get("result")
        if was == "PASS" and is_now == "FAIL":
            now_failing.append(tests_b[key])
        elif was == "FAIL" and is_now == "PASS":
            recovered.append(tests_b[key])

    pids_a = {item.get("pid"): item for item in baseline.get("live_data") or []}
    pids_b = {item.get("pid"): item for item in current.get("live_data") or []}
    deltas = []
    for pid in sorted(set(pids_a) & set(pids_b)):
        old = float(pids_a[pid]["value"])
        new = float(pids_b[pid]["value"])
        delta = new - old
        pct: float | None = (delta / old * 100.0) if old else None
        template = pids_b[pid]
        deltas.append(
            {
                "pid": pid,
                "name": template.get("name") or pids_a[pid].get("name") or pid,
                "unit": template.get("unit") or pids_a[pid].get("unit") or "",
                "old": old,
                "new": new,
                "delta": delta,
                "pct": pct,
            }
        )

    return {
        "vin_mismatch": vin_mismatch,
        "dtcs": {"added": added, "removed": removed},
        "readiness": readiness,
        "mode06": {"now_failing": now_failing, "recovered": recovered},
        "live_data": deltas,
    }


def has_changes(diff: dict[str, Any]) -> bool:
    """True when anything categorical changed (ignores live-value drift)."""
    if diff.get("vin_mismatch"):
        return True
    dtcs = diff.get("dtcs") or {}
    if dtcs.get("added") or dtcs.get("removed"):
        return True
    readiness = diff.get("readiness")
    if readiness and (readiness.get("mil") or readiness.get("monitors")):
        return True
    mode06 = diff.get("mode06") or {}
    return bool(mode06.get("now_failing") or mode06.get("recovered"))


def format_comparison(
    diff: dict[str, Any], *, baseline_name: str, current_name: str
) -> str:
    """Human-readable multi-line rendering for the compare dialog."""
    lines = [f"Comparing {baseline_name} → {current_name}"]
    if diff.get("vin_mismatch"):
        lines.append(f"WARNING: different vehicles ({diff['vin_mismatch']})")

    added = (diff.get("dtcs") or {}).get("added") or {}
    if added:
        lines.append("New trouble codes:")
        for source, codes in added.items():
            for entry in codes:
                lines.append(f"  {source}: {_code_line(entry)}")

    removed = (diff.get("dtcs") or {}).get("removed") or {}
    if removed:
        lines.append("Resolved trouble codes:")
        for source, codes in removed.items():
            for entry in codes:
                lines.append(f"  {source}: {_code_line(entry)}")

    readiness = diff.get("readiness")
    if readiness:
        parts = []
        if readiness.get("mil"):
            was, now = readiness["mil"]
            parts.append(f"MIL: {'on' if was else 'off'} → {'on' if now else 'off'}")
        if parts or readiness.get("monitors"):
            lines.append("Readiness:")
            lines.extend(f"  {part}" for part in parts)
            for name, was, now in readiness.get("monitors") or []:
                lines.append(f"  {name}: {was} → {now}")

    mode06 = diff.get("mode06") or {}
    if mode06.get("now_failing") or mode06.get("recovered"):
        lines.append("Mode $06:")
        for entry in mode06.get("now_failing") or []:
            lines.append(f"  now FAIL: {_test_line(entry)}")
        for entry in mode06.get("recovered") or []:
            lines.append(f"  now PASS: {_test_line(entry)}")

    # zero-drift rows are noise; has_changes ignores live data entirely
    deltas = [item for item in diff.get("live_data") or [] if item["delta"] != 0.0]
    if deltas:
        lines.append("Live data:")
        for item in deltas:
            unit = f" {item['unit']}" if item["unit"] else ""
            change = _signed(item["delta"])
            if item["pct"] is not None:
                change += f", {_signed(item['pct'])}%"
            lines.append(
                f"  {item['name']}: {_num(item['old'])} → {_num(item['new'])}{unit}"
                f" ({change})"
            )

    if len(lines) == 1:
        lines.append("No differences found between these sessions.")
    return "\n".join(lines)


def _code_line(entry: dict[str, Any]) -> str:
    description = entry.get("description")
    code = entry.get("code", "?")
    return f"{code} — {description}" if description else str(code)


def _test_line(entry: dict[str, Any]) -> str:
    return (
        f"MID {entry.get('mid')} TID {entry.get('tid')} — {entry.get('test')} "
        f"({entry.get('value')} {entry.get('unit')})"
    )


def _num(value: float) -> str:
    return f"{value:g}"


def _signed(value: float) -> str:
    return f"{value:+g}"
