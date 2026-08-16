"""The keyboard window itself.

Everything here is arranged around one constraint: the window must never take
focus. It is frameless (a native title bar would activate the window when
dragged), it carries WS_EX_NOACTIVATE, and it re-asserts its topmost position
whenever the foreground application changes rather than by grabbing focus back.

Being frameless means the window manager will not move or resize it for us, so
both are implemented here: a drag strip along the top, and an invisible band
around the edge that resizes. That band is also why the layout keeps a margin --
it is the only part of the window no child widget covers, so it is the only part
that still receives the mouse.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..config import Settings, save_settings
from ..controller import KeyController
from ..layouts import albanian
from ..layouts.albanian import Key
from ..prediction.engine import PredictionEngine
from ..winapi import focus
from ..winapi.hooks import OutsideClickWatcher
from . import theme
from .backlight import Backlight
from .keypanel import UnitGrid
from .sentencebar import SentencePanel
from .suggestbar import SuggestionBar, band_height

FOCUS_POLL_MS = 350
MOVE_STEP_PX = 60

#: Space kept clear around the drawn card. It holds the shadow and, more
#: importantly, it is the resize band: no child widget covers it, so it is the
#: only region where the window itself still sees the mouse.
MARGIN = 9
MIN_WIDTH = 560
MIN_HEIGHT = 230
#: How far the pointer must travel before a press counts as a drag.
DRAG_THRESHOLD = 12

HINT_TEXT = "Tërhiqe për ta lëvizur"

#: The backlight wave, for skins that have one. Ten frames a second, which
#: sounds far too few until you notice that nothing on the keyboard actually
#: moves: only the colour changes, by about three degrees of hue a frame, and
#: colour steps that small cannot be seen. A twelve-second cycle at ten frames
#: a second therefore looks perfectly smooth and costs a fraction of what
#: twenty would -- and this is a keyboard that sits on screen all day, so what
#: it costs while nobody is typing is the number that matters.
GLOW_FRAME_MS = 100
GLOW_STEP = 0.0092


class DragBar(QWidget):
    """The strip along the top of the window that moves it."""

    drag_started = Signal(QPoint)
    drag_moved = Signal(QPoint)
    drag_finished = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedHeight(30)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self.drag_started.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self.drag_moved.emit(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        self.setCursor(Qt.OpenHandCursor)
        self.drag_finished.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()


class KeyboardWindow(QWidget):
    closed = Signal()

    def __init__(self, settings: Settings, engine: PredictionEngine,
                 controller: KeyController) -> None:
        super().__init__()
        self.settings = settings
        self.engine = engine
        self.controller = controller
        self._faded = False
        self._fn_active = False
        self._move_origin: QPoint | None = None
        self._press_global: QPoint | None = None
        self._resize_edges = ""
        self._resize_from: QPoint | None = None
        self._resize_geometry = None
        self._last_foreground = 0
        self._styled = False
        self.glow = Backlight()
        self._card: QPixmap | None = None   # the drawn window background
        # Built before the UI, because applying the settings starts it.
        self._glow_timer = QTimer(self)
        self._glow_timer.timeout.connect(self._advance_glow)

        self.setObjectName("Root")
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_MouseTracking, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        self._build_ui()
        self._connect()
        self.apply_settings()

        self._focus_timer = QTimer(self)
        self._focus_timer.timeout.connect(self._poll_foreground)
        self._focus_timer.start(FOCUS_POLL_MS)

        # A click anywhere but on the keyboard may have moved the caret, which
        # invalidates the context the predictions are built from.
        self._click_watcher = OutsideClickWatcher(
            lambda: int(self.winId()), self._on_outside_click)
        self._click_watcher.install()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(MARGIN + 5, MARGIN, MARGIN + 5, MARGIN + 4)
        root.setSpacing(5)

        root.addWidget(self._build_header())

        self.suggestions = SuggestionBar(self.settings.suggestion_count,
                                         self.settings.suggestion_rows, self)
        root.addWidget(self.suggestions, 0)

        body = QHBoxLayout()
        body.setSpacing(7)
        self.main_grid = UnitGrid(albanian.ROWS, albanian.MAIN_WIDTH_UNITS,
                                  albanian.ROW_COUNT, self)
        self.nav_grid = UnitGrid(albanian.NAV_ROWS, albanian.NAV_WIDTH_UNITS,
                                 albanian.ROW_COUNT, self)
        body.addWidget(self.main_grid, int(albanian.MAIN_WIDTH_UNITS))
        body.addWidget(self.nav_grid, int(albanian.NAV_WIDTH_UNITS))
        root.addLayout(body, 1)
        self._body_layout = body

        # A sheet over the keys rather than a band above them: six sentence rows
        # would otherwise take a third of the window permanently, for something
        # wanted a few times a minute. Not in the layout at all -- it is placed
        # over the key area by hand when it opens, and costs nothing when shut.
        self.sentence_panel = SentencePanel(self.settings.sentence_count, self)
        self.sentence_panel.hide()

        # The backlight is one layer rather than something each key draws, and
        # it lives in its own widget so that a frame of the wave repaints only
        # the gaps between the keys; see backlight.py.
        self._glow_sources = [self.suggestions.lit_rects,
                              self.main_grid.lit_rects,
                              self.nav_grid.lit_rects]


    def _build_header(self) -> QWidget:
        self.header = DragBar(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(2, 0, 0, 0)
        header.setSpacing(7)

        self.badge = QLabel("SQ")
        self.badge.setObjectName("Badge")
        self.badge.setAlignment(Qt.AlignCenter)
        header.addWidget(self.badge)

        self.title_label = QLabel(APP_NAME)
        self.title_label.setObjectName("Title")
        header.addWidget(self.title_label)

        self.hint_label = QLabel(HINT_TEXT)
        self.hint_label.setObjectName("Hint")
        header.addWidget(self.hint_label)
        header.addStretch(1)

        # The window is a tool window and so has no taskbar button; hiding to the
        # tray is the only way back, which the tray icon provides.
        #
        # Icons come from Segoe MDL2 Assets, the icon font Windows itself draws
        # its title bars with, so they match the rest of the desktop. Where it is
        # missing the buttons fall back to letters rather than to the empty boxes
        # an unsupported glyph would leave behind.
        icons = QFontDatabase.families()
        glyphs = "Segoe MDL2 Assets" in icons
        icon_font = QFont("Segoe MDL2 Assets", 9) if glyphs else QFont()

        self._header_buttons = []
        for glyph, text, slot, tip, name in (
            ("", "▣", self._toggle_dock,
             "Fikso në fund të ekranit / lironi", "WinBtn"),
            ("", "◐", self._toggle_fade, "Zbeh tastierën", "WinBtn"),
            ("", "☀", self._toggle_theme,
             "Ndërro pamjen e errët / të çelët", "WinBtn"),
            ("", "◈", self._cycle_skin,
             "Ndërro dizajnin e tastierës", "WinBtn"),
            ("", "⚙", self.open_options, "Opsionet", "WinBtn"),
            ("", "—", self.hide,
             "Fshih (kthehu nga ikona pranë orës)", "WinBtn"),
            ("", "✕", self._request_close, "Mbyll", "CloseBtn"),
        ):
            btn = QPushButton(glyph if glyphs else text, self.header)
            btn.setObjectName(name)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedSize(30, 24)
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            if glyphs:
                btn.setFont(icon_font)
            btn.clicked.connect(slot)
            header.addWidget(btn)
            self._header_buttons.append(btn)
        return self.header

    def _connect(self) -> None:
        for grid in (self.main_grid, self.nav_grid):
            grid.activated.connect(self._on_key)
            grid.repeated.connect(self._on_key)
        self.suggestions.picked.connect(self._on_suggestion)
        self.suggestions.zoom_requested.connect(self._zoom_suggestions)
        self.suggestions.sentences_requested.connect(self.toggle_sentences)
        self.sentence_panel.picked.connect(self._on_sentence)
        self.sentence_panel.closed.connect(self.hide_sentences)
        self.controller.context_changed.connect(self.refresh_suggestions)
        self.controller.modifiers_changed.connect(self._sync_modifiers)
        self.controller.system_action.connect(self._on_system_action)
        self.header.drag_started.connect(self._begin_move)
        self.header.drag_moved.connect(self._continue_move)
        self.header.drag_finished.connect(self._end_move)
        self.header.double_clicked.connect(self._toggle_dock)

    # -- settings ----------------------------------------------------------

    def apply_settings(self) -> None:
        s = self.settings.clamp()
        theme.set_theme(s.theme, s.accent, s.skin)
        theme.set_animating(s.rgb_animation)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet())
        self._restyle()

        style = dict(
            font_scale=s.key_font_scale,
            dwell=s.dwell_enabled,
            dwell_ms=s.dwell_ms,
            repeat=s.hold_to_repeat,
            repeat_delay=s.repeat_delay_ms,
            repeat_rate=s.repeat_rate_ms,
        )
        self.main_grid.apply_style(**style)
        self.nav_grid.apply_style(**style)

        self.suggestions.set_shape(s.suggestion_count, s.suggestion_rows)
        self.suggestions.configure_dwell(s.dwell_enabled, s.dwell_ms)
        self.suggestions.set_metrics(s.suggestion_font_scale, s.suggestion_height)
        self.suggestions.setVisible(s.prediction_enabled)
        self.suggestions.sentences_button.setVisible(s.sentence_suggestions)
        self.nav_grid.setVisible(s.nav_visible)

        self.sentence_panel.set_row_count(s.sentence_count)
        self.sentence_panel.configure_dwell(s.dwell_enabled, s.dwell_ms)
        # Sized from the suggestion scale, plus a half again: the rows are the
        # biggest targets on the board and the sentences on them are the longest
        # text, so what suits a one-word chip is too small here.
        self.sentence_panel.set_metrics(s.suggestion_font_scale,
                                        int(s.suggestion_height * 1.25))
        self.sentence_panel.restyle()
        if not s.sentence_suggestions:
            self.hide_sentences()
        elif self.sentence_panel.isVisible():
            self._place_sentence_panel()

        self.engine.auto_space = s.auto_space
        self.engine.learn = s.learn_from_typing
        self.engine.phrases = s.phrase_suggestions
        self.engine.learn_sentences = (s.learn_from_typing
                                       and s.sentence_suggestions)
        self.controller.auto_capitals = s.auto_capitals
        self.controller.auto_punctuation = s.auto_punctuation

        self.setWindowOpacity(s.faded_opacity if self._faded else s.opacity)
        self._sync_glow_timer()
        self._apply_geometry()
        # Key spacing, corner radius and the number of suggestion rows all move
        # the keys about, and the light is traced from where they ended up.
        self._refresh_glow_shape()
        self.refresh_suggestions()
        self.update()

    # -- backlighting ------------------------------------------------------

    def _sync_glow_timer(self) -> None:
        """Run the wave only when there is one, and only when it can be seen.

        A hidden or docked-away keyboard repainting seventy keys twenty times a
        second would be spending a laptop's battery on a picture nobody is
        looking at.
        """
        wanted = theme.animating() and self.isVisible()
        if wanted and not self._glow_timer.isActive():
            self._glow_timer.start(GLOW_FRAME_MS)
        elif not wanted and self._glow_timer.isActive():
            self._glow_timer.stop()

    def _advance_glow(self) -> None:
        theme.advance(GLOW_STEP)
        # Only the gaps between the keys are damaged, so not one of the
        # eighty-three keycaps is dragged into the frame.
        self.update(self.glow.region)

    def _refresh_glow_shape(self) -> None:
        """The keys have moved, so the light has to be traced over them again."""
        if not hasattr(self, "_glow_sources"):
            return
        grid = self.main_grid
        unit = (grid.width() / grid.width_units if grid.width() else 60.0,
                grid.height() / grid.row_count if grid.height() else 55.0)
        inside = self.rect().adjusted(MARGIN + 1, MARGIN + 1,
                                      -MARGIN - 1, -MARGIN - 1)
        self.glow.rebuild(self.size(), self._glow_sources, unit, inside)
        self._card = None
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_glow_shape()
        if self.sentence_panel.isVisible():
            self._place_sentence_panel()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.hide_sentences()
        self._sync_glow_timer()

    def _restyle(self) -> None:
        p = theme.palette()
        self.title_label.setStyleSheet(f"color: {p.text}; font-weight: 600;")
        self.hint_label.setStyleSheet(f"color: {p.text_faint};")
        self.badge.setStyleSheet(
            f"color: {p.on_accent}; background: {p.accent};"
            f" border-radius: 6px; padding: 1px 6px; font-weight: 700;")
        self.suggestions.restyle()
        for cap in self.main_grid.all_caps() + self.nav_grid.all_caps():
            cap.update()

    def _suggestion_band(self) -> int:
        """Vertical space the prediction rows want, in pixels."""
        if not self.settings.prediction_enabled:
            return 0
        return band_height(self.settings.suggestion_rows,
                           self.settings.suggestion_height)

    def _apply_geometry(self) -> None:
        s = self.settings
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        # The key grid needs its own height whatever the suggestions take, so the
        # window grows with the number of prediction rows instead of squeezing
        # the keys until they are too small to hit.
        floor = MIN_HEIGHT + self._suggestion_band()
        if s.docked:
            height = min(max(floor, s.height), area.height() * 2 // 3)
            self.setGeometry(area.x(), area.bottom() - height + 1, area.width(), height)
        else:
            width = min(max(MIN_WIDTH, s.width), area.width())
            height = min(max(floor, s.height), area.height())
            x = s.x if s.x >= 0 else area.x() + (area.width() - width) // 2
            y = s.y if s.y >= 0 else area.bottom() - height - 40
            # Never leave the window somewhere it cannot be reached, which is
            # what happens when a screen is unplugged between sessions.
            x = min(max(area.x() - MARGIN, x), area.right() - 120)
            y = min(max(area.y() - MARGIN, y), area.bottom() - 60)
            self.setGeometry(x, y, width, height)

    def _remember_geometry(self) -> None:
        geo = self.geometry()
        if not self.settings.docked:
            self.settings.x, self.settings.y = geo.x(), geo.y()
            self.settings.width = geo.width()
        self.settings.height = geo.height()
        save_settings(self.settings)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        # The card behind everything is redrawn only when it changes. It costs
        # a dozen antialiased rounded rectangles across the whole window, and
        # with the backlight running that bill would arrive ten times a second
        # for a picture that had not changed at all.
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._card_pixmap())
        # The light sits on the board, under the keys: they are their own
        # widgets and are painted after this.
        self.glow.paint(painter)
        painter.end()

    def _card_pixmap(self) -> QPixmap:
        """The drawn background, built on demand.

        The glow layer declares itself opaque and paints this underneath the
        light, so it must never be handed a missing background: that is torn
        pixels on screen rather than a blank one.
        """
        if self._card is None or self._card.size() != self._card_size():
            self._card = self._render_card()
        return self._card

    def _card_size(self):
        ratio = self.devicePixelRatioF()
        return QSize(round(self.width() * ratio), round(self.height() * ratio))

    def _render_card(self) -> QPixmap:
        p = theme.palette()
        radius = theme.skin().window_radius
        card = QPixmap(self._card_size())
        card.setDevicePixelRatio(self.devicePixelRatioF())
        card.fill(QColor(0, 0, 0, 0))
        painter = QPainter(card)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

        # A soft shadow, drawn as a few nested outlines. Cheaper than a blur
        # effect over a window this large.
        for i in range(MARGIN, 0, -1):
            glow = QColor(p.shadow)
            glow.setAlpha(int(46 * (1 - i / (MARGIN + 1)) ** 1.7))
            painter.setPen(QPen(glow, 1.0))
            painter.drawRoundedRect(box.adjusted(-i, -i + 1, i, i + 1),
                                    radius + i, radius + i)

        path = QPainterPath()
        path.addRoundedRect(box, radius, radius)
        grad = QLinearGradient(box.topLeft(), box.bottomLeft())
        grad.setColorAt(0.0, QColor(p.window_hi))
        grad.setColorAt(1.0, QColor(p.window_lo))
        painter.fillPath(path, grad)
        painter.setPen(QPen(QColor(p.divider), 1.0))
        painter.drawPath(path)

        if self.settings.prediction_enabled:
            y = self.suggestions.geometry().bottom() + 3
            line = QColor(p.divider)
            line.setAlpha(140)
            painter.setPen(QPen(line, 1.0))
            painter.drawLine(round(box.left() + 12), y,
                             round(box.right() - 12), y)
        painter.end()
        return card

    # -- window behaviour --------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._styled:
            # Applied once the native window exists; this is what stops clicks
            # on the keyboard from stealing the caret from the target app.
            focus.make_non_activating(int(self.winId()))
            self._styled = True
        self._sync_glow_timer()
        self._refresh_glow_shape()

    # -- moving ------------------------------------------------------------

    def _begin_move(self, global_pos: QPoint) -> None:
        # Only the press is recorded here. Undocking waits for the pointer to
        # actually travel, because a docked keyboard that jumps loose on a
        # mistimed click is precisely the accident the users this is built for
        # make most often.
        self._press_global = global_pos
        self._move_origin = None

    def _continue_move(self, global_pos: QPoint) -> None:
        if self._press_global is None:
            return
        if self._move_origin is None:
            if (global_pos - self._press_global).manhattanLength() < DRAG_THRESHOLD:
                return
            if self.settings.docked:
                # A real drag on a docked keyboard is a request to release it.
                # Keep it where it already is rather than letting it jump to a
                # remembered position from some earlier session.
                geo = self.geometry()
                self.settings.docked = False
                self.settings.width = min(max(MIN_WIDTH, self.settings.width),
                                          geo.width())
                self.settings.x, self.settings.y = geo.x(), geo.y()
                self._apply_geometry()
            self._move_origin = self._press_global - self.frameGeometry().topLeft()
        self.move(self._keep_on_screen(global_pos - self._move_origin))

    def _keep_on_screen(self, pos: QPoint) -> QPoint:
        """Stop the window being dragged somewhere it cannot be got back from.

        Ordinary windows may hang off the edge of the screen; this one may not.
        Its edges are its resize handles and its top strip is the only way to
        move it, so a keyboard pushed half off the screen is a keyboard that can
        no longer be resized -- and the people using it are the least able to
        wrestle it back.
        """
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return pos
        area = screen.availableGeometry()
        x = min(max(area.x(), pos.x()), max(area.x(), area.right() - self.width() + 1))
        y = min(max(area.y(), pos.y()), max(area.y(), area.bottom() - self.height() + 1))
        return QPoint(x, y)

    def _end_move(self) -> None:
        moved, self._move_origin = self._move_origin, None
        self._press_global = None
        if moved is not None:
            self._remember_geometry()

    # -- resizing ----------------------------------------------------------

    def _edges_at(self, pos: QPoint) -> str:
        """Which edges of the card the pointer is on, as a string of ``lrtb``."""
        card = self.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        band = MARGIN + 3
        edges = ""
        if abs(pos.y() - card.top()) <= band:
            edges += "t"
        if not self.settings.docked:
            # A docked keyboard spans the screen and sits on the bottom edge;
            # only its height is the user's to change.
            if abs(pos.y() - card.bottom()) <= band:
                edges += "b"
            if abs(pos.x() - card.left()) <= band:
                edges += "l"
            if abs(pos.x() - card.right()) <= band:
                edges += "r"
        return edges

    @staticmethod
    def _cursor_for(edges: str) -> Qt.CursorShape:
        if edges in ("tl", "br", "lt", "rb"):
            return Qt.SizeFDiagCursor
        if edges in ("tr", "bl", "rt", "lb"):
            return Qt.SizeBDiagCursor
        if "t" in edges or "b" in edges:
            return Qt.SizeVerCursor
        if "l" in edges or "r" in edges:
            return Qt.SizeHorCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        edges = self._edges_at(event.position().toPoint())
        if edges:
            self._resize_edges = edges
            self._resize_from = event.globalPosition().toPoint()
            self._resize_geometry = self.geometry()
        else:
            self._begin_move(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._resize_edges and self._resize_from is not None:
            self._resize_to(event.globalPosition().toPoint())
            return
        if self._move_origin is not None and event.buttons() & Qt.LeftButton:
            self._continue_move(event.globalPosition().toPoint())
            return
        self.setCursor(self._cursor_for(self._edges_at(event.position().toPoint())))

    def mouseReleaseEvent(self, event) -> None:
        if self._resize_edges:
            self._resize_edges = ""
            self._resize_from = None
            self._remember_geometry()
            return
        self._end_move()

    def _resize_to(self, global_pos: QPoint) -> None:
        geo = self._resize_geometry
        delta = global_pos - self._resize_from
        left, top = geo.left(), geo.top()
        right, bottom = geo.right(), geo.bottom()
        floor = MIN_HEIGHT + self._suggestion_band()

        if "l" in self._resize_edges:
            left = min(left + delta.x(), right - MIN_WIDTH)
        if "r" in self._resize_edges:
            right = max(right + delta.x(), left + MIN_WIDTH)
        if "t" in self._resize_edges:
            top = min(top + delta.y(), bottom - floor)
        if "b" in self._resize_edges:
            bottom = max(bottom + delta.y(), top + floor)
        self.setGeometry(left, top, right - left + 1, bottom - top + 1)

    # -- focus tracking ----------------------------------------------------

    def _poll_foreground(self) -> None:
        """Notice when the user switches application.

        The shadow buffer describes one caret in one document; when focus moves
        the context is no longer true, and stale context predicts worse than no
        context at all.
        """
        hwnd = focus.foreground_window()
        if hwnd and hwnd != self._last_foreground and hwnd != int(self.winId()):
            self._last_foreground = hwnd
            self.engine.reset()
            self.controller.release_all()
            self.refresh_suggestions()
            if self.settings.always_on_top:
                focus.raise_without_activating(int(self.winId()))

    def _on_outside_click(self) -> None:
        """The user clicked into a document; assume the caret moved."""
        if self.engine.buffer:
            self.engine.reset()
            self.refresh_suggestions()

    # -- key handling ------------------------------------------------------

    def _on_key(self, key: Key) -> None:
        self.controller.press(key)

    def _on_suggestion(self, word: str) -> None:
        self.controller.accept_suggestion(word)

    # -- whole sentences ---------------------------------------------------

    def _on_sentence(self, text: str) -> None:
        """Write a whole sentence, then get out of the way.

        Closing straight after is not tidiness: the panel covers the keys, and
        leaving it open would make every sentence cost a third press to dismiss
        it before typing could go on.
        """
        self.controller.accept_sentence(text)
        self.hide_sentences()

    def toggle_sentences(self) -> None:
        if self.sentence_panel.isVisible():
            self.hide_sentences()
        else:
            self.show_sentences()

    def show_sentences(self) -> None:
        if not self.settings.sentence_suggestions:
            return
        self.sentence_panel.set_sentences(
            self.engine.sentence_suggestions(self.sentence_panel.capacity))
        self._place_sentence_panel()
        self.sentence_panel.show()
        self.sentence_panel.raise_()

    def hide_sentences(self) -> None:
        self.sentence_panel.hide()

    def _place_sentence_panel(self) -> None:
        """Cover the keys, and no more of the window than that.

        The suggestion rows stay visible above it deliberately: a user who opens
        the panel and finds nothing should be able to see the ordinary word
        predictions without shutting it first.
        """
        top = self.main_grid.geometry().top()
        left = MARGIN + 5
        right = self.width() - MARGIN - 5
        bottom = self.height() - MARGIN - 4
        available = max(80, bottom - top)
        self.sentence_panel.fit_to(available)
        # Only as much of the keyboard as the sentences actually need.
        height = min(available, self.sentence_panel.wanted_height())
        self.sentence_panel.setGeometry(left, top, right - left, height)

    def _sync_modifiers(self) -> None:
        c = self.controller
        shift, altgr, caps = c.shift_active, c.altgr_active, c.caps_lock
        self.main_grid.set_modifier_state(shift, altgr, caps)
        self.nav_grid.set_modifier_state(shift, altgr, caps)
        for name, mod in (("shift", c.shift), ("ctrl", c.ctrl), ("alt", c.alt),
                          ("win", c.win), ("altgr", c.altgr)):
            for cap in self.main_grid.caps_for_action(name):
                cap.set_latched(mod.active, mod.locked)
        for cap in self.main_grid.caps_for_action("capslock"):
            cap.set_latched(c.caps_lock, c.caps_lock)

    def refresh_suggestions(self) -> None:
        if not self.settings.prediction_enabled:
            return
        words = self.engine.suggestions(self.suggestions.capacity)
        self.suggestions.set_suggestions(words)
        self.suggestions.set_context(self.engine.buffer)
        self._refresh_sentences()

    def _refresh_sentences(self) -> None:
        """Keep the sentence count, and any open panel, in step with the text."""
        if not self.settings.sentence_suggestions:
            self.suggestions.set_sentence_count(0)
            return
        found = self.engine.sentence_suggestions(self.sentence_panel.capacity)
        self.suggestions.set_sentence_count(len(found))
        if self.sentence_panel.isVisible():
            self.sentence_panel.set_sentences(found)
            self._place_sentence_panel()   # it is sized to what is in it

    # -- system actions ----------------------------------------------------

    def _on_system_action(self, action: str) -> None:
        handlers = {
            "fn": self._toggle_fn,
            "nav": self._toggle_nav,
            "dock": self._toggle_dock,
            "fade": self._toggle_fade,
            "moveup": lambda: self._nudge(-MOVE_STEP_PX),
            "movedn": lambda: self._nudge(MOVE_STEP_PX),
            "options": self.open_options,
            "help": self._open_help,
        }
        handler = handlers.get(action)
        if handler:
            handler()

    def _toggle_fn(self) -> None:
        self._fn_active = not self._fn_active
        rows = list(albanian.ROWS)
        rows[0] = albanian.FUNCTION_ROW if self._fn_active else albanian.NUMBER_ROW
        self.main_grid.set_rows(rows)
        self.main_grid.apply_style(
            font_scale=self.settings.key_font_scale,
            dwell=self.settings.dwell_enabled,
            dwell_ms=self.settings.dwell_ms,
            repeat=self.settings.hold_to_repeat,
            repeat_delay=self.settings.repeat_delay_ms,
            repeat_rate=self.settings.repeat_rate_ms,
        )
        self._sync_modifiers()

    def _toggle_nav(self) -> None:
        self.settings.nav_visible = not self.settings.nav_visible
        self.nav_grid.setVisible(self.settings.nav_visible)
        save_settings(self.settings)

    def _toggle_dock(self) -> None:
        self.settings.docked = not self.settings.docked
        self._apply_geometry()
        save_settings(self.settings)

    def _toggle_fade(self) -> None:
        self._faded = not self._faded
        self.setWindowOpacity(
            self.settings.faded_opacity if self._faded else self.settings.opacity)

    def _toggle_theme(self) -> None:
        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        self.apply_settings()
        save_settings(self.settings)

    def _cycle_skin(self) -> None:
        """Step to the next keyboard design, from the header button.

        The designs are a matter of taste and taste is discovered by looking, so
        there is a way to page through them without opening a dialog. The name
        of the one that arrives is announced on the header for a moment, since
        the button gives no other clue which one you are now on.
        """
        keys = list(theme.SKINS)
        try:
            index = keys.index(self.settings.skin)
        except ValueError:
            index = 0
        self.settings.skin = keys[(index + 1) % len(keys)]
        self.apply_settings()
        save_settings(self.settings)
        self._flash_hint(theme.SKINS[self.settings.skin].label)

    def _flash_hint(self, text: str) -> None:
        """Show ``text`` in the header strip, then put the usual hint back."""
        self.hint_label.setText(text)
        QTimer.singleShot(1800, lambda: self.hint_label.setText(HINT_TEXT))

    def _zoom_suggestions(self, delta: int) -> None:
        """Grow or shrink the suggestion buttons, from the +/- on the bar.

        Height and lettering move together: a taller button with the same small
        word in it helps nobody, and two separate controls for one idea is one
        control too many out here. Options keeps them apart for anyone who wants
        that.
        """
        s = self.settings
        before = s.suggestion_height
        s.suggestion_height = min(96, max(22, before + delta))
        if s.suggestion_height == before:
            return
        s.suggestion_font_scale = round(s.suggestion_height / 34.0, 2)
        self.apply_settings()
        save_settings(self.settings)

    def _nudge(self, dy: int) -> None:
        """Move the keyboard up or down, so it stops covering what you are writing."""
        if self.settings.docked:
            self.settings.docked = False
            self._apply_geometry()
        geo = self.geometry()
        screen = QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else geo
        y = min(max(area.y(), geo.y() + dy), area.bottom() - geo.height() + 1)
        self.move(geo.x(), y)
        self._remember_geometry()

    def open_options(self) -> None:
        from .options import OptionsDialog
        dlg = OptionsDialog(self.settings, self.engine, self)
        dlg.settings_changed.connect(self._on_settings_changed)
        dlg.exec()

    def _on_settings_changed(self) -> None:
        self.apply_settings()
        save_settings(self.settings)

    def _open_help(self) -> None:
        from .options import HelpDialog
        HelpDialog(self).exec()

    # -- shutdown ----------------------------------------------------------

    def _request_close(self) -> None:
        self.close()

    def closeEvent(self, event) -> None:
        self._click_watcher.uninstall()
        self._remember_geometry()
        self.engine.flush()
        self.closed.emit()
        super().closeEvent(event)
        QApplication.quit()
