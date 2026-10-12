"""Single-file PDF rendering of the HTML report (Qt print engine, offline)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtGui import QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from autodiag.services.export import report_to_html


def write_report_pdf(report: dict[str, Any], path: str | Path) -> Path:
    """Render ``report`` to an A4 PDF at ``path`` — same HTML, one source."""
    target = Path(path)
    document = QTextDocument()
    document.setHtml(report_to_html(report))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(target))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    document.print_(printer)  # PySide6 renames print() (Python keyword)
    return target
