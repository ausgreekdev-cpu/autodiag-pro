"""Generate the MSIX logo assets for the Microsoft Store package.

Reuses the gauge artwork from packaging/make_icon.py (draw_icon) and emits
the exact-size PNGs the Package.appxmanifest references:

  Square44x44Logo.png    44x44
  Square150x150Logo.png  150x150
  Square310x310Logo.png  310x310
  StoreLogo50.png        50x50
  SplashScreen.png       620x300

Run from the repository root:  python packaging/msix/make_msix_assets.py [target_dir]
Default target: packaging/msix/assets/ (generated, not committed).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
MAKE_ICON = ROOT / "packaging" / "make_icon.py"
DEFAULT_TARGET = Path(__file__).resolve().parent / "assets"

# Brand background matches make_icon.BG so the tiles read as one surface.
BG = (15, 20, 26, 255)
FILL = 0.66  # icon occupies this fraction of the shorter canvas side

SIZES: dict[str, tuple[int, int]] = {
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
    "Square310x310Logo.png": (310, 310),
    "StoreLogo50.png": (50, 50),
    "SplashScreen.png": (620, 300),
}


def _load_draw_icon():
    spec = importlib.util.spec_from_file_location("make_icon", MAKE_ICON)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.draw_icon


def compose(icon: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    canvas = Image.new("RGBA", (w, h), BG)
    extent = int(min(w, h) * FILL)
    scaled = icon.resize((extent, extent), Image.Resampling.LANCZOS)
    canvas.paste(scaled, ((w - extent) // 2, (h - extent) // 2), scaled)
    return canvas


def write_assets(target: Path = DEFAULT_TARGET) -> list[Path]:
    draw = _load_draw_icon()
    icon = draw()
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, size in SIZES.items():
        path = target / name
        compose(icon, size).save(path)
        written.append(path)
    return written


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    for path in write_assets(target):
        print(f"wrote {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
