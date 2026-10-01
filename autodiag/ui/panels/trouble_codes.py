"""Trouble-code panel: stored / pending / permanent DTCs + clear."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.dictionary import describe
from autodiag.services.worker import ObdWorker

_SOURCES = (("stored", "Stored"), ("pending", "Pending"), ("permanent", "Permanent"))


class TroubleCodesPanel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._connected = False
        self._trees: dict[str, QTreeWidget] = {}

        self._build_ui()
        worker.connected.connect(lambda _info: self._set_connected(True))
        worker.disconnected.connect(lambda _reason: self._set_connected(False))
        worker.dtcs.connect(self.on_dtcs)
        worker.cleared.connect(self.on_cleared)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Trouble codes")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        buttons = QHBoxLayout()
        self._read_btn = QPushButton("Read codes")
        self._read_btn.clicked.connect(self._on_read_clicked)
        buttons.addWidget(self._read_btn)
        self._clear_btn = QPushButton("Clear codes")
        self._clear_btn.setObjectName("danger")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        buttons.addWidget(self._clear_btn)
        buttons.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("subtle")
        buttons.addWidget(self._count_label)
        layout.addLayout(buttons)

        self._hint = QLabel("Connect and press “Read codes” to query the vehicle.")
        self._hint.setObjectName("subtle")
        layout.addWidget(self._hint)

        tabs = QTabWidget()
        for source, label in _SOURCES:
            tree = QTreeWidget()
            tree.setHeaderLabels(["Code", "Description"])
            tree.setAlternatingRowColors(True)
            tree.setRootIsDecorated(False)
            tree.setColumnWidth(0, 110)
            tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            tabs.addTab(tree, label)
            self._trees[source] = tree
        tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(tabs, 1)
        self._tabs = tabs
        self._set_connected(False)

    # -- worker handlers -----------------------------------------------------------

    def on_dtcs(self, source: str, codes: list[str]) -> None:
        tree = self._trees.get(source)
        if tree is None:
            return
        tree.clear()
        for code in codes:
            item = QTreeWidgetItem([code, describe(code) or "Unknown code"])
            tree.addTopLevelItem(item)
        if source == self._current_source():
            self._update_labels()

    def on_cleared(self, ok: bool) -> None:
        if ok:
            self._hint.setText("Codes cleared — the MIL should be off now.")
            if self._connected:
                self._worker.read_dtcs(self._current_source())
        else:
            self._hint.setText("The vehicle did not confirm the reset — try again.")

    # -- interactions ----------------------------------------------------------------

    def _current_source(self) -> str:
        return _SOURCES[self._tabs.currentIndex()][0]

    def _on_tab_changed(self, _index: int) -> None:
        if self._connected:
            self._worker.read_dtcs(self._current_source())
        self._update_labels()

    def _on_read_clicked(self) -> None:
        self._hint.setText("Reading codes…")
        self._worker.read_dtcs(self._current_source())

    def _on_clear_clicked(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear codes",
            "Erase all stored diagnostic codes and turn off the MIL?\n\n"
            "Readiness monitors will reset to “not complete”.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._worker.clear_codes()

    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._read_btn.setEnabled(connected)
        self._clear_btn.setEnabled(connected)

    def _update_labels(self) -> None:
        total = sum(tree.topLevelItemCount() for tree in self._trees.values())
        self._count_label.setText(f"{total} code(s) this session")
