"""Colours, gradients and the widget stylesheet.

Everything visual is resolved through one :class:`Palette`, so a theme change is
a single swap rather than a hunt through the widgets. Two themes ship: a dark one
for ordinary use and a light one, which matters more than it looks -- an opaque
dark slab over a white document is tiring to read past, and some users with low
vision need the higher-contrast light scheme instead.

The accent colour is separated from the theme because it carries meaning here:
it marks the key under the pointer and the progress of a dwell, and users with
colour vision deficiency may need a different hue to see either.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Palette:
    """Every colour the keyboard draws with.

    Keys and chips are painted with a slight vertical gradient (``*_hi`` at the
    top, ``*_lo`` at the bottom). It reads as a physical key rather than a flat
    rectangle, and the highlight along the top edge is what keeps the keys
    legible when the window is made transparent.
    """

    name: str
    window_hi: str
    window_lo: str
    surface: str
    divider: str

    key_hi: str
    key_lo: str
    key_border: str
    key_edge: str          # the light along a key's top edge
    system_hi: str
    system_lo: str

    text: str
    text_dim: str
    text_faint: str

    chip_hi: str
    chip_lo: str
    chip_border: str

    shadow: str
    accent: str = "#3b9dff"
    accent_deep: str = "#1668c9"
    on_accent: str = "#ffffff"

    def with_accent(self, accent: str, deep: str) -> "Palette":
        return replace(self, accent=accent, accent_deep=deep)


DARK = Palette(
    name="dark",
    window_hi="#23262c",
    window_lo="#16181c",
    surface="#101216",
    divider="#2c3037",
    key_hi="#3a3f47",
    key_lo="#2b2f36",
    key_border="#14161a",
    key_edge="#4b515b",
    system_hi="#2c3038",
    system_lo="#212429",
    text="#f2f4f7",
    text_dim="#a8b0bb",
    text_faint="#6d7581",
    chip_hi="#30353d",
    chip_lo="#23272d",
    chip_border="#3d434c",
    shadow="#000000",
)

LIGHT = Palette(
    name="light",
    window_hi="#f4f6f9",
    window_lo="#e4e8ee",
    surface="#ffffff",
    divider="#d2d8e0",
    key_hi="#ffffff",
    key_lo="#eef1f5",
    key_border="#c2cad4",
    key_edge="#ffffff",
    system_hi="#e8ecf2",
    system_lo="#dde2ea",
    text="#12161c",
    text_dim="#4d5663",
    text_faint="#8a94a1",
    chip_hi="#ffffff",
    chip_lo="#eaeef4",
    chip_border="#c8d0da",
    shadow="#8b949e",
)

THEMES = {"dark": DARK, "light": LIGHT}

#: Accent choices, in Albanian, as they appear in the Options dialog.
ACCENTS = {
    "blue":   ("Blu",      "#3b9dff", "#1668c9"),
    "teal":   ("Gjelbër",  "#19b39a", "#0d7d6b"),
    "violet": ("Vjollcë",  "#9a7bff", "#6a46d6"),
    "amber":  ("Portokall", "#ff9a3c", "#d4700f"),
}

def mix(a: str, b: str, t: float):
    """``t`` of the way from colour ``a`` to colour ``b``.

    Hover and latch states are the palette's own colours tinted towards the
    accent, so that changing the accent changes them too.
    """
    from PySide6.QtGui import QColor
    ca, cb = QColor(a), QColor(b)
    return QColor(
        round(ca.red() + (cb.red() - ca.red()) * t),
        round(ca.green() + (cb.green() - ca.green()) * t),
        round(ca.blue() + (cb.blue() - ca.blue()) * t),
    )


def _glyph(name: str, colour: str, size: tuple[int, int], points) -> str:
    """Draw a small stroked glyph and return a path a stylesheet can use.

    Qt stylesheets read images from files, not from inline data, so the two
    marks the dialogs need -- the tick in a checkbox and the arrow on a
    drop-down -- are drawn once into the user's data directory and referenced
    from there. They are drawn rather than shipped so the application still
    carries no binary assets, and redrawn per colour so they follow the theme.
    """
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    from ..prediction.userstore import data_dir

    folder = data_dir() / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}_{colour.lstrip('#')}.png"
    if not path.exists():
        scale = 3   # drawn oversized so it stays crisp on a high-DPI display
        pix = QPixmap(size[0] * scale, size[1] * scale)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(colour), 1.8 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for a, b in zip(points, points[1:]):
            painter.drawLine(QPointF(a[0] * scale, a[1] * scale),
                             QPointF(b[0] * scale, b[1] * scale))
        painter.end()
        pix.save(str(path), "PNG")
    return path.as_posix()


def _chevron(colour: str) -> str:
    return _glyph("chevron", colour, (10, 7), [(1.2, 1.6), (5, 5.4), (8.8, 1.6)])


def _tick(colour: str) -> str:
    return _glyph("tick", colour, (12, 12), [(2.4, 6.4), (4.9, 8.9), (9.6, 3.4)])


_current = DARK


def palette() -> Palette:
    return _current


def set_theme(name: str, accent: str = "blue") -> Palette:
    global _current
    base = THEMES.get(name, DARK)
    _label, light, deep = ACCENTS.get(accent, ACCENTS["blue"])
    _current = base.with_accent(light, deep)
    return _current


def stylesheet() -> str:
    """Styling for the parts built from stock widgets (the dialogs, mostly).

    The keys and suggestion chips are drawn by hand and take their colours from
    the palette directly; a stylesheet cannot express a gradient that reacts to
    hover, press, latch and dwell at once.
    """
    p = _current
    dialog_bg = p.window_lo if p.name == "dark" else "#ffffff"
    field_bg = p.chip_lo if p.name == "dark" else "#ffffff"
    return f"""
