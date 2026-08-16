"""Turns a pressed on-screen key into actual input for the focused application.

This is also where sticky modifiers live. A one-finger, head-pointer or
switch-driven user cannot hold Shift and press A at the same time, so modifiers
latch instead:

* first press  -- armed for the next key only
* second press -- locked until pressed again
* third press  -- released

which is the same convention as the Windows StickyKeys feature, and the reason
Ctrl+Alt+Del-style chords are reachable with a single pointer.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .layouts.albanian import Key
from .prediction.engine import AcceptPlan, PredictionEngine
from .winapi import focus, sendinput
from .winapi.sendinput import VK

# Actions handled by the window rather than by sending input.
SYSTEM_ACTIONS = {"nav", "moveup", "movedn", "dock", "options", "help", "fade", "fn"}

# Keys that move the caret somewhere the shadow buffer cannot follow.
NAVIGATION_ACTIONS = {"left", "right", "up", "down", "home", "end", "pgup", "pgdn"}

# Action name -> virtual key, for keys that are simply forwarded.
FORWARDED = {
    "esc": "esc", "delete": "delete", "insert": "insert", "pause": "pause",
    "printscreen": "printscreen", "scrolllock": "scrolllock", "menu": "apps",
    "home": "home", "end": "end", "pgup": "pgup", "pgdn": "pgdn",
    "left": "left", "right": "right", "up": "up", "down": "down",
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
}


class Modifier:
    """A latching modifier: off -> armed -> locked -> off."""

    def __init__(self, vk: int) -> None:
        self.vk = vk
        self.state = 0  # 0 off, 1 armed for one key, 2 locked

    @property
    def active(self) -> bool:
        return self.state > 0

    @property
    def locked(self) -> bool:
        return self.state == 2

    def cycle(self) -> None:
        self.state = (self.state + 1) % 3

    def consume(self) -> None:
        """Release the modifier after a keystroke, unless it is locked."""
        if self.state == 1:
            self.state = 0

    def clear(self) -> None:
        self.state = 0


class KeyController(QObject):
    context_changed = Signal()
    modifiers_changed = Signal()
    system_action = Signal(str)

    def __init__(self, engine: PredictionEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.shift = Modifier(VK["shift"])
        self.ctrl = Modifier(VK["ctrl"])
        self.alt = Modifier(VK["alt"])
        self.win = Modifier(VK["lwin"])
        self.altgr = Modifier(VK["ralt"])
        self.caps_lock = False
        #: Capitalise the first letter typed after a full stop. Shift is two
        #: trips across the board for one capital, and a sentence needs one
        #: every time -- see :meth:`_press_char`.
        self.auto_capitals = True
        #: Put the space after a full stop or comma in without being asked.
        self.auto_punctuation = True
        self._modifiers = {
            "shift": self.shift, "ctrl": self.ctrl,
            "alt": self.alt, "win": self.win, "altgr": self.altgr,
        }

    # -- state -------------------------------------------------------------

    @property
    def shift_active(self) -> bool:
        return self.shift.active

    @property
    def altgr_active(self) -> bool:
        return self.altgr.active

    def shifted(self, key: Key) -> bool:
        """Whether ``key`` is at its shifted level right now.

        Shift and Caps Lock combine differently per key -- Caps Lock reaches
        letters only -- so the decision belongs to the key, not to a single
        "shift is on" flag.
        """
        return key.shifted(self.shift.active, self.caps_lock)

    def _chord_modifiers(self) -> tuple[int, ...]:
        """Virtual keys of the modifiers that must be held for a chord."""
        mods: list[int] = []
        if self.ctrl.active:
            mods.append(VK["ctrl"])
        if self.alt.active:
            mods.append(VK["alt"])
        if self.win.active:
            mods.append(VK["lwin"])
        if self.shift.active:
            mods.append(VK["shift"])
        return tuple(mods)

    def _consume_modifiers(self) -> None:
        for mod in self._modifiers.values():
            mod.consume()
        self.modifiers_changed.emit()

    def release_all(self) -> None:
        for mod in self._modifiers.values():
            mod.clear()
        self.modifiers_changed.emit()

    # -- pressing ----------------------------------------------------------

    def press(self, key: Key) -> None:
        if key.action in SYSTEM_ACTIONS:
            self.system_action.emit(key.action)
            return

        if key.action in self._modifiers:
            self._modifiers[key.action].cycle()
            self.modifiers_changed.emit()
            return

        if key.action == "capslock":
            sendinput.send_named("capslock")
            self.caps_lock = not self.caps_lock
            self.modifiers_changed.emit()
            return

        if key.is_char:
            self._press_char(key)
            return

        self._press_action(key)

    def _press_char(self, key: Key) -> None:
        shifted = self.shifted(key)
        ch = key.caption(shifted, self.altgr_active)
        if not ch:
            return
        mods = self._chord_modifiers()
        # Ctrl/Alt/Win chords must travel as virtual keys: an application looks
        # at the key, not at the character, when matching a shortcut.
        if self.ctrl.active or self.alt.active or self.win.active:
            hkl = focus.foreground_layout()
            if not sendinput.send_char_as_chord(ch, mods, hkl):
                sendinput.send_text(ch)
            self._consume_modifiers()
            self.engine.on_navigation()  # a shortcut may have moved the caret
            self.context_changed.emit()
            return

        # A full stop after an accepted word lands on the space auto-space put
        # there. Take it back out rather than making the user do it.
        if self.engine.plan_punctuation(ch):
            sendinput.send_named("backspace")
            self.engine.on_backspace()

        # Only when no modifier is in play. Shift and Caps Lock are the user
        # saying what case they want, and a convenience that overrides them is
        # not a convenience -- Shift with Caps Lock on has to be able to produce
        # a small letter even at the start of a sentence.
        if (self.auto_capitals and key.is_letter and not self.shift.active
                and not self.caps_lock and self.engine.at_sentence_start):
            ch = ch.upper()

        trailing = self._space_after(ch)
        sendinput.send_text(ch + trailing)
        self.engine.on_text(ch + trailing, auto_space=bool(trailing))
        self._consume_modifiers()
        self.context_changed.emit()

    def _space_after(self, ch: str) -> str:
        """The space that follows sentence punctuation, if it should follow it.

        Only after a letter: "3.14" and "14:30" must be left alone, and the
        character before the stop is what tells the two apart. Also only for
        punctuation that ends a clause -- a closing bracket may well be
        followed by more of the same.
        """
        if not (self.auto_punctuation and self.engine.auto_space):
            return ""
        if ch not in ".,!?;:":
            return ""
        buffer = self.engine.buffer
        return " " if buffer[-1:].isalpha() else ""

    def _press_action(self, key: Key) -> None:
        action = key.action
        mods = self._chord_modifiers()

        if action == "space":
            if mods:
                sendinput.send_named("space", mods)
                self.engine.on_navigation()
            else:
                sendinput.send_named("space")
                self.engine.on_text(" ")
        elif action == "backspace":
            sendinput.send_named("backspace", mods)
            if mods:
                # Ctrl+Backspace deletes a whole word; we cannot mirror that
                # precisely, so drop the context instead of desynchronising it.
                self.engine.on_navigation()
            else:
                self.engine.on_backspace()
        elif action == "enter":
            sendinput.send_named("enter", mods)
            self.engine.on_text("\n")
        elif action == "tab":
            sendinput.send_named("tab", mods)
            self.engine.on_navigation()
        elif action in FORWARDED:
            sendinput.send_named(FORWARDED[action], mods)
            if action in NAVIGATION_ACTIONS or action == "delete":
                self.engine.on_navigation()
        else:
            return

        self._consume_modifiers()
        self.context_changed.emit()

    # -- predictions -------------------------------------------------------

    def accept_sentence(self, text: str) -> None:
        """Write a whole recalled sentence in place of the one being typed."""
        self._apply(self.engine.plan_sentence(text))

    def accept_suggestion(self, word: str) -> None:
        """Replace the half-typed word with a chosen prediction."""
        self._apply(self.engine.plan_accept(word))

    def _apply(self, plan: AcceptPlan) -> None:
        """Carry out an accept plan: delete this much, then type this."""
        for _ in range(plan.backspaces):
            sendinput.send_named("backspace")
            self.engine.on_backspace()
        if plan.text:
            sendinput.send_text(plan.text)
            self.engine.on_text(plan.text, auto_space=plan.auto_space)
        self.context_changed.emit()
