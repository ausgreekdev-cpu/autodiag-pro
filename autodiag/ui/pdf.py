"""Paginated PDF rendering of the HTML report (Qt print engine, offline).

`QTextDocument` implements a CSS2 subset: flexbox is ignored and it has no notion of
running headers, so the PDF is laid out here — the document is laid out in 96 dpi units
(the units its fonts are measured in), painted onto the page through a scale factor, and
the furniture (VIN, date, page numbers) is drawn in the margins of every page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPageLayout,
    QPageSize,
    QPainter,
    QPen,
    QTextDocument,
)
from PySide6.QtPrintSupport import QPrinter

from autodiag.services.export import _display_time, report_to_html

_PAGE_MARGIN_MM = 14.0
#: Height reserved above and below the body for the running header/footer.
_FURNITURE_MM = 9.0
#: QTextDocument lays text out in 96 dpi units whatever the printer resolution is.
_LAYOUT_DPI = 96.0
_RULE = "#d1d5db"
_INK = "#6b7280"
_FURNITURE_PX = 11  # ≈ 8 pt once the page is scaled to the printer


def page_furniture(report: dict[str, Any], page: int, pages: int) -> dict[str, str]:
    """Text for the running header and footer of one printed page."""
    vehicle = report.get("vehicle") or {}
    vin = vehicle.get("vin") or "no VIN"
    when = _display_time(report.get("generated_at"))
    version = (report.get("app") or {}).get("version", "")
    return {
        "header_left": f"AutoDiag Pro report — v{version}",
        "header_right": f"VIN {vin} · {when}",
        "footer_left": f"Vehicle diagnostic report · {vin} · {when}",
        "footer_right": f"Page {page} of {pages}",
    }


def write_report_pdf(report: dict[str, Any], path: str | Path) -> Path:
    """Render ``report`` to an A4 PDF at ``path`` — same HTML, one source."""
    target = Path(path)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(target))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageMargins(
        QMarginsF(_PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM, _PAGE_MARGIN_MM),
        QPageLayout.Unit.Millimeter,
    )

    dpi = float(printer.resolution() or 300)
    #: Device pixels per layout unit, i.e. how far the painter is scaled when drawing.
    scale = dpi / _LAYOUT_DPI
    page = QRectF(printer.pageLayout().paintRectPixels(int(dpi)))
    paint = QRectF(
        page.x() / scale, page.y() / scale, page.width() / scale, page.height() / scale
    )
    band = _FURNITURE_MM * _LAYOUT_DPI / 25.4
    content = QSizeF(paint.width(), paint.height() - 2 * band)

    document = QTextDocument()
    document.setDocumentMargin(0.0)
    document.setHtml(report_to_html(report, for_print=True))
    document.setPageSize(content)

    painter = QPainter()
    if not painter.begin(printer):
        raise OSError(f"cannot write PDF to {target}")
    try:
        pages = max(1, document.pageCount())
        painter.scale(scale, scale)
        font = QFont()
        font.setPixelSize(_FURNITURE_PX)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        for index in range(pages):
            if index:
                printer.newPage()
            painter.save()
            painter.translate(paint.x(), paint.y() + band)
            document.drawContents(
                painter,
                QRectF(0.0, index * content.height(), content.width(), content.height()),
            )
            painter.restore()
            _draw_furniture(
                painter,
                paint,
                band,
                page_furniture(report, index + 1, pages),
                metrics,
            )
    finally:
        painter.end()
    return target


def _draw_furniture(
    painter: QPainter,
    paint: QRectF,
    band: float,
    text: dict[str, str],
    metrics: QFontMetricsF,
) -> None:
    """Paint the header and footer of one page inside its reserved bands."""
    rule = QPen(QColor(_RULE))
    rule.setWidthF(0.75)
    ink = QColor(_INK)
    line = metrics.height()
    gap = 2.0

    header_top = paint.y() + 0.5
    rule_y = header_top + line + gap
    _pair(
        painter,
        paint.x(),
        header_top,
        paint.width(),
        text["header_left"],
        text["header_right"],
        metrics,
        ink,
    )
    painter.setPen(rule)
    painter.drawLine(QPointF(paint.x(), rule_y), QPointF(paint.right(), rule_y))

    footer_rule_y = paint.bottom() - band + gap
    painter.setPen(rule)
    painter.drawLine(QPointF(paint.x(), footer_rule_y), QPointF(paint.right(), footer_rule_y))
    _pair(
        painter,
        paint.x(),
        footer_rule_y + 2.0,
        paint.width(),
        text["footer_left"],
        text["footer_right"],
        metrics,
        ink,
    )


def _pair(
    painter: QPainter,
    x: float,
    y: float,
    width: float,
    left: str,
    right: str,
    metrics: QFontMetricsF,
    ink: QColor,
) -> None:
    """Left- and right-aligned text on one line, each elided to the space it has."""
    gap = width * 0.03
    tail = metrics.elidedText(right, Qt.TextElideMode.ElideRight, width * 0.55)
    tail_width = metrics.horizontalAdvance(tail)
    head = metrics.elidedText(left, Qt.TextElideMode.ElideRight, width - tail_width - gap)
    painter.setPen(ink)
    painter.drawText(QPointF(x, y + metrics.ascent()), head)
    if tail:
        painter.drawText(QPointF(x + width - tail_width, y + metrics.ascent()), tail)
