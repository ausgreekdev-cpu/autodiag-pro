"""Byte-pipe transport abstraction between the ELM327 session and hardware."""

from abc import ABC, abstractmethod


class Transport(ABC):
    """A dumb, bidirectional byte pipe (serial port, socket, ...).

    Implementations must be safe to call from a single worker thread.
    ``read`` returns whatever arrived within ``timeout`` seconds (possibly
    ``b""``) — framing (finding the ELM327 ``>`` prompt) is the session's job.
    """

    @abstractmethod
    def open(self) -> None:
        """Open the underlying connection. Raises TransportError on failure."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection. Must be idempotent."""

    @abstractmethod
    def write(self, payload: bytes) -> None:
        """Write raw bytes. Raises TransportError if the link is down."""

    @abstractmethod
    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        """Return up to ``max_bytes`` read within ``timeout``; ``b""`` if none."""

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True while the connection is usable."""

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class TransportError(Exception):
    """Raised when opening, reading or writing the link fails."""
