"""Store bundle checker tests."""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

from autodiag import __version__  # noqa: E402


def _load_store_check():
    path = ROOT / "packaging" / "store_check.py"
    spec = importlib.util.spec_from_file_location("store_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_msix(path: Path, manifest: str = "<Package></Package>") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("assets/icon-256.png", b"png")


def _write_repo(repo: Path, *, eula_sync: bool = True, readme: str = "") -> None:
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "store").mkdir()
    (repo / "packaging" / "msix").mkdir(parents=True)
    (repo / "autodiag" / "data").mkdir(parents=True)
    eula_text = "EULA text\n"
    (repo / "autodiag" / "data" / "eula.txt").write_text(eula_text)
    (repo / "docs" / "eula.md").write_text(eula_text if eula_sync else "different\n")
    (repo / "docs" / "privacy-policy.md").write_text("Privacy\n")
    (repo / "docs" / "store" / "STORE.md").write_text("Listing draft\n")
    (repo / "packaging" / "msix" / "Package.appxmanifest").write_text("<Package/>\n")
    (repo / "packaging" / "version_info.txt").write_text("0\n")
    (repo / "README.md").write_text(readme)


def _readme() -> str:
    return f"# AutoDiag Pro\n\n| 35. Launch (v{__version__}) | done |\n$34 $49/mo\n"


def test_check_bundle_passes_on_complete_release(tmp_path):
    check = _load_store_check()
    release = tmp_path / "out"
    release.mkdir()
    _write_msix(release / "autodiag.msix")
    repo = tmp_path / "repo"
    _write_repo(repo, readme=_readme())
    assert check.check_bundle(release, repo) == []


def test_check_bundle_reports_missing_msix(tmp_path):
    check = _load_store_check()
    problems = check.check_bundle(tmp_path, tmp_path)
    assert any("no .msix" in problem for problem in problems)


def test_check_bundle_flags_manifest_placeholder(tmp_path):
    check = _load_store_check()
    release = tmp_path / "out"
    release.mkdir()
    _write_msix(release / "autodiag.msix", manifest='<Identity Name="{{PACKAGE_NAME}}"/>')
    _write_repo(tmp_path, readme=_readme())
    problems = check.check_bundle(release, tmp_path)
    assert any("{{PACKAGE_NAME}}" in problem for problem in problems)


def test_check_bundle_flags_unsynced_eula(tmp_path):
    check = _load_store_check()
    release = tmp_path / "out"
    release.mkdir()
    _write_msix(release / "autodiag.msix")
    _write_repo(tmp_path, eula_sync=False, readme=_readme())
    problems = check.check_bundle(release, tmp_path)
    assert any("EULA is out of sync" in problem for problem in problems)


def test_check_bundle_flags_store_placeholders(tmp_path):
    check = _load_store_check()
    release = tmp_path / "out"
    release.mkdir()
    _write_msix(release / "autodiag.msix")
    repo = tmp_path / "repo"
    _write_repo(repo, readme=_readme())
    (repo / "docs" / "store" / "STORE.md").write_text("Support URL: [your email]\n")
    problems = check.check_bundle(release, repo)
    assert any("[your " in problem for problem in problems)
