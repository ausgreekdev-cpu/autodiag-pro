"""UI gating: EULA first-run, upgrade dialog, panel locks, history truncation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QPushButton, QTableWidget

from autodiag.services.history import SessionStore
from autodiag.services.license import (
    EULA_VERSION,
    LicenseManager,
    LicenseState,
    Tier,
)
from autodiag.services.record import ScanRecord
from autodiag.ui.license import (
    SafetyNoticeDialog,
    UpgradeDialog,
    ensure_eula_accepted,
    try_unlock,
)
from autodiag.ui.panels.history import HistoryPanel
from autodiag.ui.panels.settings import SettingsPanel
from autodiag.ui.panels.uds import UdsPanel
from autodiag.ui.prefs import Prefs
from tests.test_history import _report


def _prefs(tmp_path) -> Prefs:
    settings = QSettings(
        str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat
    )
    return Prefs(settings)


def _free_manager(tmp_path) -> LicenseManager:
    return LicenseManager(key_path=tmp_path / "license.json")  # no key → Free


def _workshop_manager(tmp_path) -> LicenseManager:
    return LicenseManager(
        key_path=tmp_path / "license.json",
        state=LicenseState(Tier.WORKSHOP, source="key", licensee="Tests"),
    )


# -- EULA ---------------------------------------------------------------------


class _FakeSafetyDialog:
    """Stands in for SafetyNoticeDialog; records construction."""

    constructed: list = []
    answer = QDialog.DialogCode.Accepted

    def __init__(self, parent=None):
        type(self).constructed.append(self)

    def exec(self):
        return type(self).answer


def test_eula_accepted_sets_version_once(tmp_path):
    _FakeSafetyDialog.constructed.clear()
    prefs = _prefs(tmp_path)
    assert prefs.eula_version() == ""

    assert ensure_eula_accepted(None, prefs, _FakeSafetyDialog) is True
    assert prefs.eula_version() == EULA_VERSION
    assert len(_FakeSafetyDialog.constructed) == 1

    # second launch: no dialog
    assert ensure_eula_accepted(None, prefs, _FakeSafetyDialog) is True
    assert len(_FakeSafetyDialog.constructed) == 1


def test_eula_declined_keeps_version_empty(tmp_path):
    _FakeSafetyDialog.constructed.clear()
    _FakeSafetyDialog.answer = QDialog.DialogCode.Rejected
    prefs = _prefs(tmp_path)
    try:
        assert ensure_eula_accepted(None, prefs, _FakeSafetyDialog) is False
        assert prefs.eula_version() == ""
    finally:
        _FakeSafetyDialog.answer = QDialog.DialogCode.Accepted


def test_safety_dialog_ships_eula_text(qapp):
    dialog = SafetyNoticeDialog()
    headings = [
        label for label in dialog.findChildren(QLabel) if label.objectName() == "heading"
    ]
    assert headings and "Before you use" in headings[0].text()
    viewers = dialog.findChildren(QPlainTextEdit)
    assert viewers and "No manufacturer affiliation" in viewers[0].toPlainText()
    assert not dialog._accept_btn.isEnabled()
    dialog._accept_chk.setChecked(True)
    assert dialog._accept_btn.isEnabled()
    dialog.deleteLater()


# -- upgrade dialog / try_unlock ------------------------------------------------


class _FakeUpgrade:
    constructed: list = []

    def __init__(self, manager, feature, parent=None):
        type(self).constructed.append((manager, feature))

    def exec(self):
        return QDialog.DialogCode.Accepted


def test_try_unlock_allowed_skips_dialog(tmp_path, monkeypatch):
    _FakeUpgrade.constructed.clear()
    monkeypatch.setattr("autodiag.ui.license.UpgradeDialog", _FakeUpgrade)
    manager = _workshop_manager(tmp_path)
    assert try_unlock(None, manager, "pdf.export") is True
    assert _FakeUpgrade.constructed == []


def test_try_unlock_blocked_opens_dialog(tmp_path, monkeypatch):
    _FakeUpgrade.constructed.clear()
    monkeypatch.setattr("autodiag.ui.license.UpgradeDialog", _FakeUpgrade)
    manager = _free_manager(tmp_path)
    assert try_unlock(None, manager, "pdf.export") is False
    assert _FakeUpgrade.constructed == [(manager, "pdf.export")]


def test_upgrade_dialog_builds_tier_table(tmp_path, qapp):
    manager = _free_manager(tmp_path)
    dialog = UpgradeDialog(manager, "uds.read")
    tables = dialog.findChildren(QTableWidget)
    assert len(tables) == 1
    assert tables[0].rowCount() == 6
    assert tables[0].columnCount() == 4
    labels = [button.text() for button in dialog.findChildren(QPushButton)]
    assert any("Install licence key" in text for text in labels)
    dialog.deleteLater()


# -- history panel ---------------------------------------------------------------


def _fill_sessions(store: SessionStore, count: int) -> None:
    base = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    for index in range(count):
        store.save(_report(), when=base + timedelta(minutes=index))


def test_history_truncated_for_free_tier(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    _fill_sessions(store, 12)
    panel = HistoryPanel(store, license_manager=_free_manager(tmp_path))
    assert panel._table.rowCount() == 10
    assert "10 of 12" in panel._count_label.text()
    assert "Pro unlocks" in panel._count_label.text()
    panel.deleteLater()


def test_history_full_for_workshop_tier(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    _fill_sessions(store, 12)
    panel = HistoryPanel(store, license_manager=_workshop_manager(tmp_path))
    assert panel._table.rowCount() == 12
    assert panel._count_label.text() == "12 session(s)"
    panel.deleteLater()


def test_history_work_order_gated(tmp_path, monkeypatch):
    _FakeUpgrade.constructed.clear()
    monkeypatch.setattr("autodiag.ui.license.UpgradeDialog", _FakeUpgrade)

    class _NoWorkOrder:
        def __init__(self, *args, **kwargs):
            raise AssertionError("WorkOrderDialog must not open while locked")

    monkeypatch.setattr("autodiag.ui.panels.history.WorkOrderDialog", _NoWorkOrder)
    store = SessionStore(tmp_path / "sessions")
    _fill_sessions(store, 1)
    panel = HistoryPanel(store, license_manager=_free_manager(tmp_path))
    panel._table.selectRow(0)
    assert panel._selected is not None
    panel._on_work_order()
    assert _FakeUpgrade.constructed[-1][1] == "work_order"
    panel.deleteLater()


# -- settings panel ---------------------------------------------------------------


def test_settings_shows_tier_and_gates_pdf(tmp_path, monkeypatch):
    messages: list[str] = []
    panel = SettingsPanel(
        ScanRecord(), messages.append, license_manager=_free_manager(tmp_path)
    )
    assert "Tier: Free" in panel._tier_label.text()

    def _blocked(*_args, **_kwargs):
        raise AssertionError("file dialog must not open while locked")

    monkeypatch.setattr(
        "autodiag.ui.panels.settings.try_unlock", lambda *a: False
    )
    monkeypatch.setattr(
        "autodiag.ui.panels.settings.QFileDialog.getSaveFileName", _blocked
    )
    panel.export_with_dialog("pdf")
    assert messages and "Pro" in messages[-1]
    panel.deleteLater()


def test_settings_tier_label_reflects_key(tmp_path):
    manager = _workshop_manager(tmp_path)
    panel = SettingsPanel(ScanRecord(), lambda _m: None, license_manager=manager)
    assert "Tier: Workshop" in panel._tier_label.text()
    assert "Tests" in panel._tier_label.text()
    panel.deleteLater()


# -- UDS panel --------------------------------------------------------------------


def _worker():
    from autodiag.services.worker import ObdWorker

    return ObdWorker()


def test_uds_reads_blocked_on_free_tier(tmp_path, monkeypatch):
    _FakeUpgrade.constructed.clear()
    monkeypatch.setattr("autodiag.ui.license.UpgradeDialog", _FakeUpgrade)
    worker = _worker()
    sent: list = []
    monkeypatch.setattr(worker, "uds_request", lambda req, **kw: sent.append(req))
    panel = UdsPanel(worker, license_manager=_free_manager(tmp_path))
    panel._connected = True
    panel._send("22F190")
    assert sent == []
    assert "Pro" in panel._status.text()
    assert _FakeUpgrade.constructed[-1][1] == "uds.read"
    panel.deleteLater()


def test_uds_reads_allowed_on_workshop_tier(tmp_path, monkeypatch):
    worker = _worker()
    sent: list = []
    monkeypatch.setattr(worker, "uds_request", lambda req, **kw: sent.append(req))
    panel = UdsPanel(worker, license_manager=_workshop_manager(tmp_path))
    panel._connected = True
    panel._send("22F190")
    assert sent == ["22F190"]
    panel.deleteLater()


def test_uds_waiver_blocked_on_free_tier(tmp_path, monkeypatch):
    _FakeUpgrade.constructed.clear()
    monkeypatch.setattr("autodiag.ui.license.UpgradeDialog", _FakeUpgrade)
    worker = _worker()
    panel = UdsPanel(worker, license_manager=_free_manager(tmp_path))
    panel._connected = True
    panel._waiver_chk.setChecked(True)
    assert panel._waiver_chk.isChecked() is False
    assert not panel._write_btn.isEnabled()
    assert _FakeUpgrade.constructed[-1][1] == "uds.write"
    panel.deleteLater()


def test_upgrade_dialog_store_button(qapp, monkeypatch, tmp_path):
    from autodiag.ui.prefs import Prefs

    manager = _free_manager(tmp_path)
    dialog = UpgradeDialog(manager, "pdf.export")
    assert dialog._store_btn.isEnabled()

    opened: list[str] = []
    monkeypatch.setattr(
        "PySide6.QtGui.QDesktopServices.openUrl",
        staticmethod(lambda url: opened.append(url.toString()) or True),
    )
    monkeypatch.setattr(
        "autodiag.ui.license.QMessageBox.information", lambda *_a, **_k: None
    )

    # No product ID yet → info dialog, no navigation.
    dialog._store_btn.click()
    assert opened == []

    monkeypatch.setattr(Prefs, "store_product_id", lambda _self: "9NBLGGH4R32N")
    dialog._store_btn.click()
    assert opened == ["ms-windows-store://pdp/?ProductId=9NBLGGH4R32N"]
