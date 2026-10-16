"""First-run safety/EULA notice and the tier upgrade dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.data import read_bytes
from autodiag.services.license import (
    EULA_VERSION,
    FEATURE_LABELS,
    LicenseError,
    LicenseManager,
    feature_tier,
    tier_label,
)

#: feature rows shown in the upgrade table: (label, Free, Pro, Workshop)
_TIER_ROWS = (
    ("Session history", "Last 10", "Full", "Full"),
    ("CSV & HTML export", "✓", "✓", "✓"),
    ("UDS module reads ($10/$19/$22)", "—", "✓", "✓"),
    ("PDF reports", "—", "✓", "✓"),
    ("UDS write services", "—", "—", "✓"),
    ("Work orders", "—", "—", "✓"),
)
_TIER_HEADERS = ("Feature", "Free $0", "Pro $34", "Workshop $49/mo")


def eula_text() -> str:
    """The bundled EULA/safety text (single source: autodiag/data/eula.txt)."""
    return read_bytes("eula.txt").decode("utf-8")


class SafetyNoticeDialog(QDialog):
    """First-run acceptance of the safety notice + EULA."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Safety notice & licence agreement")
        self.setModal(True)
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        heading = QLabel("Before you use AutoDiag Pro")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(eula_text())
        layout.addWidget(text, 1)

        self._accept_chk = QCheckBox(
            "I have read the safety notice and agree to the EULA"
        )
        layout.addWidget(self._accept_chk)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._decline_btn = QPushButton("Decline")
        self._decline_btn.clicked.connect(self.reject)
        buttons.addWidget(self._decline_btn)
        self._accept_btn = QPushButton("Accept")
        self._accept_btn.setObjectName("primary")
        self._accept_btn.setEnabled(False)
        self._accept_btn.clicked.connect(self.accept)
        buttons.addWidget(self._accept_btn)
        self._accept_chk.toggled.connect(self._accept_btn.setEnabled)
        layout.addLayout(buttons)


def install_license_key(parent: QWidget, manager: LicenseManager) -> bool:
    """File picker + validate + persist. True when a key was installed."""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Install licence key", "", "Licence key (*.json)"
    )
    if not path:
        return False
    try:
        state = manager.install_key(path)
    except LicenseError as exc:
        QMessageBox.warning(parent, "Licence key rejected", str(exc))
        return False
    QMessageBox.information(
        parent,
        "Licence installed",
        f"Tier is now {tier_label(state.tier)}"
        + (f" for {state.licensee}." if state.licensee else "."),
    )
    return True


class UpgradeDialog(QDialog):
    """Tier comparison + license-key install for a locked feature."""

    def __init__(
        self,
        manager: LicenseManager,
        feature: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("Upgrade AutoDiag Pro")
        self.setModal(True)
        self.resize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        required = feature_tier(feature)
        state = manager.current()
        heading = QLabel(f"{FEATURE_LABELS.get(feature, feature)} — {tier_label(required)} feature")
        heading.setObjectName("heading")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        current = f"Current tier: {tier_label(state.tier)}"
        if state.licensee:
            current += f" ({state.licensee})"
        if state.expires is not None:
            current += f" — expires {state.expires.isoformat()}"
        sub = QLabel(
            current
            if state.tier >= required
            else f"{current}. Unlock {tier_label(required)} with a licence key "
            "(or a Store purchase when Store billing arrives)."
        )
        sub.setObjectName("subtle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        table = QTableWidget(len(_TIER_ROWS), len(_TIER_HEADERS))
        table.setHorizontalHeaderLabels(list(_TIER_HEADERS))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(True)
        table.verticalHeader().setDefaultSectionSize(26)
        for row, values in enumerate(_TIER_ROWS):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.setMinimumWidth(520)
        layout.addWidget(table, 1)

        buttons = QHBoxLayout()
        self._key_btn = QPushButton("Install licence key…")
        self._key_btn.clicked.connect(self._install_key)
        buttons.addWidget(self._key_btn)
        self._store_btn = QPushButton("Upgrade in Store…")
        self._store_btn.clicked.connect(self._open_store)
        buttons.addWidget(self._store_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _install_key(self) -> None:
        if install_license_key(self, self._manager):
            self.accept()

    def _open_store(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from autodiag.ui.prefs import Prefs

        product_id = Prefs().store_product_id()
        if not product_id:
            QMessageBox.information(
                self,
                "Microsoft Store",
                "The AutoDiag Pro Store listing is not published yet.\n\n"
                "Pro and Workshop upgrades are available as licence keys — "
                "use Install licence key… below.",
            )
            return
        QDesktopServices.openUrl(QUrl(f"ms-windows-store://pdp/?ProductId={product_id}"))


def try_unlock(parent: QWidget, manager: LicenseManager, feature: str) -> bool:
    """True when ``feature`` is allowed; otherwise opens the upgrade dialog.

    Returns True after a successful in-dialog key install so the caller can
    proceed with the originally blocked action.
    """
    if manager.current().allows(feature):
        return True
    dialog = UpgradeDialog(manager, feature, parent)
    dialog.exec()
    return manager.current().allows(feature)


def ensure_eula_accepted(
    parent: QWidget, prefs, dialog_type=SafetyNoticeDialog
) -> bool:
    """Prompt until the current EULA version is accepted (False = declined)."""
    if prefs.eula_version() == EULA_VERSION:
        return True
    dialog = dialog_type(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    prefs.set_eula_version(EULA_VERSION)
    prefs.sync()
    return True
