"""Generate packaging/version_info.txt (Windows exe file properties).

Run from the repository root:  python packaging/make_version_info.py

The text file is eval()'d by PyInstaller on Windows builds against
PyInstaller.utils.win32.versioninfo's classes, so keep it plain ASCII.
The committed copy is kept in sync with pyproject.toml by a test.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "packaging" / "version_info.txt"


def parse_version(version: str) -> tuple[int, int, int, int]:
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"expected MAJOR.MINOR.PATCH, got {version!r}")
    numbers = tuple(int(p) for p in parts)
    return numbers + (0,)


def build_version_text(version: str) -> str:
    quad = parse_version(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={quad},
    prodvers={quad},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904b0',
          [
            StringStruct('CompanyName', 'AutoDiagPro'),
            StringStruct('FileDescription', 'AutoDiag Pro - OBD-II diagnostics'),
            StringStruct('FileVersion', '{version}'),
            StringStruct('InternalName', 'autodiag'),
            StringStruct('OriginalFilename', 'autodiag.exe'),
            StringStruct('ProductName', 'AutoDiag Pro'),
            StringStruct('ProductVersion', '{version}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    text = build_version_text(data["project"]["version"])
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
