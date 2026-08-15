"""One drawn key.

Painted rather than assembled from widgets, because each key shows two legends
(the base character large in the middle, the shifted one small in the corner,
exactly as Windows does), because dwell selection needs to draw a filling
progress bar underneath the label, and because a key should look like a key --
a soft gradient, a lit top edge and a shadow beneath it -- which no stylesheet
can produce while also reacting to hover, press, latch and dwell.

Three activation routes are supported, and every one of them matters to somebody:

* click -- the ordinary case;
* press-and-hold -- auto-repeat, so deleting a line does not mean 40 clicks;
* dwell -- resting the pointer on the key selects it, for users driving a head
  mouse or eye tracker who cannot click at all.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import QWidget

from ..layouts.albanian import Key
from . import theme

DWELL_TICK_MS = 25
RADIUS = 8.0


_mix = theme.mix   # hover and latch tints; shared with the suggestion chips


class KeyCap(QWidget):
    activated = Signal(object)   # -> Key
    repeated = Signal(object)    # -> Key (auto-repeat firing)

    def __init__(self, key: Key, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_MouseTracking, True)
        self.setCursor(Qt.PointingHandCursor)

        self._hover = False
        self._pressed = False
        self.latched = False   # active for the next keystroke only
        self.locked = False    # active until pressed again

        self._font_scale = 1.0
        # Legends are sized from the grid's unit, not from this key's own
        # rectangle, so that a tall Enter or a wide Space is lettered at the
        # same size as the letter keys instead of ballooning.
        self._unit_w = 0.0
        self._unit_h = 0.0
        self._shift = False
        self._altgr = False

        self._repeat_enabled = True
        self._repeat_delay = 500
        self._repeat_rate = 60
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.timeout.connect(self._start_repeating)
        self._repeat_tick = QTimer(self)
        self._repeat_tick.timeout.connect(self._emit_repeat)

        self._dwell_enabled = False
        self._dwell_ms = 900
        self._dwell_progress = 0.0
        self._dwell_done = False
        self._dwell_timer = QTimer(self)
        self._dwell_timer.timeout.connect(self._dwell_tick)

    # -- configuration -----------------------------------------------------

    def configure(self, *, font_scale: float, dwell: bool, dwell_ms: int,
                  repeat: bool, repeat_delay: int, repeat_rate: int) -> None:
        self._font_scale = font_scale
        self._dwell_enabled = dwell
        self._dwell_ms = max(300, dwell_ms)
        self._repeat_enabled = repeat
        self._repeat_delay = repeat_delay
        self._repeat_rate = repeat_rate
        if not dwell:
            self._cancel_dwell()
        self.update()

    def set_unit_size(self, unit_w: float, unit_h: float) -> None:
        self._unit_w, self._unit_h = unit_w, unit_h

    def set_modifier_state(self, shift: bool, altgr: bool) -> None:
        if (shift, altgr) != (self._shift, self._altgr):
            self._shift, self._altgr = shift, altgr
            self.update()

    def set_latched(self, latched: bool, locked: bool = False) -> None:
        if (latched, locked) != (self.latched, self.locked):
            self.latched, self.locked = latched, locked
            self.update()

    # -- mouse -------------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hover = True
        if self._dwell_enabled and not self._dwell_done:
            self._dwell_progress = 0.0
            self._dwell_timer.start(DWELL_TICK_MS)
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self._cancel_dwell()
        self._stop_repeat()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._pressed = True
        self._cancel_dwell()
        self.update()
        self.activated.emit(self.key)
        if self._repeat_enabled and self.key.repeatable:
            self._repeat_timer.start(self._repeat_delay)

    def mouseReleaseEvent(self, event) -> None:
        self._pressed = False
        self._stop_repeat()
        self.update()

    def _start_repeating(self) -> None:
        if self._pressed:
            self._repeat_tick.start(self._repeat_rate)

    def _emit_repeat(self) -> None:
        if self._pressed:
            self.repeated.emit(self.key)
        else:
            self._stop_repeat()

    def _stop_repeat(self) -> None:
        self._repeat_timer.stop()
        self._repeat_tick.stop()

    # -- dwell -------------------------------------------------------------

    def _dwell_tick(self) -> None:
        self._dwell_progress += DWELL_TICK_MS / self._dwell_ms
        if self._dwell_progress >= 1.0:
            self._dwell_timer.stop()
            self._dwell_progress = 0.0
            # Latch until the pointer leaves, so resting on a key does not fire
            # it over and over.
            self._dwell_done = True
            self.activated.emit(self.key)
        self.update()

    def _cancel_dwell(self) -> None:
        self._dwell_timer.stop()
        self._dwell_progress = 0.0
        if not self._hover:
            self._dwell_done = False

    # -- painting ----------------------------------------------------------

    def _gradient(self, rect: QRectF) -> QLinearGradient:
        p = theme.palette()
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if self._pressed:
            grad.setColorAt(0.0, QColor(p.accent))
            grad.setColorAt(1.0, QColor(p.accent_deep))
        elif self.locked:
            grad.setColorAt(0.0, QColor(p.accent))
            grad.setColorAt(1.0, QColor(p.accent_deep))
        elif self.latched:
            grad.setColorAt(0.0, _mix(p.key_hi, p.accent, 0.55))
            grad.setColorAt(1.0, _mix(p.key_lo, p.accent_deep, 0.55))
        elif self.key.role == "system":
            hi, lo = p.system_hi, p.system_lo
            if self._hover:
                hi, lo = _mix(hi, p.accent, 0.22).name(), _mix(lo, p.accent, 0.22).name()
            grad.setColorAt(0.0, QColor(hi))
            grad.setColorAt(1.0, QColor(lo))
        else:
            hi, lo = p.key_hi, p.key_lo
            if self._hover:
                hi, lo = _mix(hi, p.accent, 0.28).name(), _mix(lo, p.accent, 0.28).name()
            grad.setColorAt(0.0, QColor(hi))
            grad.setColorAt(1.0, QColor(lo))
        return grad

    def _text_colour(self) -> QColor:
        p = theme.palette()
        if self._pressed or self.locked:
            return QColor(p.on_accent)
        return QColor(p.text)

    def paintEvent(self, event) -> None:
        p = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -2.0)
        if self._pressed:
            # A pressed key sinks: the shadow disappears and the cap moves down
            # into the space it occupied.
            rect.translate(0, 1.0)

        if not self._pressed:
            shadow = QColor(p.shadow)
            shadow.setAlpha(70 if p.name == "dark" else 40)
            shadow_path = QPainterPath()
            shadow_path.addRoundedRect(rect.translated(0, 1.5), RADIUS, RADIUS)
            painter.fillPath(shadow_path, shadow)

        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        painter.fillPath(path, self._gradient(rect))

        if self._dwell_progress > 0:
            self._paint_dwell(painter, rect)

        border = QColor(p.accent) if self._hover and not self._pressed \
            else QColor(p.key_border)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)

        # A one-pixel lit line just inside the top edge; this is what makes the
        # key read as raised rather than as a coloured rectangle.
        if not self._pressed:
            edge = QColor(p.key_edge)
            edge.setAlpha(150 if p.name == "dark" else 220)
            painter.setPen(QPen(edge, 1.0))
            painter.drawLine(QPointF(rect.left() + RADIUS * 0.7, rect.top() + 1.0),
                             QPointF(rect.right() - RADIUS * 0.7, rect.top() + 1.0))

        ref_h = self._unit_h or rect.height()
        ref_w = self._unit_w or rect.width()
        base_size = max(9.0, min(ref_h * 0.32, ref_w * 0.40)) * self._font_scale

        if self.key.is_char:
            self._paint_char_key(painter, rect, base_size)
        else:
            self._paint_label(painter, rect, base_size)

        if self.locked:
            self._paint_lock_dot(painter, rect)
        painter.end()

    def _paint_dwell(self, painter: QPainter, rect: QRectF) -> None:
        p = theme.palette()
        fill = QRectF(rect)
        fill.setHeight(rect.height() * self._dwell_progress)
        fill.moveBottom(rect.bottom())
        clip = QPainterPath()
        clip.addRoundedRect(rect, RADIUS, RADIUS)
        painter.save()
        painter.setClipPath(clip)
        colour = QColor(p.accent)
        colour.setAlpha(120)
        painter.fillRect(fill, colour)
        # A bright line at the top of the fill: with a head pointer the edge is
        # far easier to track than the shaded area behind it.
        painter.setPen(QPen(QColor(p.accent), 2.0))
        painter.drawLine(QPointF(fill.left(), fill.top()),
                         QPointF(fill.right(), fill.top()))
        painter.restore()

    def _paint_label(self, painter: QPainter, rect: QRectF, base_size: float) -> None:
        label = self.key.label
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, base_size * (0.58 if len(label) > 3 else 0.80)))
        font.setWeight(QFont.DemiBold if len(label) <= 3 else QFont.Medium)
        # Shrink a word that will not fit rather than let it run off the key.
        # "Options" and "PrtScn" are narrow keys with long names, and at a large
        # font scale -- which is exactly what a user with low vision selects --
        # the clipped remainder is unreadable.
        available = rect.width() - 8
        metrics = QFontMetricsF(font)
        while (metrics.horizontalAdvance(label) > available
               and font.pointSizeF() > 6.0):
            font.setPointSizeF(font.pointSizeF() - 0.5)
            metrics = QFontMetricsF(font)
        painter.setFont(font)
        painter.setPen(self._text_colour() if self._pressed or self.locked
                       else QColor(theme.palette().text_dim))
        painter.drawText(rect, Qt.AlignCenter | Qt.TextSingleLine, label)

    def _paint_char_key(self, painter: QPainter, rect: QRectF,
                        base_size: float) -> None:
        base = self.key.caption(self._shift, self._altgr)
        secondary = ""
        if self.key.shift and self.key.shift != base:
            secondary = self.key.shift
        if self._altgr and self.key.altgr:
            secondary = self.key.base

        font = QFont(self.font())
        font.setPointSizeF(max(8.0, base_size))
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(self._text_colour())
        # Letters centre; keys carrying a second legend sit low, mirroring the
        # Windows keyboard where the shifted glyph occupies the top-left.
        target = rect if not secondary else rect.adjusted(0, rect.height() * 0.20, 0, 0)
        painter.drawText(target, Qt.AlignCenter | Qt.TextSingleLine, base)

        if secondary:
            small = QFont(self.font())
            small.setPointSizeF(max(7.0, base_size * 0.60))
            painter.setFont(small)
            colour = self._text_colour()
            colour.setAlpha(165)
            painter.setPen(colour)
            painter.drawText(rect.adjusted(7, 4, -5, 0),
                             Qt.AlignLeft | Qt.AlignTop | Qt.TextSingleLine, secondary)

    def _paint_lock_dot(self, painter: QPainter, rect: QRectF) -> None:
        """A locked modifier gets a dot, so latched and locked are told apart."""
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.palette().on_accent))
        r = 2.5
        painter.drawEllipse(QPointF(rect.right() - 8, rect.top() + 8), r, r)