QWidget#Root {{ background: transparent; }}
QWidget#SuggestionBar {{ background: transparent; }}

QPushButton#WinBtn, QPushButton#CloseBtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    color: {p.text_dim};
    padding: 0;
    font-size: 13px;
}}
QPushButton#WinBtn:hover {{ background: {p.chip_hi}; color: {p.text}; }}
QPushButton#WinBtn:pressed {{ background: {p.accent}; color: {p.on_accent}; }}
QPushButton#CloseBtn:hover {{ background: #d13438; color: #ffffff; }}

QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.divider};
    padding: 4px 8px;
}}

QDialog, QMessageBox {{
    background: {dialog_bg};
    color: {p.text};
}}
QDialog QLabel, QMessageBox QLabel, QDialog QCheckBox, QDialog QRadioButton {{
    color: {p.text};
}}
QGroupBox {{
    border: 1px solid {p.divider};
    border-radius: 10px;
    margin-top: 16px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.accent};
}}
QPushButton {{
    background: {p.chip_hi};
    color: {p.text};
    border: 1px solid {p.chip_border};
    border-radius: 8px;
    padding: 7px 16px;
}}
QPushButton:hover {{ border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.accent}; color: {p.on_accent}; }}
QPushButton:default {{ border-color: {p.accent}; }}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {p.chip_border};
    background: {field_bg};
}}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: url("{_tick(p.on_accent)}");
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.accent};
}}

QSlider::groove:horizontal {{
    height: 5px; background: {p.divider}; border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    height: 5px; background: {p.accent}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {p.accent}; width: 17px; height: 17px;
    margin: -7px 0; border-radius: 9px;
    border: 2px solid {dialog_bg};
}}

QSpinBox, QComboBox {{
    background: {field_bg}; color: {p.text};
    border: 1px solid {p.chip_border}; border-radius: 7px;
    padding: 5px 8px; min-height: 20px;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: url("{_chevron(p.text_dim)}");
    width: 10px; height: 7px; margin-right: 7px;
}}
QComboBox QAbstractItemView {{
    background: {dialog_bg}; color: {p.text};
    border: 1px solid {p.divider};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}

QTextBrowser {{
    background: {field_bg}; color: {p.text};
    border: 1px solid {p.divider}; border-radius: 10px; padding: 10px;
}}
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p.chip_border}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
"""
