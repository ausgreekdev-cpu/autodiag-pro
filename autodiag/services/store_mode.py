"""Microsoft Store runtime detection.

Store-packaged builds (MSIX) manage their own updates and purchases; the app
detects that mode so the update check can defer to the Store instead of
GitHub. Detection is deliberately simple:

* the ``AUTODIAG_STORE_MODE`` environment variable (set by launchers), or
* the executable living inside the WindowsApps package directory.

Everything here is dependency-free and unit-testable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

STORE_ENV_VAR = "AUTODIAG_STORE_MODE"


def store_mode() -> bool:
    """True when running as (or launched for) a Microsoft Store package."""
    if os.environ.get(STORE_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}:
        return True
    parts = {part.lower() for part in Path(sys.executable).parts}
    return "windowsapps" in parts
