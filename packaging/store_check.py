"""Validate the release bundle for the Microsoft Store listing.

Run after the MSIX build (the ``package-msix`` job does this automatically):

    python packaging/store_check.py --release-dir out --repo-root .

Prints one line per problem and exits non-zero when anything fails, so launch
day is a copy-paste job instead of a scavenger hunt.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autodiag import __version__  # noqa: E402

MANIFEST_PLACEHOLDERS = ("{{PACKAGE_NAME}}", "{{PUBLISHER}}", "{{PUBLISHER_DISPLAY}}")
STORE_MARKERS = ("[set ", "[your ", "[when publishing")


def check_bundle(release_dir: Path, repo_root: Path) -> list[str]:
    """Return a list of problems (empty means launch-ready)."""
    problems: list[str] = []

    packages = sorted(release_dir.glob("*.msix"))
    if not packages:
        problems.append(f"no .msix package found in {release_dir}")

    for package in packages:
        try:
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                manifest = archive.read("AppxManifest.xml").decode("utf-8", "replace")
        except (OSError, zipfile.BadZipFile) as exc:
            problems.append(f"{package.name}: not a readable MSIX archive ({exc})")
            continue
        for placeholder in MANIFEST_PLACEHOLDERS:
            if placeholder in manifest:
                problems.append(
                    f"{package.name}: manifest still has the {placeholder} placeholder"
                )
        # Every icon the manifest references must be inside the package.
        referenced = set(re.findall(r'"([^"]+\.png)"', manifest))
        missing = sorted(name for name in referenced if name not in names)
        if missing:
            problems.append(
                f"{package.name}: manifest references missing icons: {', '.join(missing)}"
            )

    for required in (
        "docs/privacy-policy.md",
        "docs/store/STORE.md",
        "packaging/msix/Package.appxmanifest",
        "packaging/version_info.txt",
    ):
        if not (repo_root / required).is_file():
            problems.append(f"missing repo artifact: {required}")

    eula = repo_root / "autodiag/data/eula.txt"
    eula_doc = repo_root / "docs/eula.md"
    if eula.is_file() and eula_doc.is_file():
        if eula.read_text(encoding="utf-8") != eula_doc.read_text(encoding="utf-8"):
            problems.append("bundled EULA is out of sync with docs/eula.md")

    store_doc = repo_root / "docs" / "store" / "STORE.md"
    if store_doc.is_file():
        for marker in STORE_MARKERS:
            if marker in store_doc.read_text(encoding="utf-8").lower():
                problems.append(f"STORE.md still contains the placeholder {marker!r}")

    readme_path = repo_root / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        for price in ("$34", "$49/mo"):
            if price not in readme:
                problems.append(f"README tier table is missing the {price} price")
        if f"v{__version__}" not in readme:
            problems.append("README milestone table has no row for the current version")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-dir",
        default="out",
        help="directory holding the built .msix (default: out)",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="repository root (default: current directory)",
    )
    args = parser.parse_args(argv)

    release_dir = Path(args.release_dir)
    repo_root = Path(args.repo_root).resolve()
    problems = check_bundle(release_dir, repo_root)
    for problem in problems:
        print(f"FAIL  {problem}")
    if problems:
        print(f"{len(problems)} problem(s) — see docs/store/STORE.md")
        return 1
    print(f"Store bundle OK — {release_dir} is launch-ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
