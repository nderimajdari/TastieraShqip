"""Colours, shapes and fonts -- everything that decides how the keyboard looks.

Two layers, deliberately separate:

* a :class:`Palette` is the colours alone, and every widget resolves its colours
  through the current one, so a theme change is a single swap rather than a hunt
  through the widgets;
* a :class:`Skin` is the whole design -- a palette for the dark theme, another
  for the light one, plus the shape of a key, the depth of its shading, the gap
  between keys and the typeface of its legends.

Skins exist because a keyboard is a familiar object and people have strong
preferences about which one they are looking at. The six here are independent
designs written for this program, drawn in the manner of keyboards people
recognise -- a flat low-profile aluminium board, a red-and-black gaming board,
a backlit RGB one, a deep-travel mechanical board and a typewriter. They carry no
brand's name, marks or artwork, and none of them are affiliated with anyone.

The accent colour is separated out again because it carries meaning here: it
marks the key under the pointer and the progress of a dwell, and users with
colour vision deficiency may need a different hue to see either. The plain skin
leaves that choice to the user; the designed ones set their own, because an
arbitrary accent is exactly what would stop them looking like themselves.
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
    #: Legends on the keys, when the keycaps are not the same colour as the rest
    #: of the window -- cream keys on a black body, say, where one text colour
    #: cannot be read on both.
    key_text: str = ""

    @property
    def legend(self) -> str:
        return self.key_text or self.text

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


# ---------------------------------------------------------------------------
# Skins
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Skin:
    """A complete keyboard design: colours, shape, depth and lettering."""

    key: str
    label: str            # shown in the Options drop-down
    note: str             # one line under it, explaining what it looks like
    dark: Palette
    light: Palette

    radius: float = 8.0   # corner radius of a keycap, in pixels
    gap: float = 3.0      # space between keycaps
    #: How strongly a key is shaded from top to bottom. 0 is flat, 1 is the
    #: default gradient, above 1 deepens it into a moulded cap.
    bevel: float = 1.0
    shadow: float = 1.0   # depth of the drop shadow under a key
    edge: float = 1.0     # brightness of the lit line along a key's top edge
    border: float = 1.0   # width of the outline around a key
    #: Typefaces for the legends, best first; the first one installed wins and
    #: the interface font is the fallback.
    fonts: tuple[str, ...] = ()
    weight: int = 500     # Qt font weight for the legends
    #: Upper-cases the *named* keys (Tab, Enter, Shift). Never the characters:
    #: the letter on a key has to be the letter it types, or the user cannot see
    #: whether Shift is on.
    uppercase: bool = False
    #: Whether the keys are lit from underneath, the hue of the light running
    #: as a slow diagonal wave across and down the board. Only the RGB skin is.
    rgb: bool = False
    #: How strongly that light spills into the gaps around a key. The spill is
    #: most of what makes backlighting read as light rather than as a coloured
    #: border; see backlight.py.
    glow: float = 0.0
    window_radius: float = 14.0
    #: Whether the user's accent choice applies. The designed skins own their
    #: accent -- it is most of what makes them recognisable.
    accent_locked: bool = True

    def palette(self, theme: str) -> Palette:
        return self.light if theme == "light" else self.dark


_STANDARD = Skin(
    key="standard",
    label="Standarde",
    note="Pamja e zakonshme e programit. Ju zgjidhni ngjyrën e theksit.",
    dark=DARK, light=LIGHT,
    accent_locked=False,
)

# A flat, low-profile aluminium board: almost no shading, wide gaps between
# small square keys, thin lettering. Silver under the light theme, graphite
# under the dark one.
_SLIM = Skin(
    key="slim",
    label="Slim aluminium",
    note="Taste të sheshta e të holla, si tastierat e holla prej alumini.",
    light=Palette(
        name="light",
        window_hi="#ececed", window_lo="#dcdce0", surface="#ffffff",
        divider="#c9c9ce",
        key_hi="#ffffff", key_lo="#f8f8fa", key_border="#cfcfd4",
        key_edge="#ffffff", system_hi="#ebebee", system_lo="#e2e2e6",
        text="#1d1d1f", text_dim="#4b4b50", text_faint="#8e8e93",
        chip_hi="#ffffff", chip_lo="#f2f2f5", chip_border="#d5d5da",
        shadow="#9a9aa0", accent="#0071e3", accent_deep="#0058b0",
    ),
    dark=Palette(
        name="dark",
        window_hi="#3a3a3c", window_lo="#29292b", surface="#1c1c1e",
        divider="#48484a",
        key_hi="#4b4b4f", key_lo="#434347", key_border="#232326",
        key_edge="#5c5c61", system_hi="#38383b", system_lo="#313134",
        text="#f5f5f7", text_dim="#aeaeb2", text_faint="#8e8e93",
        chip_hi="#464649", chip_lo="#3a3a3d", chip_border="#545457",
        shadow="#000000", accent="#0a84ff", accent_deep="#0060df",
    ),
    radius=6.0, gap=4.5, bevel=0.15, shadow=0.35, edge=0.25, border=0.8,
    fonts=("SF Pro Display", "Helvetica Neue", "Segoe UI Variable Display",
           "Segoe UI"),
    weight=400, window_radius=12.0,
)

# Red on black, tight square keys, condensed capitals on the named keys.
_GAMING = Skin(
    key="gaming",
    label="Gaming — kuqezi",
    note="E zezë me theks të kuq dhe shkronja të mëdha, si tastierat e lojërave.",
    dark=Palette(
        name="dark",
        window_hi="#1e1e21", window_lo="#0d0d0f", surface="#08080a",
        divider="#2c2c31",
        key_hi="#26262b", key_lo="#161619", key_border="#000000",
        key_edge="#ff3b52", system_hi="#201f23", system_lo="#131315",
        text="#f5f5f7", text_dim="#b9b9c0", text_faint="#77777f",
        chip_hi="#24242a", chip_lo="#161619", chip_border="#4a2028",
        shadow="#000000", accent="#e8112d", accent_deep="#96091d",
    ),
    light=Palette(
        name="light",
        window_hi="#f2f2f4", window_lo="#e0e0e5", surface="#ffffff",
        divider="#cdcdd5",
        key_hi="#ffffff", key_lo="#e9e9ee", key_border="#b6b6c0",
        key_edge="#ff6b7d", system_hi="#ededf1", system_lo="#dedee4",
        text="#17171a", text_dim="#4a4a52", text_faint="#8b8b95",
        chip_hi="#ffffff", chip_lo="#ededf2", chip_border="#d3d3db",
        shadow="#9a9aa2", accent="#e8112d", accent_deep="#a80c20",
    ),
    radius=5.0, gap=4.0, bevel=0.95, shadow=1.3, edge=1.0, border=1.2,
    fonts=("Bahnschrift", "Segoe UI Semibold", "Franklin Gothic Medium",
           "Segoe UI"),
    weight=600, uppercase=True, window_radius=10.0,
)

# Every row lit a different colour, the way a per-key RGB board is usually set
# up. The legends stay white: the colour is on the edges, where it cannot cost
# any contrast on the letters themselves.
_RGB = Skin(
    key="rgb",
    label="RGB neon",
    note="Taste të errëta të ndriçuara nga poshtë, me dritë që rrjedh ngadalë "
         "nëpër tastierë. Shkronjat mbeten të bardha.",
    dark=Palette(
        name="dark",
        window_hi="#131019", window_lo="#07060a", surface="#040308",
        divider="#241d30",
        # Near-black caps on a near-black board: the colour has to come from
        # the light, not from the plastic, or the glow has nothing to read
        # against.
        key_hi="#1b1626", key_lo="#0d0b13", key_border="#040307",
        key_edge="#ffffff", system_hi="#171320", system_lo="#0b0910",
        text="#ffffff", text_dim="#c6bbdd", text_faint="#7d7392",
        chip_hi="#1e1829", chip_lo="#100d18", chip_border="#332853",
        shadow="#000000", accent="#b14dff", accent_deep="#7a1fd0",
    ),
    light=Palette(
        name="light",
        window_hi="#f7f4fd", window_lo="#e4dcf3", surface="#ffffff",
        divider="#cfc3e5",
        key_hi="#ffffff", key_lo="#f0eafa", key_border="#c2b5db",
        key_edge="#ffffff", system_hi="#f2ecfb", system_lo="#e5ddf3",
        text="#1b1526", text_dim="#5a4d72", text_faint="#8d82a3",
        chip_hi="#ffffff", chip_lo="#f1ebfa", chip_border="#cabde2",
        shadow="#9b8fb2", accent="#8b2fe0", accent_deep="#631cae",
    ),
    # A wider gap than the other designs: the light lives between the keys, so
    # the space between them is what there is to see it in.
    radius=7.0, gap=10.0, bevel=1.1, shadow=1.2, edge=1.6, border=1.0,
    fonts=("Bahnschrift", "Consolas", "Segoe UI"),
    weight=600, rgb=True, glow=1.0,
    window_radius=16.0,
)

# Deep, moulded caps with a heavy shadow and a monospaced legend -- the look of
# a full-travel mechanical board.
_MECHANICAL = Skin(
    key="mechanical",
    label="Mekanike",
    note="Taste të thella e të rënda, me hije të fortë dhe shkronja monospace.",
    dark=Palette(
        name="dark",
        window_hi="#35383d", window_lo="#22252a", surface="#1a1c1f",
        divider="#43474d",
        key_hi="#565a62", key_lo="#31343a", key_border="#15171a",
        key_edge="#6f747d", system_hi="#3e4147", system_lo="#282b30",
        text="#eef1f5", text_dim="#b4bac2", text_faint="#7d848d",
        chip_hi="#474b53", chip_lo="#33363c", chip_border="#575c64",
        shadow="#000000", accent="#f0a500", accent_deep="#a06f00",
        on_accent="#1a1c1f",
    ),
    light=Palette(
        name="light",
        window_hi="#d9d5c9", window_lo="#c3beb0", surface="#efece2",
        divider="#b0aa9a",
        key_hi="#f5f2e9", key_lo="#dcd7c8", key_border="#a49d8c",
        key_edge="#ffffff", system_hi="#cfcabb", system_lo="#bab4a3",
        text="#2a2620", text_dim="#5b5648", text_faint="#8d8878",
        chip_hi="#f5f2e9", chip_lo="#e2ddd0", chip_border="#b6b0a0",
        shadow="#7d7869", accent="#c1440e", accent_deep="#8c2f08",
    ),
    radius=4.0, gap=5.0, bevel=1.45, shadow=1.8, edge=0.9, border=1.0,
    fonts=("Consolas", "Cascadia Mono", "Lucida Console", "Courier New"),
    weight=600, window_radius=10.0,
)

# Cream keys, round caps, a serif legend and a dark red accent. The dark variant
# is the black-bodied machine, which is why the legends carry their own colour:
# cream keycaps need dark letters whatever the body behind them is doing.
_TYPEWRITER = Skin(
    key="typewriter",
    label="Makinë shkrimi",
    note="Taste të rrumbullakëta krem me shkronja serif, si makina e vjetër.",
    light=Palette(
        name="light",
        window_hi="#f3ead6", window_lo="#e0d3b6", surface="#fbf6ea",
        divider="#c6b592",
        key_hi="#fdfaf2", key_lo="#eee4d0", key_border="#8a7a5c",
        key_edge="#ffffff", system_hi="#e9dcc2", system_lo="#d9caab",
        text="#2f2519", text_dim="#6a5a42", text_faint="#99886b",
        chip_hi="#fdfaf2", chip_lo="#f0e7d4", chip_border="#bfae8c",
        shadow="#8a7a5c", accent="#8c2f1f", accent_deep="#5d1c11",
        on_accent="#fdfaf2",
    ),
    dark=Palette(
        name="dark",
        window_hi="#2b241c", window_lo="#15100c", surface="#0f0b08",
        divider="#3f342a",
        key_hi="#f0e8d7", key_lo="#dbd0b8", key_border="#0b0805",
        key_edge="#fffdf6", system_hi="#d9cdb4", system_lo="#c4b795",
        text="#ecdfc4", text_dim="#b9a684", text_faint="#8a7a5c",
        chip_hi="#efe7d5", chip_lo="#dcd1b9", chip_border="#0b0805",
        shadow="#000000", accent="#a8371f", accent_deep="#6d2011",
        on_accent="#fdfaf2", key_text="#241c14",
    ),
    radius=13.0, gap=5.0, bevel=0.85, shadow=1.5, edge=0.7, border=1.4,
    fonts=("Georgia", "Cambria", "Times New Roman"),
    weight=600, window_radius=18.0,
)

#: Every skin, in the order the Options drop-down and the cycle button use.
SKINS: dict[str, Skin] = {
    s.key: s for s in
    (_STANDARD, _SLIM, _GAMING, _RGB, _MECHANICAL, _TYPEWRITER)
}


_colour_cache: dict = {}


def colour(value):
    """``value`` as a QColor, parsed once.

    Parsing "#3a3f47" is not free, and the painters ask for the same handful of
    palette strings on every key of every frame. With a lit skin animating,
    that is thousands of parses a second for a dozen distinct colours.
    """
    from PySide6.QtGui import QColor
    if isinstance(value, QColor):
        return value
    cached = _colour_cache.get(value)
    if cached is None:
        cached = _colour_cache[value] = QColor(value)
    return cached


def mix(a, b, t: float):
    """``t`` of the way from colour ``a`` to colour ``b``.

    Hover and latch states are the palette's own colours tinted towards the
    accent, so that changing the accent changes them too. ``t`` outside 0..1 is
    allowed and extrapolates, which is how a skin deepens its own shading; the
    result is clamped so it stays a colour.
    """
    from PySide6.QtGui import QColor
    ca, cb = colour(a), colour(b)

    def channel(x: int, y: int) -> int:
        return min(255, max(0, round(x + (y - x) * t)))

    return QColor(
        channel(ca.red(), cb.red()),
        channel(ca.green(), cb.green()),
        channel(ca.blue(), cb.blue()),
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
_current_skin = _STANDARD
_family_cache: dict[tuple[str, ...], str] = {}


def palette() -> Palette:
    return _current


def skin() -> Skin:
    return _current_skin


def set_theme(name: str, accent: str = "blue", skin_key: str = "standard") -> Palette:
    global _current, _current_skin
    _current_skin = SKINS.get(skin_key, _STANDARD)
    base = _current_skin.palette(name if name in THEMES else "dark")
    if _current_skin.accent_locked:
        _current = base
    else:
        _label, light, deep = ACCENTS.get(accent, ACCENTS["blue"])
        _current = base.with_accent(light, deep)
    return _current


def font_family() -> str:
    """The first of the skin's typefaces that is actually installed.

    A skin naming a font the machine does not have would otherwise fall back to
    whatever Qt picks, which on Windows is a serif face -- unreadable at key
    size. The answer is cached because it is asked for on every repaint.
    """
    names = _current_skin.fonts
    if not names:
        return ""
    cached = _family_cache.get(names)
    if cached is not None:
        return cached
    from PySide6.QtGui import QFontDatabase
    installed = set(QFontDatabase.families())
    chosen = next((n for n in names if n in installed), "")
    _family_cache[names] = chosen
    return chosen


def key_font(base: "object", size: float, weight: int | None = None):
    """A legend font: the skin's face at ``size``, falling back to ``base``."""
    from PySide6.QtGui import QFont
    family = font_family()
    font = QFont(family) if family else QFont(base)
    font.setPointSizeF(size)
    font.setWeight(QFont.Weight(weight if weight is not None
                                else _current_skin.weight))
    return font


