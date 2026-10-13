"""Build the Microsoft Store MSIX package for AutoDiag Pro.

Stages the PyInstaller Windows executable with the appx manifest and logo
assets, and (with --pack, Windows only) compresses the folder into an
unsigned .msix via makeappx.exe from the Windows SDK. Partner Center
re-signs uploaded packages with its own certificate, so the artifact does
not need a signature for Store submission.

Run from the repository root:

  python packaging/msix/build_msix.py --dist dist/autodiag.exe --out out --pack

Identity (argument > environment variable > placeholder used for CI smoke
builds until a real Partner Center identity exists):

  --package-name       / MSIX_PACKAGE_NAME          reserved Store package Name
  --publisher          / MSIX_PUBLISHER             verified publisher, e.g. CN=Ab12Cd34
  --publisher-display  / MSIX_PUBLISHER_DISPLAY     display name, e.g. "Jane Doe"

The package Version is the pyproject version padded to four parts
(0.21.0 -> 0.21.0.0) as MSIX requires.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_TEMPLATE = Path(__file__).resolve().parent / "Package.appxmanifest"
EXE_NAME = "autodiag-windows-x86_64.exe"
MANIFEST_NAME = "AppxManifest.xml"

PLACEHOLDER_IDENTITY = {
    # Identity Name must match the MSIX schema pattern [-.A-Za-z0-9]+ —
    # no underscores.
    "package_name": "AutoDiagPro-Placeholder",
    "publisher": "CN=AutoDiagPro-Placeholder",
    "publisher_display": "AutoDiag Pro",
}


def msix_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"expected MAJOR.MINOR.PATCH, got {version!r}")
    return f"{parts[0]}.{parts[1]}.{parts[2]}.0"


def render_manifest(
    template: str,
    *,
    package_name: str,
    publisher: str,
    publisher_display: str,
    version: str,
) -> str:
    text = template
    for key, value in (
        ("{{PACKAGE_NAME}}", package_name),
        ("{{PUBLISHER}}", publisher),
        ("{{PUBLISHER_DISPLAY}}", publisher_display),
        ("{{VERSION}}", msix_version(version)),
    ):
        text = text.replace(key, value)
    if "{{" in text:
        raise ValueError("manifest template still contains unsubstituted placeholders")
    return text


def stage_package(*, exe: Path, stage_dir: Path, manifest_text: str) -> Path:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    shutil.copy2(exe, stage_dir / EXE_NAME)
    (stage_dir / MANIFEST_NAME).write_text(manifest_text, encoding="utf-8")
    return stage_dir


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def find_makeappx() -> Path | None:
    override = os.environ.get("MAKEAPPX")
    if override and Path(override).is_file():
        return Path(override)
    which = shutil.which("makeappx")
    if which:
        return Path(which)
    candidates: list[Path] = []
    for base in (
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin"),
        Path(r"C:\Program Files\Windows Kits\10\bin"),
    ):
        if base.is_dir():
            candidates.extend(base.glob("*/x64/makeappx.exe"))
    if not candidates:
        return None

    def kit_version(path: Path) -> tuple[int, ...]:
        parts = path.parent.parent.name.split(".")
        numbers = tuple(int(p) for p in parts if p.isdigit())
        return numbers or (0,)

    return max(candidates, key=kit_version)


def pack_package(stage_dir: Path, out_msix: Path) -> Path:
    makeappx = find_makeappx()
    if makeappx is None:
        raise SystemExit("makeappx.exe not found — install the Windows SDK or set MAKEAPPX")
    out_msix.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(makeappx), "pack", "/d", str(stage_dir), "/p", str(out_msix), "/o"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"makeappx pack failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )
    return out_msix


def resolve_identity(args: argparse.Namespace) -> tuple[str, str, str]:
    package_name = (
        args.package_name or os.environ.get("MSIX_PACKAGE_NAME") or
        PLACEHOLDER_IDENTITY["package_name"]
    )
    publisher = (
        args.publisher or os.environ.get("MSIX_PUBLISHER") or
        PLACEHOLDER_IDENTITY["publisher"]
    )
    publisher_display = (
        args.publisher_display or os.environ.get("MSIX_PUBLISHER_DISPLAY") or
        PLACEHOLDER_IDENTITY["publisher_display"]
    )
    return package_name, publisher, publisher_display


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dist",
        type=Path,
        required=True,
        help="PyInstaller Windows executable (any filename; staged as "
             f"{EXE_NAME})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "out",
        help="output directory for stage/ and the .msix (default: out/)",
    )
    parser.add_argument(
        "--pack",
        action="store_true",
        help="compress to .msix with makeappx (Windows only)",
    )
    parser.add_argument("--package-name", default=None, help="Store package Name")
    parser.add_argument("--publisher", default=None, help="verified publisher, e.g. CN=...")
    parser.add_argument("--publisher-display", default=None, help="publisher display name")
    args = parser.parse_args(argv)

    package_name, publisher, publisher_display = resolve_identity(args)
    if (
        package_name == PLACEHOLDER_IDENTITY["package_name"]
        or publisher == PLACEHOLDER_IDENTITY["publisher"]
    ):
        print(
            "warning: building with PLACEHOLDER identity — set MSIX_PACKAGE_NAME "
            "and MSIX_PUBLISHER (Partner Center values) before submitting to the Store",
            file=sys.stderr,
        )

    if not args.dist.is_file():
        raise SystemExit(f"executable not found: {args.dist}")

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    manifest_text = render_manifest(
        MANIFEST_TEMPLATE.read_text(encoding="utf-8"),
        package_name=package_name,
        publisher=publisher,
        publisher_display=publisher_display,
        version=version,
    )

    stage_dir = args.out / "stage"
    stage_package(exe=args.dist, stage_dir=stage_dir, manifest_text=manifest_text)

    assets = _load_module(
        "make_msix_assets", Path(__file__).resolve().parent / "make_msix_assets.py"
    )
    written = assets.write_assets(stage_dir)
    print(f"staged {stage_dir} ({len(written)} assets, version {msix_version(version)})")

    if args.pack:
        out_msix = args.out / f"AutoDiagPro_{msix_version(version)}_x64.msix"
        pack_package(stage_dir, out_msix)
        print(f"packed {out_msix} ({out_msix.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
