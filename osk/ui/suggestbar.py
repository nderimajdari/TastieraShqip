"""The predicted words shown above the keyboard.

Laid out as a grid of one to three rows. More rows is not merely more choice: a
trigram model is confident about its first two or three guesses and much less so
after that, so a second and third row is where the words a slow typist actually
wanted tend to appear. Against that, every extra row is screen space taken from
the document and a longer visual search, which is why the shape is left to the
user rather than fixed here.

The chips are deliberately large and evenly sized: for someone with limited
pointer control, a suggestion that is hard to hit is a suggestion that costs more
than typing the word out. They carry the same dwell behaviour as the keys, so a
dwell user can accept a prediction without clicking.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .theme import mix as _mix

DWELL_TICK_MS = 25
RADIUS = 9.0


class SuggestionChip(QWidget):
    """One suggested word, selectable by click or by dwelling on it."""

    picked = Signal(str)

    def __init__(self, primary: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(30)

        self._word = ""
        self._primary = primary   # the model's best guess, marked out
        self._hover = False
        self._pressed = False
        self._font_scale = 1.0

        self._dwell_enabled = False
        self._dwell_ms = 900
        self._progress = 0.0
        self._done = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # -- state -------------------------------------------------------------

    def set_word(self, word: str) -> None:
        if word != self._word:
            self._word = word
            self._timer.stop()
            self._progress = 0.0
            self._done = False
            self.update()

    def word(self) -> str:
        return self._word

    def set_primary(self, primary: bool) -> None:
        if primary != self._primary:
            self._primary = primary
            self.update()

    def set_font_scale(self, scale: float) -> None:
        self._font_scale = scale
        self.update()

    def configure_dwell(self, enabled: bool, ms: int) -> None:
        self._dwell_enabled = enabled
        self._dwell_ms = max(300, ms)
        if not enabled:
            self._timer.stop()
            self._progress = 0.0
            self.update()

    # -- interaction -------------------------------------------------------

    def enterEvent(self, event) -> None:
        self._hover = True
        if self._dwell_enabled and self._word and not self._done:
            self._progress = 0.0
            self._timer.start(DWELL_TICK_MS)
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._pressed = False
        self._timer.stop()
        self._progress = 0.0
        self._done = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._word:
            self._pressed = True
            self._timer.stop()
            self._progress = 0.0
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        was_pressed, self._pressed = self._pressed, False
        self.update()
        if was_pressed and self._word:
            self.picked.emit(self._word)

    def _tick(self) -> None:
        self._progress += DWELL_TICK_MS / self._dwell_ms
        if self._progress >= 1.0:
            self._timer.stop()
            self._progress = 0.0
            self._done = True
            self.update()
            if self._word:
                self.picked.emit(self._word)
            return
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)

        if not self._word:
            # An empty slot stays as a faint outline rather than vanishing, so
            # the rows keep their shape and the buttons never move under a
            # pointer that is already on its way to one.
            faint = QColor(p.divider)
            faint.setAlpha(60)
            painter.setPen(QPen(faint, 1.0, Qt.DashLine))
            painter.drawPath(path)
            painter.end()
            return

        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if self._pressed:
            grad.setColorAt(0.0, QColor(p.accent))
            grad.setColorAt(1.0, QColor(p.accent_deep))
        elif self._hover:
            grad.setColorAt(0.0, _mix(p.chip_hi, p.accent, 0.30))
            grad.setColorAt(1.0, _mix(p.chip_lo, p.accent, 0.30))
        else:
            grad.setColorAt(0.0, QColor(p.chip_hi))
            grad.setColorAt(1.0, QColor(p.chip_lo))
        painter.fillPath(path, grad)

        if self._progress > 0:
            fill = QRectF(rect)
            fill.setWidth(rect.width() * min(1.0, self._progress))
            painter.save()
            painter.setClipPath(path)
            colour = QColor(p.accent)
            colour.setAlpha(120)
            painter.fillRect(fill, colour)
            painter.setPen(QPen(QColor(p.accent), 2.0))
            painter.drawLine(QPointF(fill.right(), rect.top()),
                             QPointF(fill.right(), rect.bottom()))
            painter.restore()

        if self._pressed:
            border = QColor(p.accent_deep)
        elif self._hover or self._primary:
            border = QColor(p.accent)
        else:
            border = QColor(p.chip_border)
        painter.setPen(QPen(border, 1.6 if self._primary and not self._hover else 1.0))
        painter.drawPath(path)

        font = QFont(self.font())
        font.setPointSizeF(max(8.5, min(rect.height() * 0.42, 15.0) * self._font_scale))
        font.setWeight(QFont.DemiBold if self._primary else QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(p.on_accent if self._pressed else p.text))
        painter.drawText(rect.adjusted(6, 0, -6, 0),
                         Qt.AlignCenter | Qt.TextSingleLine, self._word)
        painter.end()


class SuggestionBar(QWidget):
    """Shows predictions in a grid and reports which one the user picked."""

    picked = Signal(str)

    def __init__(self, per_row: int = 7, rows: int = 2,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SuggestionBar")
        self.setFocusPolicy(Qt.NoFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 0, 2, 0)
        outer.setSpacing(3)

        self.context_label = QLabel("")
        self.context_label.setObjectName("ContextLabel")
        self.context_label.setTextFormat(Qt.PlainText)
        self.context_label.setFixedHeight(15)
        outer.addWidget(self.context_label)

        # Only ever shown when something is wrong -- a missing or unreadable
        # language model, which would otherwise look like the prediction simply
        # not working.
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        outer.addWidget(self.status_label)

        self._grid = QGridLayout()
        self._grid.setSpacing(5)
        outer.addLayout(self._grid, 1)

        self._chips: list[SuggestionChip] = []
        self._per_row = per_row
        self._rows = rows
        self._dwell = (False, 900)
        self._font_scale = 1.0
        self.set_shape(per_row, rows)

    # -- shape -------------------------------------------------------------

    def set_shape(self, per_row: int, rows: int) -> None:
        if self._chips and (per_row, rows) == (self._per_row, self._rows):
            return
        self._per_row, self._rows = per_row, rows
        while self._chips:
            chip = self._chips.pop()
            self._grid.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        for index in range(per_row * rows):
            chip = SuggestionChip(primary=(index == 0), parent=self)
            chip.picked.connect(self.picked)
            chip.configure_dwell(*self._dwell)
            chip.set_font_scale(self._font_scale)
            self._grid.addWidget(chip, index // per_row, index % per_row)
            self._chips.append(chip)
        for column in range(per_row):
            self._grid.setColumnStretch(column, 1)
        self.set_suggestions([])

    @property
    def capacity(self) -> int:
        return len(self._chips)

    # -- appearance --------------------------------------------------------

    def configure_dwell(self, enabled: bool, ms: int) -> None:
        self._dwell = (enabled, ms)
        for chip in self._chips:
            chip.configure_dwell(enabled, ms)

    def set_font_scale(self, scale: float) -> None:
        self._font_scale = scale
        for chip in self._chips:
            chip.set_font_scale(scale)
        font = self.context_label.font()
        font.setPointSizeF(max(7.0, 8.5 * scale))
        self.context_label.setFont(font)
        self.context_label.setFixedHeight(round(15 * min(1.6, scale)))

    def restyle(self) -> None:
        p = theme.palette()
        self.context_label.setStyleSheet(
            f"color: {p.text_faint}; padding-left: 4px;")
        self.status_label.setStyleSheet(f"color: #e0a33c; padding-left: 4px;")
        for chip in self._chips:
            chip.update()

    # -- content -----------------------------------------------------------

    def set_suggestions(self, words: list[str]) -> None:
        for i, chip in enumerate(self._chips):
            chip.set_word(words[i] if i < len(words) else "")

    def set_context(self, text: str) -> None:
        # Show the tail of what has been typed, so the user can see the context
        # the prediction is working from.
        self.context_label.setText(text[-110:] if text else "")

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
