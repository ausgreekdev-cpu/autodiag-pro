# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AutoDiag Pro (one-file GUI executable).

Build:  pyinstaller --noconfirm autodiag.spec
Output: dist/autodiag  (.exe on Windows)
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("autodiag")
hiddenimports = collect_submodules("pyqtgraph")

a = Analysis(
    ["autodiag/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # QtNetwork is pulled in only by PySide6's Windows-only SSL probe; the app
    # never uses it and it fails to load on hosts without Kerberos libs.
    excludes=["PySide6.QtNetwork"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="autodiag",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="packaging/autodiag.ico",
)
