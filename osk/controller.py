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
from .prediction.engine import PredictionEngine
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
        self._modifiers = {
            "shift": self.shift, "ctrl": self.ctrl,
            "alt": self.alt, "win": self.win, "altgr": self.altgr,
        }

    # -- state -------------------------------------------------------------

    @property
    def shift_active(self) -> bool:
        return self.shift.active or self.caps_lock

    @property
    def altgr_active(self) -> bool:
        return self.altgr.active

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
        ch = key.caption(self.shift_active, self.altgr_active)
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

        sendinput.send_text(ch)
        self.engine.on_text(ch)
        self._consume_modifiers()
        self.context_changed.emit()

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

    def accept_suggestion(self, word: str) -> None:
        """Replace the half-typed word with a chosen prediction."""
        plan = self.engine.plan_accept(word)
        for _ in range(plan.backspaces):
            sendinput.send_named("backspace")
            self.engine.on_backspace()
        if plan.text:
            sendinput.send_text(plan.text)
            self.engine.on_text(plan.text)
        self.context_changed.emit()
