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

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QGuiApplication, QLinearGradient, QPainter,
    QPainterPath, QPen,
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
from .keypanel import UnitGrid
from .suggestbar import SuggestionBar

FOCUS_POLL_MS = 350
MOVE_STEP_PX = 60

#: Space kept clear around the drawn card. It holds the shadow and, more
#: importantly, it is the resize band: no child widget covers it, so it is the
#: only region where the window itself still sees the mouse.
MARGIN = 9
RADIUS = 14
MIN_WIDTH = 560
MIN_HEIGHT = 230
#: How far the pointer must travel before a press counts as a drag.
DRAG_THRESHOLD = 12


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

        self.hint_label = QLabel("Tërhiqe për ta lëvizur")
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
        theme.set_theme(s.theme, s.accent)
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
        self.suggestions.set_font_scale(s.key_font_scale)
        self.suggestions.setVisible(s.prediction_enabled)
        self.nav_grid.setVisible(s.nav_visible)

        self.engine.auto_space = s.auto_space
        self.engine.learn = s.learn_from_typing

        self.setWindowOpacity(s.faded_opacity if self._faded else s.opacity)
        self._apply_geometry()
        self.refresh_suggestions()
        self.update()

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
        rows = self.settings.suggestion_rows
        scale = min(1.6, max(0.8, self.settings.key_font_scale))
        return round((20 + rows * 38) * scale)

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
        p = theme.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

        # A soft shadow, drawn as a few nested outlines. Cheaper than a blur
        # effect over a window this large, and it repaints on every keypress.
        for i in range(MARGIN, 0, -1):
            glow = QColor(p.shadow)
            glow.setAlpha(int(46 * (1 - i / (MARGIN + 1)) ** 1.7))
            painter.setPen(QPen(glow, 1.0))
            painter.drawRoundedRect(card.adjusted(-i, -i + 1, i, i + 1),
                                    RADIUS + i, RADIUS + i)

        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        grad = QLinearGradient(card.topLeft(), card.bottomLeft())
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
            painter.drawLine(round(card.left() + 12), y,
                             round(card.right() - 12), y)
        painter.end()

    # -- window behaviour --------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._styled:
            # Applied once the native window exists; this is what stops clicks
            # on the keyboard from stealing the caret from the target app.
            focus.make_non_activating(int(self.winId()))
            self._styled = True

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

    def _sync_modifiers(self) -> None:
        c = self.controller
        shift, altgr = c.shift_active, c.altgr_active
        self.main_grid.set_modifier_state(shift, altgr)
        self.nav_grid.set_modifier_state(shift, altgr)
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
