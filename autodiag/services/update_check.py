"""Update check: compare the running version against the latest GitHub release.

One manual HTTP request (stdlib urllib — QtNetwork is excluded from the
bundle); never runs automatically. All network access is injectable so
tests never leave the machine.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QThread, Signal

from autodiag import __version__

RELEASES_URL = "https://api.github.com/repos/ausgreekdev-cpu/autodiag-pro/releases/latest"
DEFAULT_TIMEOUT = 5.0

Fetch = Callable[[str, float], Any]


@dataclass(frozen=True)
class UpdateCheck:
    """Result of one check: ``update`` (newer release), ``current`` or ``error``."""

    status: str
    latest: str | None = None
    url: str | None = None
    message: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """Parse a release tag like ``v0.12.0`` into a comparable tuple."""
    parts = text.strip().lstrip("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"unrecognised version tag: {text!r}")
    return tuple(int(part) for part in parts)


def is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is a higher version than ``current``."""
    return parse_version(latest) > parse_version(current)


def fetch_json(url: str, timeout: float) -> Any:
    """GET ``url`` and decode the JSON body (raises OSError on network trouble)."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"autodiag-pro/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def check_for_update(
    current: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    fetch: Fetch | None = None,
) -> UpdateCheck:
    """Check GitHub for a release newer than ``current``; never raises."""
    do_fetch = fetch if fetch is not None else fetch_json
    try:
        payload = do_fetch(RELEASES_URL, timeout)
        tag = str(payload["tag_name"])
        url = str(payload.get("html_url") or RELEASES_URL)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        message = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else str(exc)
        return UpdateCheck(status="error", message=message or type(exc).__name__)
    try:
        newer = is_newer(tag, current)
    except ValueError:
        return UpdateCheck(status="error", message=f"unrecognised release tag: {tag!r}")
    if newer:
        return UpdateCheck(status="update", latest=tag, url=url)
    return UpdateCheck(status="current", latest=tag, url=url)


class UpdateCheckWorker(QThread):
    """Runs :func:`check_for_update` off the UI thread."""

    done = Signal(object)  # UpdateCheck

    def __init__(self, current: str, parent: Any = None) -> None:
        super().__init__(parent)
        self._current = current

    def run(self) -> None:
        self.done.emit(check_for_update(self._current))
