"""MSIX packaging: version mapping, manifest templating, logo assets, staging."""

from __future__ import annotations

import importlib.util
import xml.dom.minidom
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MSIX_DIR = ROOT / "packaging" / "msix"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build():
    return _load("build_msix", MSIX_DIR / "build_msix.py")


@pytest.fixture(scope="module")
def assets():
    return _load("make_msix_assets", MSIX_DIR / "make_msix_assets.py")


def test_msix_version_pads_to_four_parts(build):
    assert build.msix_version("0.21.0") == "0.21.0.0"
    assert build.msix_version("1.2.3") == "1.2.3.0"


def test_placeholder_identity_matches_msix_name_schema(build):
    """Identity Name must match the MSIX schema pattern [-.A-Za-z0-9]+.

    makeappx rejects anything else (underscores!), which failed the first
    CI run of the package-msix job.
    """
    import re

    name = build.PLACEHOLDER_IDENTITY["package_name"]
    assert re.fullmatch(r"[-.A-Za-z0-9]+", name)
    publisher = build.PLACEHOLDER_IDENTITY["publisher"]
    assert publisher.startswith("CN=")
    assert re.fullmatch(r"[-.A-Za-z0-9]+", publisher[3:])


@pytest.mark.parametrize("bad", ["0.21", "0.21.0.1", "0.21.x", "v0.21.0", ""])
def test_msix_version_rejects_bad_input(build, bad):
    with pytest.raises(ValueError):
        build.msix_version(bad)


def test_manifest_template_substitutes_all_placeholders(build):
    template = (MSIX_DIR / "Package.appxmanifest").read_text(encoding="utf-8")
    rendered = build.render_manifest(
        template,
        package_name="AutoDiagPro_Test123",
        publisher="CN=TestPublisher42",
        publisher_display="Test Publisher",
        version="0.21.0",
    )
    assert "{{" not in rendered
    dom = xml.dom.minidom.parseString(rendered)  # parses or raises
    identity = dom.getElementsByTagName("Identity")[0]
    assert identity.getAttribute("Name") == "AutoDiagPro_Test123"
    assert identity.getAttribute("Publisher") == "CN=TestPublisher42"
    assert identity.getAttribute("Version") == "0.21.0.0"
    publisher_display = dom.getElementsByTagName("PublisherDisplayName")[0]
    assert publisher_display.firstChild.data == "Test Publisher"


def test_manifest_declares_full_trust_application(build):
    template = (MSIX_DIR / "Package.appxmanifest").read_text(encoding="utf-8")
    rendered = build.render_manifest(
        template,
        package_name="P",
        publisher="CN=P",
        publisher_display="P",
        version="0.0.1",
    )
    dom = xml.dom.minidom.parseString(rendered)
    application = dom.getElementsByTagName("Application")[0]
    assert application.getAttribute("Executable") == build.EXE_NAME
    assert application.getAttribute("EntryPoint") == "Windows.FullTrustApplication"
    capability = dom.getElementsByTagName("rescap:Capability")[0]
    assert capability.getAttribute("Name") == "runFullTrust"


def test_pyproject_version_renders_into_manifest(build):
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    template = (MSIX_DIR / "Package.appxmanifest").read_text(encoding="utf-8")
    rendered = build.render_manifest(
        template, package_name="P", publisher="CN=P", publisher_display="P",
        version=version,
    )
    dom = xml.dom.minidom.parseString(rendered)
    assert dom.getElementsByTagName("Identity")[0].getAttribute("Version") == (
        build.msix_version(version)
    )


def test_render_manifest_rejects_unsubstituted_placeholders(build):
    with pytest.raises(ValueError, match="placeholders"):
        build.render_manifest(
            "{{VERSION}} {{UNKNOWN}}", package_name="P", publisher="CN=P",
            publisher_display="P", version="1.0.0",
        )


def test_stage_package_copies_exe_and_manifest(build, tmp_path):
    exe = tmp_path / "autodiag.exe"
    exe.write_bytes(b"MZ fake windows executable")
    stage = tmp_path / "stage"
    build.stage_package(
        exe=exe, stage_dir=stage, manifest_text="<Package/>"
    )
    assert (stage / build.EXE_NAME).read_bytes() == b"MZ fake windows executable"
    assert (stage / build.MANIFEST_NAME).read_text(encoding="utf-8") == "<Package/>"


def test_write_assets_generates_manifest_referenced_pngs(assets, tmp_path):
    written = assets.write_assets(tmp_path)
    names = {path.name for path in written}
    assert names == set(assets.SIZES)
    for path in written:
        blob = path.read_bytes()
        assert blob.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(blob) > 200
    # every size the manifest references must exist
    template = (MSIX_DIR / "Package.appxmanifest").read_text(encoding="utf-8")
    for logo in ("Square44x44Logo.png", "Square150x150Logo.png", "SplashScreen.png",
                 "StoreLogo50.png"):
        assert logo in template
        assert (tmp_path / logo).is_file()


def test_stage_dir_matches_manifest_executable(build):
    """The staged exe filename and the manifest's Executable attribute agree."""
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]
    template = (MSIX_DIR / "Package.appxmanifest").read_text(encoding="utf-8")
    rendered = build.render_manifest(
        template, package_name="P", publisher="CN=P", publisher_display="P",
        version=version,
    )
    assert f'Executable="{build.EXE_NAME}"' in rendered
