"""Bundled data files (DTC dictionary, ...)."""

from importlib import resources


def read_text(filename: str) -> str:
    """Return the contents of a file bundled in ``autodiag/data``."""
    return (resources.files(__package__) / filename).read_text(encoding="utf-8")


def read_bytes(filename: str) -> bytes:
    """Return the raw contents of a (binary) file bundled in ``autodiag/data``."""
    return (resources.files(__package__) / filename).read_bytes()
