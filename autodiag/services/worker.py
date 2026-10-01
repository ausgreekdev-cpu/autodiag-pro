"""Qt worker thread: runs :class:`ObdEngine` off the UI thread, exposes signals."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal

from autodiag.services.engine import Connector, ObdEngine


class ObdWorker(QThread):
    """Owns the OBD engine in a background thread; results arrive as signals.

    All methods are safe to call from the UI thread — commands are queued
    and executed serially by the engine loop in :meth:`run`.
    """

    status = Signal(str)  # human-readable progress ("Trying /dev/ttyUSB0 ...")
    error = Signal(str)  # recoverable errors (poll failures, bad responses)
    connected = Signal(object)  # SessionInfo
    disconnected = Signal(str)  # reason
    pids_supported = Signal(object)  # set[int]
    pid_value = Signal(int, float, float)  # pid, value, monotonic timestamp
    dtcs = Signal(str, object)  # source ("stored"/"pending"/"permanent"), list[str]
    cleared = Signal(bool)
    monitors = Signal(object)  # MonitorStatus
    freeze_supported = Signal(object)  # set[int]
    freeze = Signal(object)  # FreezeFrame
    vehicle = Signal(object)  # {"vin", "cal_ids", "cvns"}
    mids_supported = Signal(object)  # set[int]
    mode06 = Signal(object)  # list[TestResult]
    voltage = Signal(float)

    _EVENT_KINDS = (
        "status",
        "error",
        "connected",
        "disconnected",
        "pids_supported",
        "pid_value",
        "dtcs",
        "cleared",
        "monitors",
        "freeze_supported",
        "freeze",
        "vehicle",
        "mids_supported",
        "mode06",
        "voltage",
    )

    def __init__(self, connector: Connector | None = None, parent: Any = None) -> None:
        super().__init__(parent)
        self._engine = ObdEngine(connector=connector, on_event=self._dispatch)

    # -- commands (UI thread) -------------------------------------------------

    def connect_to(self, device: str) -> None:
        self._engine.submit("connect", device)

    def disconnect_from(self) -> None:
        self._engine.submit("disconnect")

    def set_poll(self, pids: set[int] | None = None, interval: float | None = None) -> None:
        self._engine.submit("set_poll", (pids, interval))

    def read_dtcs(self, source: str = "stored") -> None:
        self._engine.submit("read_dtcs", source)

    def clear_codes(self) -> None:
        self._engine.submit("clear_dtcs")

    def read_monitors(self) -> None:
        self._engine.submit("read_monitors")

    def read_freeze(self, pid: int = 0x0C, frame: int = 0) -> None:
        self._engine.submit("read_freeze", (pid, frame))

    def read_freeze_support(self) -> None:
        self._engine.submit("read_freeze_support")

    def read_vehicle(self) -> None:
        self._engine.submit("read_vehicle")

    def read_mode06(self) -> None:
        self._engine.submit("read_mode06")

    def read_voltage(self) -> None:
        self._engine.submit("read_voltage")

    # -- lifecycle -------------------------------------------------------------

    @property
    def engine(self) -> ObdEngine:
        return self._engine

    def run(self) -> None:
        self._engine.run_forever()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Stop the engine loop and join the thread (call before destroy)."""
        self._engine.stop()
        if self.isRunning():
            self.wait(timeout_ms)

    def _dispatch(self, kind: str, args: tuple[Any, ...]) -> None:
        if kind in self._EVENT_KINDS:
            getattr(self, kind).emit(*args)
