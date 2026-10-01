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
    worker.connect_to("X")

    assert _wait_until(app, lambda: "info" in seen), "no connected signal"
    assert _wait_until(app, lambda: "supported" in seen), "no pids_supported signal"
    assert 0x0C in seen["supported"]

    worker.set_poll({0x0C}, 0.0)
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
