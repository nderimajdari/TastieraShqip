"""Injection of keystrokes into whatever window currently has focus.

Two mechanisms are used, and the distinction matters:

* Printable text is injected as UTF-16 code units with ``KEYEVENTF_UNICODE``.
  This bypasses the active keyboard layout entirely, so "ë" and "ç" arrive
  correctly even when the target machine has the US layout selected. It is the
  reason this keyboard does not require the Albanian layout to be installed.

* Everything else -- Enter, Tab, arrows, and any chord that involves Ctrl / Alt /
  Win -- is injected as a virtual key code. Applications read shortcuts from the
  virtual key, not from the produced character, so Ctrl+C injected as Unicode
  "c" would be silently ignored.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------------------
# SendInput plumbing
# ---------------------------------------------------------------------------

INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.VkKeyScanExW.argtypes = (wintypes.WCHAR, wintypes.HKL)
user32.VkKeyScanExW.restype = ctypes.c_short
user32.MapVirtualKeyExW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.HKL)
user32.MapVirtualKeyExW.restype = wintypes.UINT

MAPVK_VK_TO_VSC = 0

# A marker stamped into every event we synthesise. The optional physical-key
# listener uses it to ignore our own output instead of counting it twice.
INJECTED_MARKER = 0x05C10BE1

# ---------------------------------------------------------------------------
# Virtual key codes
# ---------------------------------------------------------------------------

VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "space": 0x20,
    "pgup": 0x21,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "apps": 0x5D,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i

# Keys that live on the "extended" part of the original PC keyboard. Without the
# extended flag Windows delivers e.g. Home as numpad-7 to some applications.
_EXTENDED = {
    VK["pgup"], VK["pgdn"], VK["end"], VK["home"],
    VK["left"], VK["up"], VK["right"], VK["down"],
    VK["insert"], VK["delete"], VK["numlock"], VK["printscreen"],
    VK["rctrl"], VK["ralt"], VK["lwin"], VK["rwin"], VK["apps"],
}


def _send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())
    return sent


def _vk_event(vk: int, keyup: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if keyup else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, None)
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0,
                      dwExtraInfo=INJECTED_MARKER),
    )


def _unicode_events(code_unit: int) -> list[INPUT]:
    return [
        INPUT(type=INPUT_KEYBOARD,
              ki=KEYBDINPUT(wVk=0, wScan=code_unit,
                            dwFlags=KEYEVENTF_UNICODE | up,
                            time=0, dwExtraInfo=INJECTED_MARKER))
        for up in (0, KEYEVENTF_KEYUP)
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_text(text: str) -> None:
    """Type ``text`` verbatim into the focused window, layout-independently."""
    events: list[INPUT] = []
    for ch in text:
        for unit in _utf16_units(ch):
            events.extend(_unicode_events(unit))
    _send(events)


def _utf16_units(ch: str) -> list[int]:
    """UTF-16 code units for one character (surrogate pair for astral chars)."""
    raw = ch.encode("utf-16-le")
    return [int.from_bytes(raw[i:i + 2], "little") for i in range(0, len(raw), 2)]


def send_vk(vk: int, modifiers: tuple[int, ...] = ()) -> None:
    """Press ``vk`` while ``modifiers`` (virtual key codes) are held down."""
    events: list[INPUT] = []
    for mod in modifiers:
        events.append(_vk_event(mod, keyup=False))
    events.append(_vk_event(vk, keyup=False))
    events.append(_vk_event(vk, keyup=True))
    for mod in reversed(modifiers):
        events.append(_vk_event(mod, keyup=True))
    _send(events)


def send_named(name: str, modifiers: tuple[int, ...] = ()) -> None:
    """Press a key from :data:`VK` by name, e.g. ``send_named("enter")``."""
    vk = VK.get(name)
    if vk is None:
        raise KeyError(f"unknown virtual key: {name}")
    send_vk(vk, modifiers)


def send_char_as_chord(ch: str, modifiers: tuple[int, ...], hkl: int | None = None) -> bool:
    """Send ``ch`` as a virtual-key chord (for Ctrl+C, Alt+F and friends).

    Returns False when the active layout cannot produce ``ch`` from a single
    key, in which case the caller should fall back to plain Unicode text.
    """
    res = user32.VkKeyScanExW(ch, hkl or 0)
    if res == -1:
        return False
    vk = res & 0xFF
    layout_mods = (res >> 8) & 0xFF
    mods = list(modifiers)
    if layout_mods & 1 and VK["shift"] not in mods:
        mods.append(VK["shift"])
    send_vk(vk, tuple(mods))
    return True
