"""Noticing when the caret moves somewhere the keyboard cannot see.

The prediction engine keeps a shadow copy of what has been typed, because there
is no reliable way to read the text out of an arbitrary Windows application.
That copy is only true for as long as this keyboard is the only thing writing.
The moment the user clicks somewhere else in the document -- to fix a word
further up, say -- the caret is no longer at the end of the shadow buffer, and
every prediction made from it is wrong.

A low-level mouse hook gives us the one signal that matters: a click that landed
outside the keyboard itself. Only button presses are inspected; move events are
passed straight through so the hook costs nothing noticeable system-wide.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
_BUTTON_DOWN = {WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN}


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE,
                                     wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                                  wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_longlong
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.WindowFromPoint.argtypes = (POINT,)
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND

GA_ROOT = 2


class OutsideClickWatcher:
    """Calls ``on_outside_click`` whenever a mouse button goes down elsewhere.

    The hook runs on the thread that installs it and relies on that thread
    pumping messages, which the Qt event loop already does.
    """

    def __init__(self, own_hwnd_getter: Callable[[], int],
                 on_outside_click: Callable[[], None]) -> None:
        self._own_hwnd = own_hwnd_getter
        self._callback = on_outside_click
        self._handle: int | None = None
        # Kept on the instance: if the trampoline is garbage collected while the
        # hook is installed, Windows calls into freed memory.
        self._proc = HOOKPROC(self._on_event)

    def install(self) -> bool:
        if self._handle:
            return True
        self._handle = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        return bool(self._handle)

    def uninstall(self) -> None:
        if self._handle:
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None

    def _on_event(self, code: int, wparam: int, lparam: int) -> int:
        if code >= 0 and wparam in _BUTTON_DOWN:
            try:
                data = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                hwnd = user32.WindowFromPoint(data.pt)
                root = user32.GetAncestor(hwnd, GA_ROOT) if hwnd else 0
                if root != self._own_hwnd():
                    self._callback()
            except Exception:
                # A hook callback must never raise into Windows.
                pass
        return user32.CallNextHookEx(self._handle or 0, code, wparam, lparam)