# ---------------------------------------------------------------------------
# Backlighting
# ---------------------------------------------------------------------------

#: How far the hue moves per row and per key across a row. Small numbers: a
#: real board's wave is much wider than one key, so neighbours are close in
#: colour and the whole thing reads as one light rather than as confetti.
#: backlight.py turns these two into the direction and period of a gradient.
ROW_SHIFT = 0.055
COLUMN_SHIFT = 0.020

#: Saturation and value of the light. Held high: it is dimmed by the alpha it
#: is drawn at, never by muddying the colour, or it stops looking like light.
SATURATION = 0.78

_phase = 0.0
_animating = True


def advance(step: float = 0.008) -> None:
    """Move the wave along one frame. Driven by a timer in the window."""
    global _phase
    _phase = (_phase + step) % 1.0


def set_animating(on: bool) -> None:
    """Freeze or unfreeze the wave. Frozen, it is a static rainbow profile."""
    global _animating
    _animating = on


def animating() -> bool:
    return _animating and _current_skin.rgb


def phase() -> float:
    return _phase


def wave_colour(hue: float):
    """The light at a given point on the hue circle."""
    from PySide6.QtGui import QColor
    return QColor.fromHsvF(hue % 1.0, SATURATION, 1.0)


def key_hue(row: int, column: float = 0.0):
    """The colour of the light on a key, or None if the skin has no light.

    Hue comes from position and from the phase of the wave, rather than from a
    fixed colour per row: a real board lights a shallow diagonal band that
    drifts, and a per-row palette of five flat colours is the thing that gives
    a fake one away.

    This is the definition of the wave. Nothing paints key by key -- the
    overlay in backlight.py builds one gradient with the same direction and
    period, because painting eighty-three keys individually cost more than the
    frame it had to fit in -- but this is what that gradient reproduces, and
    what the tests hold it to.
    """
    if not _current_skin.rgb:
        return None
    return wave_colour(_phase + row * ROW_SHIFT + column * COLUMN_SHIFT)


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

QPushButton#WinBtn, QPushButton#CloseBtn, QPushButton#ZoomBtn {{
    background: transparent;
    border: none;
    border-radius: 7px;
    color: {p.text_dim};
    padding: 0;
    font-size: 13px;
}}
QPushButton#WinBtn:hover, QPushButton#ZoomBtn:hover {{
    background: {p.chip_hi}; color: {p.text};
}}
QPushButton#WinBtn:pressed, QPushButton#ZoomBtn:pressed {{
    background: {p.accent}; color: {p.on_accent};
}}
QPushButton#ZoomBtn {{
    border: 1px solid {p.chip_border};
    font-size: 14px;
    font-weight: 700;
}}
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
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
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
QPushButton:disabled {{ color: {p.text_faint}; border-color: {p.divider}; }}

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
QSpinBox:disabled, QComboBox:disabled {{ color: {p.text_faint}; }}
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
