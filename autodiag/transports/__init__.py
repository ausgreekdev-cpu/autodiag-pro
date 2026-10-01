"""Hardware transports (serial USB / Bluetooth SPP) — see ``base.Transport``."""

from autodiag.transports.base import Transport, TransportError

__all__ = ["Transport", "TransportError"]
