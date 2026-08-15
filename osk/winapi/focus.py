"""Keeping the keyboard out of the focus chain, and watching who has focus.

An on-screen keyboard that takes focus is useless: the moment you click a key
the text cursor leaves the document you were writing in. Windows solves this
with ``WS_EX_NOACTIVATE`` -- a window carrying that style is never activated by
a mouse click, so the application underneath keeps its caret and receives the
keystrokes we inject.

``WS_EX_TOOLWINDOW`` additionally keeps the keyboard out of Alt+Tab and the
taskbar, which is what users expect from an assistive overlay.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _get_long = user32.GetWindowLongPtrW
    _set_long = user32.SetWindowLongPtrW
    _get_long.restype = ctypes.c_longlong
    _set_long.restype = ctypes.c_longlong
    _get_long.argtypes = (wintypes.HWND, ctypes.c_int)
    _set_long.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_longlong)
else:  # pragma: no cover - 32-bit interpreters
    _get_long = user32.GetWindowLongW
    _set_long = user32.SetWindowLongW
    _get_long.restype = ctypes.c_long
    _set_long.restype = ctypes.c_long
    _get_long.argtypes = (wintypes.HWND, ctypes.c_int)
    _set_long.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetKeyboardLayout.argtypes = (wintypes.DWORD,)
user32.GetKeyboardLayout.restype = wintypes.HKL
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)


def make_non_activating(hwnd: int) -> None:
    """Apply the no-focus-stealing window styles to ``hwnd``."""
    style = _get_long(hwnd, GWL_EXSTYLE)
    style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    _set_long(hwnd, GWL_EXSTYLE, style)
    # Re-assert topmost without activating, so the new styles take effect.
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)


def raise_without_activating(hwnd: int) -> None:
    """Bring the keyboard back to the top of the z-order, still without focus."""
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def foreground_layout() -> int:
    """Keyboard layout (HKL) of the focused window's thread.

    Needed so Ctrl/Alt chords are mapped through *its* layout rather than ours.
    """
    hwnd = foreground_window()
    if not hwnd:
        return 0
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    return user32.GetKeyboardLayout(tid)
