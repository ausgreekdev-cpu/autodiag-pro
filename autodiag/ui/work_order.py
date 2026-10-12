"""Dialog: attach or edit a work order on a saved session."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

#: Report field names, in display order.
FIELDS = ("customer", "phone", "mileage", "job", "notes")


class WorkOrderDialog(QDialog):
    """Customer/job details stored alongside a session's report."""

    def __init__(
        self,
        values: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Work order")
        self.resize(420, 380)

        current = values or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._customer = QLineEdit(current.get("customer", ""))
        self._phone = QLineEdit(current.get("phone", ""))
        self._mileage = QLineEdit(current.get("mileage", ""))
        form.addRow("Customer:", self._customer)
        form.addRow("Phone:", self._phone)
        form.addRow("Mileage:", self._mileage)
        layout.addLayout(form)

        layout.addWidget(QLabel("Job:"))
        self._job = QPlainTextEdit(current.get("job", ""))
        self._job.setPlaceholderText("What was requested…")
        layout.addWidget(self._job, 1)

        layout.addWidget(QLabel("Notes:"))
        self._notes = QPlainTextEdit(current.get("notes", ""))
        self._notes.setPlaceholderText("Findings, parts, follow-ups…")
        layout.addWidget(self._notes, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        """Trimmed field values, keyed by report field name."""
        return {
            "customer": self._customer.text().strip(),
            "phone": self._phone.text().strip(),
            "mileage": self._mileage.text().strip(),
            "job": self._job.toPlainText().strip(),
            "notes": self._notes.toPlainText().strip(),
        }
