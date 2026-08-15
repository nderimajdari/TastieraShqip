"""Tastiera Shqip -- an on-screen Albanian keyboard with word prediction.

Run with::

    python main.py
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from osk import APP_NAME, __version__
from osk.config import load_settings, save_settings
from osk.controller import KeyController
from osk.prediction.engine import PredictionEngine
from osk.prediction.model import LanguageModel
from osk.ui import theme
from osk.ui.window import KeyboardWindow

MODEL_PATH = Path(__file__).resolve().parent / "osk" / "prediction" / "data" / "model_sq.pkl.gz"

#: The personal dictionary is flushed on this interval so a power loss costs at
#: most a minute of learned vocabulary.
AUTOSAVE_MS = 60_000


def build_icon() -> QIcon:
    """Draw the tray icon, so the app ships without binary assets."""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(theme.palette().accent))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 12, 60, 40, 6, 6)
    p.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(20)
    p.setFont(font)
    p.drawText(pix.rect().adjusted(0, 8, 0, 8), Qt.AlignCenter, "Ë")
    p.end()
    return QIcon(pix)


class ModelLoader(QThread):
    """Reads the language model off disk without holding up the keyboard.

    The Albanian model is a few hundred thousand n-gram contexts and takes some
    seconds to unpack. Doing that before the first paint meant the user watched
    an empty screen; done here, the keyboard is on screen and usable straight
    away and the predictions light up when they are ready. Somebody who only
    wants to type a filename never waits at all.
    """

    finished_loading = Signal(object, str)  # LanguageModel | None, error

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            self.finished_loading.emit(LanguageModel.load(self._path), "")
        except Exception as exc:  # a broken model must not stop the keyboard
            self.finished_loading.emit(None, str(exc))


def main() -> int:
    # Tell Windows this process is DPI aware, otherwise the keyboard is drawn
    # blurry and the key hit-boxes drift from what is painted -- which matters
    # a great deal to someone aiming with a head pointer.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)

    settings = load_settings()
    # The window applies the theme itself once it is built; setting it here too
    # means the tray icon and any early dialog are already the right colour.
    theme.set_theme(settings.theme, settings.accent)
    app.setStyleSheet(theme.stylesheet())
    engine = PredictionEngine()          # the model arrives on the thread below
    engine.auto_space = settings.auto_space
    engine.learn = settings.learn_from_typing

    controller = KeyController(engine)
    window = KeyboardWindow(settings, engine, controller)

    loader: ModelLoader | None = None
    if not MODEL_PATH.exists():
        window.suggestions.set_status(
            "Modeli i gjuhës nuk u gjet — parashikimi është i çaktivizuar. "
            "Ndërtojeni me: python tools/train.py"
        )
    else:
        window.suggestions.set_status("Duke ngarkuar fjalorin shqip…")

        def on_loaded(model, error: str) -> None:
            if model is None:
                window.suggestions.set_status(f"Modeli nuk u ngarkua: {error}")
                return
            engine.attach_model(model)
            window.suggestions.set_status("")
            window.refresh_suggestions()

        loader = ModelLoader(MODEL_PATH)
        loader.finished_loading.connect(on_loaded)
        loader.start()

    icon = build_icon()
    app.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(APP_NAME)
    menu = QMenu()
    show_action = QAction("Trego tastierën", menu)
    show_action.triggered.connect(window.show)
    options_action = QAction("Opsionet…", menu)
    options_action.triggered.connect(window.open_options)
    quit_action = QAction("Dil", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(show_action)
    menu.addAction(options_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.show() if reason == QSystemTrayIcon.Trigger else None)
    tray.show()

    autosave = QTimer(app)
    autosave.timeout.connect(engine.flush)
    autosave.start(AUTOSAVE_MS)

    def on_quit() -> None:
        # Let the loader finish before the interpreter tears down under it.
        if loader is not None and loader.isRunning():
            loader.wait(5000)
        engine.flush()
        save_settings(settings)

    app.aboutToQuit.connect(on_quit)

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
