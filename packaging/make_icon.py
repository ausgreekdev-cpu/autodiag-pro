"""Generate the app icon: packaging/autodiag.ico + assets/icon-256.png.

Run from the repository root:  python packaging/make_icon.py
(The drawing is done on a 1024px canvas and downsampled for crisp edges.)
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICO_PATH = ROOT / "packaging" / "autodiag.ico"
PNG_PATH = ROOT / "assets" / "icon-256.png"

S = 1024  # supersampled canvas
BG = (15, 20, 26, 255)
BORDER = (42, 52, 65, 255)
TRACK = (30, 39, 50, 255)
ACCENT = (47, 129, 247, 255)
TEXT = (230, 237, 243, 255)

_FILL = 0.72  # needle/arc position
_START = 135  # PIL degrees: lower-left (screen y-down)
_SWEEP = 270  # clockwise to lower-right


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    painter = ImageDraw.Draw(img)

    # rounded square plate
    painter.rounded_rectangle(
        [40, 40, S - 40, S - 40],
        radius=S // 5,
        fill=BG,
        outline=BORDER,
        width=14,
    )

    # gauge ring: track, then filled portion
    bbox = [190, 190, S - 190, S - 190]
    arc_width = 74
    painter.arc(bbox, _START, _START + _SWEEP, fill=TRACK, width=arc_width)
    painter.arc(
        bbox, _START, _START + int(_SWEEP * _FILL), fill=ACCENT, width=arc_width
    )

    # needle pointing at the fill position + hub
    cx = cy = S / 2
    radius = (S - 380) / 2  # matches the arc bbox
    angle = math.radians(_START + _SWEEP * _FILL)
    tip = (cx + radius * 0.76 * math.cos(angle), cy + radius * 0.76 * math.sin(angle))
    tail = (cx - radius * 0.10 * math.cos(angle), cy - radius * 0.10 * math.sin(angle))
    painter.line([tail, tip], fill=TEXT, width=26, joint="curve")
    painter.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], fill=TEXT)
    painter.ellipse([cx - 18, cy - 18, cx + 18, cy + 18], fill=BG)
    return img


def main() -> None:
    icon = draw_icon()

    png256 = icon.resize((256, 256), Image.Resampling.LANCZOS)
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    png256.save(PNG_PATH)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    png256.save(ICO_PATH, format="ICO", sizes=[(s, s) for s in sizes])

    print(f"wrote {ICO_PATH.relative_to(ROOT)} ({ICO_PATH.stat().st_size} bytes)")
    print(f"wrote {PNG_PATH.relative_to(ROOT)} ({PNG_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
