"""Store runtime detection tests."""

from __future__ import annotations

from autodiag.services import store_mode


def test_env_var_enables_store_mode(monkeypatch):
    monkeypatch.setenv("AUTODIAG_STORE_MODE", "1")
    assert store_mode.store_mode() is True


def test_env_var_off_for_normal_install(monkeypatch):
    monkeypatch.delenv("AUTODIAG_STORE_MODE", raising=False)
    monkeypatch.setattr("sys.executable", "/usr/bin/autodiag")
    assert store_mode.store_mode() is False


def test_windowsapps_path_enables_store_mode(monkeypatch):
    monkeypatch.delenv("AUTODIAG_STORE_MODE", raising=False)
    monkeypatch.setattr(
        "sys.executable",
        "C:/Program Files/WindowsApps/AutoDiagPro_1.0.0_x64/autodiag.exe",
    )
    assert store_mode.store_mode() is True
