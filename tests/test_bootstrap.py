"""Bootstrap smoke tests: package metadata, entry point, Transport contract."""

import re

import pytest

import autodiag
from autodiag import __main__ as main_mod
from autodiag.transports import Transport, TransportError


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", autodiag.__version__)


def test_entry_point_prints_version(capsys):
    main_mod.main()
    out = capsys.readouterr().out
    assert "AutoDiag Pro" in out
    assert autodiag.__version__ in out


def test_subpackages_importable():
    import autodiag.data  # noqa: F401
    import autodiag.obd  # noqa: F401
    import autodiag.services  # noqa: F401
    import autodiag.transports  # noqa: F401
    import autodiag.ui  # noqa: F401


class DummyTransport(Transport):
    """Minimal concrete transport used to exercise the ABC contract."""

    def __init__(self) -> None:
        self._open = False
        self.sent: list[bytes] = []

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, payload: bytes) -> None:
        if not self._open:
            raise TransportError("not open")
        self.sent.append(payload)

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        return b""

    @property
    def is_open(self) -> bool:
        return self._open


def test_transport_abstract_methods_enforced():
    with pytest.raises(TypeError):
        Transport()  # type: ignore[abstract]


def test_transport_context_manager():
    with DummyTransport() as t:
        assert t.is_open
        t.write(b"0100\r")
    assert not t.is_open
    assert t.sent == [b"0100\r"]
