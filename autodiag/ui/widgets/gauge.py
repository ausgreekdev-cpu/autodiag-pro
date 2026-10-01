"""Circular gauge widget (custom-painted, dark theme)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from autodiag.ui import theme

_START_DEG = 225 * 16  # bottom-left
_SWEEP_DEG = -270 * 16  # clockwise 270°


class Gauge(QWidget):
    """Ring gauge with a centered value and a caption.

    ``set_value(None)`` shows an empty ``--`` state (PID not reported yet).
    """

    def __init__(
        self,
        label: str,
        unit: str = "",
        *,
        minimum: float = 0.0,
        maximum: float = 100.0,
        decimals: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._label = label
        self._unit = unit
        self._minimum = minimum
        self._maximum = maximum
        self._decimals = decimals
        self._value: float | None = None
        self.setMinimumSize(150, 140)

    # -- API ------------------------------------------------------------------

    @property
    def value(self) -> float | None:
        return self._value

    def set_value(self, value: float | None) -> None:
        self._value = value
        self.update()

    def set_unit(self, unit: str) -> None:
        self._unit = unit
        self.update()

    def set_range(self, minimum: float, maximum: float) -> None:
        self._minimum = minimum
        self._maximum = maximum
        self.update()

    def _fraction(self) -> float:
        if self._value is None:
            return 0.0
        span = self._maximum - self._minimum
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self._value - self._minimum) / span))

    # -- painting ---------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: ARG002 — Qt signature
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width, height = self.width(), self.height()
        caption_h = max(18, height // 8)
        side = min(width - 8, height - caption_h - 6)
        if side <= 0:
            return

        arc_pen_width = max(6, side // 12)
        ring_rect = self.rect().adjusted(
            (width - side) // 2,
            caption_h,
            -((width - side) // 2),
            -(height - side - caption_h),
        )
        ring_rect.adjust(
            arc_pen_width // 2,
            arc_pen_width // 2,
            -arc_pen_width // 2,
            -arc_pen_width // 2,
        )

        # caption
        painter.setPen(QPen(QColor(theme.MUTED)))
        font = QFont(painter.font())
        font.setPointSizeF(max(8.5, height / 16))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            0, 2, width, caption_h,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
            self._label,
        )

        # track
        track = QPen(QColor(theme.SURFACE2), arc_pen_width)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(ring_rect, _START_DEG, _SWEEP_DEG)

        # value arc
        frac = self._fraction()
        if self._value is not None and frac > 0:
            color = theme.DANGER if frac >= 0.9 else theme.ACCENT
            value_pen = QPen(QColor(color), arc_pen_width)
            value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(value_pen)
            painter.drawArc(ring_rect, _START_DEG, int(_SWEEP_DEG * frac))

        # center value + unit
        painter.setPen(QPen(QColor(theme.TEXT)))
        value_font = QFont(painter.font())
        value_font.setPointSizeF(max(10.0, side / 5.5))
        value_font.setBold(True)
        painter.setFont(value_font)
        text = "--" if self._value is None else f"{self._value:.{self._decimals}f}"
        text_rect = ring_rect.adjusted(0, side // 8, 0, -side // 8)
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text
        )

        if self._unit:
            painter.setPen(QPen(QColor(theme.MUTED)))
            unit_font = QFont(painter.font())
            unit_font.setPointSizeF(max(7.5, height / 18))
            unit_font.setBold(False)
            painter.setFont(unit_font)
            unit_rect = ring_rect.adjusted(0, side // 3, 0, 0)
            painter.drawText(
                unit_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                self._unit,
            )
        painter.end()
