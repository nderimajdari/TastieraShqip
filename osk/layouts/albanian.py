"""The Albanian (shqip) keyboard layout.

Albanian is a QWERTZ layout: Y and Z are swapped relative to US QWERTY, and it
carries the two letters that make the alphabet Albanian -- Ç (right of P) and Ë
(right of L). The punctuation on the bottom row follows the Italian-style
arrangement used by the sq-AL layout: comma/semicolon, period/colon,
slash/question mark, and the 102nd key with < and >.

Geometry is expressed in "key units": one unit is the width of a letter key.
Every row in the main block sums to 16 units, so the block scales cleanly to any
window size. Enter is two units tall and hangs down into the third row, exactly
as in the Windows on-screen keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    """One physical key.

    ``base`` / ``shift`` / ``altgr`` hold the characters produced in each of the
    three levels. Keys that do not produce text carry an ``action`` instead.
    """

    action: str = ""
    base: str = ""
    shift: str = ""
    altgr: str = ""
    label: str = ""
    w: float = 1.0
    h: float = 1.0
    repeatable: bool = False
    role: str = "normal"  # normal | modifier | system | accent

    @property
    def is_char(self) -> bool:
        return not self.action and bool(self.base)

    @property
    def is_letter(self) -> bool:
        """True for keys whose character has a distinct upper case."""
        return bool(self.base) and self.base.upper() != self.base

    def caption(self, shift: bool = False, altgr: bool = False) -> str:
        """The character this key emits at the current modifier level.

        Letter keys carry no explicit shifted form: there are thirty of them and
        the shifted character is simply the upper case one, including for ë and
        ç. Falling back to ``upper()`` rather than listing them is also what
        keeps Shift working -- an omitted second legend used to mean the key
        quietly produced its lower-case character with Shift held.
        """
        if altgr and self.altgr:
            return self.altgr
        if shift:
            return self.shift or self.base.upper()
        return self.base

    def shifted(self, shift: bool, caps: bool) -> bool:
        """Whether this key is at its shifted level, given Shift and Caps Lock.

        Caps Lock is not a second Shift: it applies to letters only -- with it
        on, the comma key must still type a comma -- and it inverts rather than
        forces, so Shift+A while capitals are locked gives a lower-case a.
        """
        if caps and self.is_letter:
            return not shift
        return shift


def C(base: str, shift: str = "", altgr: str = "", **kw) -> Key:
    """Character key."""
    return Key(base=base, shift=shift, altgr=altgr, repeatable=True, **kw)


def A(action: str, label: str, **kw) -> Key:
    """Action key."""
    kw.setdefault("role", "system")
    return Key(action=action, label=label, **kw)


def M(action: str, label: str, **kw) -> Key:
    """Modifier key (latching)."""
    return Key(action=action, label=label, role="modifier", **kw)


# ---------------------------------------------------------------------------
# Main block -- five rows, 16 units wide
# ---------------------------------------------------------------------------

NUMBER_ROW: list[Key] = [
    A("esc", "Esc"),
    C("\\", "|"),
    C("1", "!"),
    C("2", '"', "@"),
    C("3", "#", "£"),
    C("4", "$", "€"),
    C("5", "%"),
    C("6", "^"),
    C("7", "&"),
    C("8", "*"),
    C("9", "("),
    C("0", ")"),
    C("-", "_"),
    C("=", "+"),
    A("backspace", "⌫", w=2, repeatable=True),
]

# Fn swaps the number row for the function keys, as on a compact keyboard.
FUNCTION_ROW: list[Key] = (
    [A("esc", "Esc")]
    + [A(f"f{i}", f"F{i}") for i in range(1, 13)]
    + [A("delete", "Del"), A("backspace", "⌫", w=2, repeatable=True)]
)

ROWS: list[list[Key]] = [
    NUMBER_ROW,
    [
        A("tab", "Tab", w=1.5),
        C("q"), C("w"), C("e"), C("r"), C("t"), C("z"),
        C("u"), C("i"), C("o"), C("p"),
        C("ç"),
        C("@", "'"),
        A("enter", "Enter", w=2.5, h=2),
    ],
    [
        A("capslock", "Caps", w=1.5, role="modifier"),
        C("a"), C("s"), C("d"), C("f"), C("g"), C("h"),
        C("j"), C("k"), C("l"),
        C("ë"),
        C("[", "{"),
        C("]", "}"),
        # Enter from the previous row occupies the remaining 2.5 units.
    ],
    [
        M("shift", "Shift", w=1.5),
        C("<", ">"),
        C("y"), C("x"), C("c"), C("v"), C("b"), C("n"), C("m"),
        C(",", ";"),
        C(".", ":"),
        C("/", "?"),
        A("up", "⌃", repeatable=True),
        M("shift", "Shift"),
        A("delete", "Del", w=1.5, repeatable=True),
    ],
    [
        A("fn", "Fn", role="modifier"),
        M("ctrl", "Ctrl"),
        M("win", "⊞"),
        M("alt", "Alt"),
        A("space", "", w=6, repeatable=True, role="normal"),
        M("altgr", "AltGr"),
        M("ctrl", "Ctrl"),
        A("left", "‹", repeatable=True),
        A("down", "⌄", repeatable=True),
        A("right", "›", repeatable=True),
        A("menu", "☰"),
    ],
]

# ---------------------------------------------------------------------------
# Navigation pane -- the three columns down the right-hand side
# ---------------------------------------------------------------------------

NAV_ROWS: list[list[Key]] = [
    [A("home", "Home"), A("pgup", "PgUp"), A("nav", "Nav")],
    [A("end", "End"), A("pgdn", "PgDn"), A("moveup", "Mv Up")],
    [A("insert", "Insert"), A("pause", "Pause"), A("movedn", "Mv Dn")],
    [A("printscreen", "PrtScn"), A("scrolllock", "ScrLk"), A("dock", "Dock")],
    [A("options", "Options"), A("help", "Help"), A("fade", "Fade")],
]

MAIN_WIDTH_UNITS = 16.0
NAV_WIDTH_UNITS = 3.0
ROW_COUNT = 5

# Characters that end a sentence, after which the next word is capitalised.
SENTENCE_END = ".!?:"

# Punctuation that should not be preceded by a space when auto-spacing.
CLING_LEFT = ",.!?;:)]}»…%"
