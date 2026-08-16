"""The panel of whole sentences.

Shown over the keys rather than above them, and only while it is being used.
That placement is the whole design, and it follows from what a trip across the
board costs: a permanent band of six sentence rows would take a third of the
window from the keys for something wanted a few times a minute, whereas a panel
that opens over them costs nothing at all when it is shut. Open, pick, and it
closes itself -- two presses for a sentence that would otherwise be forty.

The rows are the largest targets on the keyboard, deliberately. They run the
full width, they are half again as tall as a suggestion chip, and they are
ordered so that the likeliest sentence is the top one, nearest the pointer's
resting place after the button that opened the panel. A sentence too long for
its row is elided at the end rather than shrunk, because a row of six-point text
is a row this user cannot read.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme
from .theme import mix as _mix

DWELL_TICK_MS = 25

#: Row height at the default scale, and the bounds it moves between. Taller than
#: a suggestion chip because the target is worth more: a mis-hit on a chip costs
#: one word, a mis-hit here costs a whole sentence typed out or deleted.
DEFAULT_ROW_HEIGHT = 42
MIN_ROW_HEIGHT = 30
MAX_ROW_HEIGHT = 110

TITLE = "Fjalitë e mia — klikoni një fjali"
EMPTY = "Asnjë fjali për këtë fillim. Shkruani një fjali dhe do të kujtohet."


class SentenceRow(QWidget):
    """One whole sentence, selectable by click or by dwelling on it."""

    picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(DEFAULT_ROW_HEIGHT)

        self._text = ""
        self._first = False
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

    def set_text(self, text: str, first: bool = False) -> None:
        if (text, first) != (self._text, self._first):
            self._text, self._first = text, first
            self._timer.stop()
            self._progress = 0.0
            self._done = False
            self.update()

    def text(self) -> str:
        return self._text

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
        if self._dwell_enabled and self._text and not self._done:
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
        if event.button() == Qt.LeftButton and self._text:
            self._pressed = True
            self._timer.stop()
            self._progress = 0.0
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        was_pressed, self._pressed = self._pressed, False
        self.update()
        if was_pressed and self._text:
            self.picked.emit(self._text)

    def _tick(self) -> None:
        self._progress += DWELL_TICK_MS / self._dwell_ms
        if self._progress >= 1.0:
            self._timer.stop()
            self._progress = 0.0
            self._done = True
            self.update()
            if self._text:
                self.picked.emit(self._text)
            return
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = theme.palette()
        radius = min(theme.skin().radius + 1.0, self.height() / 2.0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        if not self._text:
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
        elif self._hover or self._first:
            border = QColor(p.accent)
        else:
            border = QColor(p.chip_border)
        painter.setPen(QPen(border, 1.6 if self._first and not self._hover else 1.0))
        painter.drawPath(path)

        size = max(9.0, min(rect.height() * 0.42, 13.5 * self._font_scale))
        font = theme.key_font(self.font(), size, 600 if self._first else 450)
        painter.setFont(font)
        painter.setPen(QColor(p.on_accent if self._pressed else p.legend))
        # Left-aligned and elided: a sentence is read from its beginning, and a
        # centred one would start in a different place on every row.
        body = rect.adjusted(12, 0, -12, 0)
        text = QFontMetricsF(font).elidedText(self._text, Qt.ElideRight,
                                              body.width())
        painter.drawText(body, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextSingleLine,
                         text)
        painter.end()


class SentencePanel(QWidget):
    """The sheet of whole sentences that opens over the keys."""

    picked = Signal(str)
    closed = Signal()

    def __init__(self, rows: int = 6, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SentencePanel")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoFillBackground(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(2, 0, 0, 0)
        top.setSpacing(6)
        self.title = QLabel(TITLE)
        self.title.setObjectName("SentenceTitle")
        top.addWidget(self.title, 1)

        self.close_button = QPushButton("Mbyll ✕", self)
        self.close_button.setObjectName("SentenceClose")
        self.close_button.setFocusPolicy(Qt.NoFocus)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedHeight(26)
        self.close_button.setMinimumWidth(78)
        self.close_button.clicked.connect(self.closed)
        top.addWidget(self.close_button, 0)
        outer.addLayout(top)

        self._body = QVBoxLayout()
        self._body.setSpacing(5)
        outer.addLayout(self._body, 1)

        self._rows: list[SentenceRow] = []
        self._dwell = (False, 900)
        self._font_scale = 1.0
        self._row_height = DEFAULT_ROW_HEIGHT
        self._count = 0
        #: Rows with a sentence in them; the panel is sized from this.
        self._shown = 0
        self.set_row_count(rows)

    # -- shape -------------------------------------------------------------

    def set_row_count(self, rows: int) -> None:
        if self._rows and rows == self._count:
            return
        self._count = rows
        while self._rows:
            row = self._rows.pop()
            self._body.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        for _index in range(rows):
            row = SentenceRow(self)
            row.picked.connect(self.picked)
            row.configure_dwell(*self._dwell)
            row.set_font_scale(self._font_scale)
            row.setMinimumHeight(self._row_height)
            self._body.addWidget(row, 1)
            self._rows.append(row)
        self.set_sentences([])

    @property
    def capacity(self) -> int:
        return len(self._rows)

    #: Title strip, its spacing and the outer margins -- everything in the
    #: panel that is not a row.
    CHROME = 26 + 5 + 14

    def wanted_height(self) -> int:
        """Height the panel needs, for the rows it actually has something in.

        Sized to its contents rather than to the full row count, so that three
        sentences cover half the keys instead of all of them. The alternative --
        a fixed panel with empty slots in it -- covers keys to display nothing.
        """
        rows = max(1, self._shown)
        return rows * self._row_height + (rows - 1) * 5 + self.CHROME

    def fit_to(self, available: int) -> None:
        """Squeeze the rows into ``available`` pixels if the window is short.

        A docked keyboard on a small screen can be shorter than the rows ask
        for; they shrink rather than spilling past the bottom edge, down to a
        floor below which a row is not worth aiming at anyway.
        """
        rows = max(1, self._shown)
        room = max(0, available - self.CHROME - (rows - 1) * 5)
        per_row = room // rows
        for row in self._rows:
            row.setMinimumHeight(max(MIN_ROW_HEIGHT,
                                     min(self._row_height, per_row)))

    # -- appearance --------------------------------------------------------

    def configure_dwell(self, enabled: bool, ms: int) -> None:
        self._dwell = (enabled, ms)
        for row in self._rows:
            row.configure_dwell(enabled, ms)

    def set_metrics(self, scale: float, row_height: int) -> None:
        self._font_scale = scale
        self._row_height = min(MAX_ROW_HEIGHT, max(MIN_ROW_HEIGHT, row_height))
        for row in self._rows:
            row.set_font_scale(scale)
            row.setMinimumHeight(self._row_height)
        font = self.title.font()
        font.setPointSizeF(max(8.0, 9.0 * min(1.6, scale)))
        self.title.setFont(font)
        self.updateGeometry()

    def restyle(self) -> None:
        p = theme.palette()
        self.title.setStyleSheet(f"color: {p.text_faint}; padding-left: 2px;")
        self.close_button.setStyleSheet(
            f"QPushButton {{ color: {p.text}; background: {p.key_hi};"
            f" border: 1px solid {p.key_border}; border-radius: 6px;"
            f" padding: 2px 10px; }}"
            f"QPushButton:hover {{ background: {p.accent}; color: {p.on_accent};"
            f" border-color: {p.accent}; }}")
        for row in self._rows:
            row.update()

    # -- content -----------------------------------------------------------

    def set_sentences(self, sentences: list[str]) -> None:
        for i, row in enumerate(self._rows):
            row.set_text(sentences[i] if i < len(sentences) else "", first=(i == 0))
            # Hidden rather than left as an empty outline: an empty slot here is
            # a whole line of keys hidden behind nothing.
            row.setVisible(i < len(sentences))
        self._shown = min(len(sentences), len(self._rows))
        self.title.setText(TITLE if sentences else EMPTY)

    def paintEvent(self, event) -> None:
        """A solid sheet, so the keys underneath do not read through it."""
        p = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, theme.skin().window_radius, theme.skin().window_radius)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0.0, QColor(p.window_hi))
        grad.setColorAt(1.0, QColor(p.window_lo))
        painter.fillPath(path, grad)
        painter.setPen(QPen(QColor(p.accent), 1.4))
        painter.drawPath(path)
        painter.end()
