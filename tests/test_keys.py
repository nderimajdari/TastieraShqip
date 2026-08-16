"""Tests for the keyboard layout, the modifier logic and the skins.

These cover the part of the program that decides *which character a key types*,
which is where a bug is least visible in review and most obvious in use: a Shift
that quietly does nothing looks exactly like a Shift that works until you read
what you typed.

Runnable either with pytest or directly:  python tests/test_keys.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osk.config import Settings
from osk.controller import KeyController, Modifier
from osk.layouts import albanian
from osk.layouts.albanian import Key
from osk.prediction.engine import PredictionEngine
from osk.prediction.sentences import SentenceBank
from osk.prediction.userstore import UserModel
from osk.ui import theme


def all_keys() -> list[Key]:
    rows = list(albanian.ROWS) + [albanian.FUNCTION_ROW] + list(albanian.NAV_ROWS)
    return [key for row in rows for key in row]


def key_for(base: str) -> Key:
    for key in all_keys():
        if key.is_char and key.base == base:
            return key
    raise AssertionError(f"no key types {base!r}")


def action_key(action: str) -> Key:
    for key in all_keys():
        if key.action == action:
            return key
    raise AssertionError(f"no key does {action!r}")


class FakeInput:
    """Stands in for SendInput, and records what would have been typed.

    The controller is where auto-capitals and the punctuation repair live, and
    both are decided just before the characters leave for the operating system
    -- so this is the only level at which they can be checked at all.
    """

    def __init__(self) -> None:
        self.typed = ""

    def send_text(self, text: str) -> None:
        self.typed += text

    def send_named(self, name: str, mods=()) -> None:
        if name == "backspace" and not mods:
            self.typed = self.typed[:-1]
        elif name == "space" and not mods:
            self.typed += " "

    def send_char_as_chord(self, ch, mods, hkl) -> bool:  # pragma: no cover
        return True


def typing_controller(monkey: list) -> tuple[KeyController, FakeInput]:
    """A controller wired to a recorder instead of to the real keyboard."""
    import tempfile

    from osk import controller as controller_module

    fake = FakeInput()
    original = controller_module.sendinput
    controller_module.sendinput = fake
    monkey.append(lambda: setattr(controller_module, "sendinput", original))

    scratch = Path(tempfile.mkdtemp())
    store = UserModel(scratch / "user.json")
    # A scratch sentence store, never the default: the default is the real one
    # under %APPDATA%, and a test must not write the user's own sentences.
    bank = SentenceBank(scratch / "sentences.json", builtin=False)
    engine = PredictionEngine(user_model=store, sentence_bank=bank)
    engine.learn = False
    return KeyController(engine), fake


def type_keys(controller: KeyController, sequence: str) -> None:
    """Press the keys that produce ``sequence``, one character at a time."""
    for ch in sequence:
        if ch == " ":
            controller.press(action_key("space"))
        else:
            controller.press(key_for(ch))


# -- shift ------------------------------------------------------------------

def test_shift_capitalises_a_letter_that_lists_no_shifted_form() -> None:
    # The bug this guards: letter keys carry only their lower-case character,
    # so a caption() that required an explicit shifted form returned "q" for
    # Shift+Q -- Shift appeared to do nothing at all.
    assert key_for("q").caption(shift=True) == "Q"
    assert key_for("z").caption(shift=True) == "Z"


def test_every_letter_key_shifts_to_something_different() -> None:
    letters = [k for k in all_keys() if k.is_letter]
    assert len(letters) >= 28
    for key in letters:
        assert key.caption(shift=True) != key.base


def test_the_albanian_letters_shift_to_their_own_capitals() -> None:
    assert key_for("ë").caption(shift=True) == "Ë"
    assert key_for("ç").caption(shift=True) == "Ç"


def test_shift_still_gives_punctuation_its_second_character() -> None:
    assert key_for(",").caption(shift=True) == ";"
    assert key_for("1").caption(shift=True) == "!"


def test_altgr_wins_over_shift() -> None:
    assert key_for("4").caption(shift=True, altgr=True) == "€"


# -- caps lock --------------------------------------------------------------

def test_caps_lock_capitalises_letters() -> None:
    assert key_for("a").shifted(shift=False, caps=True) is True


def test_caps_lock_leaves_punctuation_alone() -> None:
    # A comma key under Caps Lock types a comma, not a semicolon. Caps Lock is
    # not a second Shift.
    comma = key_for(",")
    assert comma.shifted(shift=False, caps=True) is False
    assert comma.caption(comma.shifted(False, True)) == ","


def test_shift_inverts_caps_lock_rather_than_adding_to_it() -> None:
    a = key_for("a")
    assert a.shifted(shift=True, caps=True) is False
    assert a.caption(a.shifted(True, True)) == "a"


def test_digits_are_not_letters() -> None:
    assert key_for("1").is_letter is False
    assert key_for("a").is_letter is True


# -- latching modifiers -----------------------------------------------------

def test_a_modifier_cycles_off_armed_locked_off() -> None:
    mod = Modifier(0x10)
    assert (mod.active, mod.locked) == (False, False)
    mod.cycle()
    assert (mod.active, mod.locked) == (True, False)
    mod.cycle()
    assert (mod.active, mod.locked) == (True, True)
    mod.cycle()
    assert mod.active is False


def test_an_armed_modifier_is_consumed_but_a_locked_one_is_not() -> None:
    armed, locked = Modifier(0x10), Modifier(0x10)
    armed.cycle()
    locked.cycle()
    locked.cycle()
    armed.consume()
    locked.consume()
    assert armed.active is False
    assert locked.active is True


# -- layout integrity -------------------------------------------------------

def test_every_row_of_the_main_block_is_the_same_width() -> None:
    widths = [sum(k.w for k in row) for row in albanian.ROWS]
    # The third row is short by the Enter key hanging down from the second.
    assert widths[0] == widths[1] == widths[3] == widths[4] == albanian.MAIN_WIDTH_UNITS
    assert widths[2] + 2.5 == albanian.MAIN_WIDTH_UNITS


def test_no_key_is_both_a_character_and_an_action() -> None:
    for key in all_keys():
        assert not (key.action and key.base)


# -- skins ------------------------------------------------------------------

def test_every_skin_offers_both_a_dark_and_a_light_palette() -> None:
    # The theme button is on the header of every design; a skin that answered
    # only one of the two would make it look broken.
    for key, skin in theme.SKINS.items():
        assert skin.palette("dark").name == "dark", key
        assert skin.palette("light").name == "light", key


def test_a_skin_defines_every_colour_the_painters_ask_for() -> None:
    from dataclasses import fields
    # key_text is the one optional colour: it exists for the designs whose
    # keycaps are not the same colour as the window behind them, and resolves
    # to the ordinary text colour when a skin does not need it.
    optional = {"name", "key_text"}
    for key, skin in theme.SKINS.items():
        for name in (f.name for f in fields(theme.Palette) if f.name not in optional):
            for palette in (skin.dark, skin.light):
                value = getattr(palette, name)
                assert isinstance(value, str) and value.startswith("#"), (key, name)


def test_the_default_skin_is_the_one_the_settings_start_on() -> None:
    assert Settings().skin in theme.SKINS


def test_choosing_a_skin_changes_the_palette_and_an_unknown_one_falls_back() -> None:
    typed = theme.set_theme("dark", "blue", "typewriter")
    assert typed is theme.SKINS["typewriter"].dark
    assert theme.skin() is theme.SKINS["typewriter"]
    # A settings file naming a design that no longer exists must not stop the
    # keyboard from starting.
    theme.set_theme("dark", "blue", "no-such-skin")
    assert theme.skin() is theme.SKINS["standard"]
    assert theme.palette().name == "dark"


def test_only_the_plain_skin_takes_the_users_accent_colour() -> None:
    plain = theme.set_theme("dark", "amber", "standard")
    assert plain.accent == theme.ACCENTS["amber"][1]
    # A designed board keeps its own: the colour is most of what makes it
    # recognisable, and the dialog says so rather than silently ignoring it.
    designed = theme.set_theme("dark", "amber", "gaming")
    assert designed.accent == theme.SKINS["gaming"].dark.accent
    theme.set_theme("dark", "blue", "standard")


def test_a_keycap_legend_is_readable_against_the_keycap_it_sits_on() -> None:
    """Every skin must keep enough contrast between a key and its lettering.

    Not a matter of taste: this is an assistive keyboard, and a design that
    looks striking but cannot be read at a glance has failed at the only thing
    it is for. 4.5:1 is the WCAG AA threshold for body text.
    """
    for key, skin in theme.SKINS.items():
        for palette in (skin.dark, skin.light):
            # The suggestion chips are keycaps too, and were the place this
            # went wrong: a design with cream caps on a dark body had chips the
            # colour of its keys and lettering the colour of its window.
            for background in (palette.key_hi, palette.key_lo,
                               palette.system_hi, palette.system_lo,
                               palette.chip_hi, palette.chip_lo):
                assert contrast(palette.legend, background) >= 4.5, (
                    key, palette.name, background)


def test_a_lit_keycap_is_still_readable_at_every_colour_of_the_wave() -> None:
    """The backlight must not eat the contrast it was measured to keep.

    The static palettes are checked above, but the RGB skin tints its keys with
    a colour that moves. Yellow at full saturation is the dangerous one, and it
    comes around on every cycle -- so the check has to run right around the
    wheel, not on the colour the skin happens to start at.
    """
    from PySide6.QtGui import QColor

    from osk.ui.keycap import KeyCap

    theme.set_theme("dark", "blue", "rgb")
    palette = theme.SKINS["rgb"].dark
    for step in range(24):
        hue = QColor.fromHsvF(step / 24.0, 0.78, 1.0)
        for base in (palette.key_hi, palette.system_hi, palette.chip_hi):
            face = theme.mix(base, hue, 0.16)
            assert contrast(palette.legend, face.name()) >= 4.5, (step, base)
    assert KeyCap is not None
    theme.set_theme("dark", "blue", "standard")


def test_only_the_rgb_skin_lights_its_keys() -> None:
    theme.set_theme("dark", "blue", "standard")
    assert theme.key_hue(0, 0.0) is None
    theme.set_theme("dark", "blue", "rgb")
    assert theme.key_hue(0, 0.0) is not None


def test_the_backlight_colour_varies_across_and_down_the_board() -> None:
    theme.set_theme("dark", "blue", "rgb")
    rows = [theme.key_hue(r, 0.0).name() for r in range(albanian.ROW_COUNT)]
    assert len(set(rows)) == albanian.ROW_COUNT
    across = [theme.key_hue(0, c).name() for c in (0.0, 4.0, 8.0, 15.0)]
    assert len(set(across)) == 4
    # Neighbours stay close, or the board reads as confetti rather than as one
    # light drifting over it.
    a, b = theme.key_hue(0, 0.0), theme.key_hue(0, 1.0)
    assert abs(a.hueF() - b.hueF()) < 0.05
    theme.set_theme("dark", "blue", "standard")


def test_the_wave_moves_and_wraps() -> None:
    theme.set_theme("dark", "blue", "rgb")
    before = theme.key_hue(0, 0.0).name()
    for _ in range(20):
        theme.advance(0.01)
    assert theme.key_hue(0, 0.0).name() != before
    for _ in range(80):
        theme.advance(0.01)   # a full turn back to where it started
    assert theme.key_hue(0, 0.0).name() == before
    theme.set_theme("dark", "blue", "standard")


def test_the_wave_only_runs_when_it_is_wanted_and_visible() -> None:
    theme.set_theme("dark", "blue", "rgb")
    theme.set_animating(True)
    assert theme.animating() is True
    theme.set_animating(False)
    assert theme.animating() is False
    # A skin with no backlight never animates, whatever the setting says.
    theme.set_animating(True)
    theme.set_theme("dark", "blue", "standard")
    assert theme.animating() is False


def _channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return (0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b))


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    lo, hi = sorted((la, lb))
    return (hi + 0.05) / (lo + 0.05)


# -- suggestion sizing ------------------------------------------------------

def test_the_suggestion_band_grows_with_rows_and_with_button_height() -> None:
    from osk.ui.suggestbar import band_height
    one = band_height(1, 34)
    assert band_height(2, 34) > one
    assert band_height(1, 60) > one


def test_suggestion_size_settings_are_clamped_to_something_usable() -> None:
    s = Settings(suggestion_height=5000, suggestion_font_scale=99.0).clamp()
    assert 22 <= s.suggestion_height <= 96
    assert 0.6 <= s.suggestion_font_scale <= 2.5
    s = Settings(suggestion_height=1, suggestion_font_scale=0.0).clamp()
    assert s.suggestion_height == 22
    assert s.suggestion_font_scale == 0.6


# -- what a sentence costs to write -----------------------------------------
#
# Every press these remove is a trip across the whole keyboard for somebody
# aiming with one finger, and a sentence boundary used to cost four of them.

def test_a_full_stop_closes_up_the_space_auto_space_left() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.engine.on_text("Shkova ")
        plan = c.engine.plan_accept("shtëpi")
        fake.typed = "Shkova shtëpi "
        c.engine.on_text(plan.text, auto_space=plan.auto_space)
        c.press(key_for("."))
        assert fake.typed == "Shkova shtëpi. "
    finally:
        for fn in undo:
            fn()


def test_a_full_stop_the_user_spaced_themselves_is_left_alone() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "po ")
        c.press(key_for("."))
        # The space was theirs, so it stays, and nothing is added after a stop
        # that does not follow a letter. The keyboard tidies up after itself,
        # not after the user.
        assert fake.typed == "Po ."
    finally:
        for fn in undo:
            fn()


def test_a_number_keeps_its_decimal_point() -> None:
    """"3.14" must not become "3. 14" -- the character before the stop is
    what tells a decimal from the end of a sentence."""
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "3")
        c.press(key_for("."))
        type_keys(c, "14")
        assert fake.typed == "3.14"
    finally:
        for fn in undo:
            fn()


def test_the_first_letter_after_a_full_stop_is_capitalised() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "po")
        c.press(key_for("."))
        type_keys(c, "po")
        # The first letter of all is capitalised too: an empty buffer is the
        # start of a sentence as much as a full stop is.
        assert fake.typed == "Po. Po"
    finally:
        for fn in undo:
            fn()


def test_auto_capitals_can_be_switched_off() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.auto_capitals = False
        type_keys(c, "po")
        c.press(key_for("."))
        type_keys(c, "po")
        assert fake.typed == "po. po"
    finally:
        for fn in undo:
            fn()


def test_the_automatic_capital_never_overrides_shift_or_caps_lock() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.caps_lock = True
        c.press(action_key("shift"))     # Shift inverts Caps Lock: small letter
        c.press(key_for("p"))
        assert fake.typed == "p"
    finally:
        for fn in undo:
            fn()


def test_auto_capitals_do_not_reach_the_middle_of_a_word() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "a")
        c.press(key_for("."))
        type_keys(c, "bc")
        assert fake.typed == "A. Bc"
    finally:
        for fn in undo:
            fn()


def test_shift_still_wins_over_an_automatic_capital() -> None:
    """Shift at a sentence start must still be able to produce lower case
    once Caps Lock is on -- the automatic capital may not override the user."""
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "po")
        c.press(key_for("."))
        c.caps_lock = True
        c.press(action_key("shift"))
        c.press(key_for("p"))
        assert fake.typed.endswith("p")
    finally:
        for fn in undo:
            fn()


def test_punctuation_repair_can_be_switched_off() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.auto_punctuation = False
        type_keys(c, "po")
        c.press(key_for("."))
        assert fake.typed == "Po."
    finally:
        for fn in undo:
            fn()


# -- whole sentences --------------------------------------------------------

def test_a_recalled_sentence_is_typed_in_full() -> None:
    """One press must produce the whole sentence, spaced ready for the next."""
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.accept_sentence("Faleminderit shumë për ndihmën.")
        assert fake.typed == "Faleminderit shumë për ndihmën. "
    finally:
        for fn in undo:
            fn()


def test_a_recalled_sentence_replaces_the_letters_already_typed() -> None:
    # The guard here is against the sentence being appended to the fragment
    # that summoned it -- "FalFaleminderit..." is the obvious failure.
    undo = []
    try:
        c, fake = typing_controller(undo)
        c.engine.bank.observe("Faleminderit shumë për ndihmën.")
        type_keys(c, "fal")
        c.accept_sentence("Faleminderit shumë për ndihmën.")
        assert fake.typed == "Faleminderit shumë për ndihmën. "
    finally:
        for fn in undo:
            fn()


def test_a_recalled_sentence_leaves_the_sentence_before_it_alone() -> None:
    undo = []
    try:
        c, fake = typing_controller(undo)
        type_keys(c, "po")
        c.press(key_for("."))
        c.accept_sentence("Mirupafshim!")
        assert fake.typed == "Po. Mirupafshim! "
    finally:
        for fn in undo:
            fn()


def test_a_sentence_typed_by_hand_is_remembered() -> None:
    """The whole feature rests on this: what is written comes back."""
    undo = []
    try:
        c, _fake = typing_controller(undo)
        c.engine.learn_sentences = True
        type_keys(c, "po vij nesër")
        c.press(key_for("."))
        assert c.engine.bank.matches("") == ["Po vij nesër."]
    finally:
        for fn in undo:
            fn()


def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
