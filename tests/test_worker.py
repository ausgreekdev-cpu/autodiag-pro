"""ObdWorker QThread smoke test — headless QCoreApplication, no hardware."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QCoreApplication

from autodiag.services.worker import ObdWorker
from tests.fakes import scripted_connector


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def _wait_until(app: QCoreApplication, pred, *, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    app.processEvents()
    return pred()


def test_worker_connect_discover_and_poll(app):
    connector, _holder = scripted_connector()
    worker = ObdWorker(connector=connector)
    seen: dict = {"values": []}
    errors: list[str] = []
    worker.connected.connect(lambda info: seen.update(info=info))
    worker.pids_supported.connect(lambda s: seen.update(supported=s))
    worker.pid_value.connect(lambda pid, value, _t: seen["values"].append((pid, value)))
    worker.error.connect(errors.append)

    worker.start()
    # queue the poll config BEFORE connecting: after _establish the engine
    # polls every supported PID on its first idle step, and the fake0100
    # bitmap claims PIDs the script does not answer (a slow CI runner can
    # lose that 50 ms race and record a spurious '?' error)
    worker.set_poll({0x0C}, 0.0)
    worker.connect_to("X")

    assert _wait_until(app, lambda: "info" in seen), "no connected signal"
    assert _wait_until(app, lambda: "supported" in seen), "no pids_supported signal"
    assert 0x0C in seen["supported"]

    assert _wait_until(app, lambda: len(seen["values"]) >= 2), "no pid_value signals"
    assert all(pid == 0x0C for pid, _v in seen["values"])
    assert seen["values"][0][1] == pytest.approx(1726.0)

    worker.shutdown()
    assert not worker.isRunning()
    assert errors == []


def test_worker_shutdown_without_connect(app):
    worker = ObdWorker()
    worker.start()
    worker.shutdown()
    assert not worker.isRunning()


def test_worker_freeze_all_signal_carries_frame(app):
    worker = ObdWorker()
    seen: list = []
    worker.freeze_all.connect(lambda frame, values: seen.append((frame, values)))
    worker.freeze_all.emit(1, {0x0C: 1726.0})
    assert seen == [(1, {0x0C: 1726.0})]


def test_worker_read_freeze_all_submits_frame(app):
    worker = ObdWorker()
    worker.read_freeze_all(2)
    assert worker.engine._jobs.get_nowait() == ("read_freeze_all", 2)
    worker.read_freeze_all()
    assert worker.engine._jobs.get_nowait() == ("read_freeze_all", 0)


def test_worker_request_pid_round_trip(app):
    connector, _holder = scripted_connector()
    worker = ObdWorker(connector=connector)
    seen: dict = {"supported": None, "response": None, "values": []}
    errors: list[str] = []
    worker.pids_supported.connect(lambda s: seen.update(supported=s))
    worker.pid_response.connect(lambda pid, text: seen.update(response=(pid, text)))
    worker.pid_value.connect(lambda pid, value, _t: seen["values"].append((pid, value)))
    worker.error.connect(errors.append)

    worker.start()
    worker.set_poll({0x0C}, 0.0)  # narrow before connect (see test above)
    worker.connect_to("X")
    assert _wait_until(app, lambda: seen["supported"] is not None), "no pids_supported"

    worker.request_pid(0x0D)
    assert _wait_until(app, lambda: seen["response"] is not None), "no pid_response"
    pid, text = seen["response"]
    assert pid == 0x0D
    assert "41 0D" in text
    assert _wait_until(app, lambda: any(p == 0x0D for p, _v in seen["values"]))

    worker.shutdown()
    assert not worker.isRunning()
    assert errors == []
