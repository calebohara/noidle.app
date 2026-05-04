"""
noidle (zig.winapi)
====================

Thin ctypes wrapper around the Win32 surface required to keep a Windows
machine considered "active" by the OS power subsystem AND by user-mode
presence apps (Microsoft Teams, Slack, Outlook, etc.).

Background and rationale: see ``docs/windows-internals.md``.

Public API:
    prevent_sleep()      -> set ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    allow_sleep()        -> clear flags (set ES_CONTINUOUS only)
    send_mouse_jitter()  -> relative (+1,0) then (-1,0) via SendInput, net drift = 0
    send_f15()           -> VK_F15 key down + up via SendInput
    get_idle_seconds()   -> float seconds since last real-or-injected input

This module is import-safe on non-Windows platforms (it raises only when a
function is actually called), so the rest of the project can be linted and
unit-tested on macOS / Linux dev machines.

No production logic beyond this module — `noidle.app` policy code lives
elsewhere.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes  # noqa: F401  (always import for type stubs; harmless on non-win)

__all__ = [
    "prevent_sleep",
    "allow_sleep",
    "send_mouse_jitter",
    "send_f15",
    "get_idle_seconds",
]


# --------------------------------------------------------------------------- #
# Platform guard
# --------------------------------------------------------------------------- #

_IS_WINDOWS = sys.platform.startswith("win")


def _require_windows() -> None:
    if not _IS_WINDOWS:
        raise RuntimeError(
            "noidle (zig.winapi) only operates on Windows; "
            f"current platform is {sys.platform!r}"
        )


# --------------------------------------------------------------------------- #
# Win32 constants
# --------------------------------------------------------------------------- #

# SetThreadExecutionState flags (winbase.h)
ES_CONTINUOUS        = 0x80000000
ES_SYSTEM_REQUIRED   = 0x00000001
ES_DISPLAY_REQUIRED  = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040  # noqa: F841 (exposed for callers)

# SendInput types (winuser.h)
INPUT_MOUSE    = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2  # noqa: F841

# MOUSEINPUT.dwFlags
MOUSEEVENTF_MOVE     = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000  # noqa: F841

# KEYBDINPUT.dwFlags
KEYEVENTF_EXTENDEDKEY = 0x0001  # noqa: F841
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_UNICODE     = 0x0004  # noqa: F841
KEYEVENTF_SCANCODE    = 0x0008  # noqa: F841

# Virtual-Key Codes
VK_F15 = 0x7E


# --------------------------------------------------------------------------- #
# Win32 struct layouts for SendInput
#
# The INPUT struct is a tagged union. Its size differs between x86 (28 bytes)
# and x64 (40 bytes) due to pointer/ULONG_PTR widths in MOUSEINPUT.dwExtraInfo
# and KEYBDINPUT.dwExtraInfo. ctypes computes the right size automatically as
# long as we use ULONG_PTR (= c_size_t on win32) for those fields.
# --------------------------------------------------------------------------- #

# ULONG_PTR on Windows is pointer-sized: 4 bytes x86, 8 bytes x64.
# ctypes.c_size_t mirrors that exactly.
ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg",    ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("u",    _INPUT_UNION),
    ]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_uint),  # GetTickCount() ms; wraps every ~49.7 days
    ]


# --------------------------------------------------------------------------- #
# Lazy DLL bindings (only resolved on Windows, only on first use)
# --------------------------------------------------------------------------- #

_user32 = None
_kernel32 = None


def _bind() -> None:
    """Resolve user32 / kernel32 entry points once. Windows-only."""
    global _user32, _kernel32
    if _user32 is not None:
        return
    _require_windows()

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # SendInput(UINT cInputs, LPINPUT pInputs, int cbSize) -> UINT
    _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = ctypes.c_uint

    # GetLastInputInfo(PLASTINPUTINFO) -> BOOL
    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    _user32.GetLastInputInfo.restype = ctypes.c_int

    # GetTickCount() -> DWORD
    _kernel32.GetTickCount.argtypes = []
    _kernel32.GetTickCount.restype = ctypes.c_uint

    # SetThreadExecutionState(EXECUTION_STATE esFlags) -> EXECUTION_STATE
    _kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]
    _kernel32.SetThreadExecutionState.restype = ctypes.c_uint


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def prevent_sleep() -> int:
    """
    Tell Windows to stay awake (no S3/S4 sleep, no display blanking) until
    `allow_sleep` is called or the process exits.

    Returns the previous EXECUTION_STATE bitmask (mostly informational; the
    OS returns 0 on failure, in which case `ctypes.get_last_error()` may
    have a code).

    Note: this does NOT reset `GetLastInputInfo`. Presence apps like Teams
    will still flip you to Away — you must also call `send_mouse_jitter`
    and/or `send_f15` periodically. See `docs/windows-internals.md` §2.
    """
    _bind()
    assert _kernel32 is not None  # _bind() raises on non-Windows
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    prev = _kernel32.SetThreadExecutionState(flags)
    if prev == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    return prev


def allow_sleep() -> int:
    """
    Release the wakelock acquired by `prevent_sleep`. Restores normal power
    management. Returns the previous EXECUTION_STATE bitmask.
    """
    _bind()
    assert _kernel32 is not None
    prev = _kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    if prev == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    return prev


def _send(*inputs: _INPUT) -> int:
    """Push N INPUT events through SendInput; return how many were accepted."""
    _bind()
    assert _user32 is not None
    n = len(inputs)
    arr_t = _INPUT * n
    arr = arr_t(*inputs)
    accepted = _user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
    if accepted != n:
        raise ctypes.WinError(ctypes.get_last_error())
    return accepted


def send_mouse_jitter() -> None:
    """
    Send a relative (+1, 0) mouse move immediately followed by (-1, 0).
    Net cursor drift: 0 pixels. Both events advance LASTINPUTINFO.

    A zero-delta MOUSEEVENTF_MOVE is filtered by the input stack and does
    NOT reset the idle counter — that's why we use ±1.
    """
    move_right = _INPUT(type=INPUT_MOUSE)
    move_right.mi = _MOUSEINPUT(
        dx=1, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0
    )

    move_left = _INPUT(type=INPUT_MOUSE)
    move_left.mi = _MOUSEINPUT(
        dx=-1, dy=0, mouseData=0, dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=0
    )

    _send(move_right, move_left)


def send_f15() -> None:
    """
    Send a VK_F15 key down + up via SendInput. F15 is a defined virtual key
    that no mainstream keyboard ships and almost no application binds, so
    the OS counts it as input but user-mode apps ignore it.
    """
    key_down = _INPUT(type=INPUT_KEYBOARD)
    key_down.ki = _KEYBDINPUT(
        wVk=VK_F15, wScan=0, dwFlags=0, time=0, dwExtraInfo=0
    )

    key_up = _INPUT(type=INPUT_KEYBOARD)
    key_up.ki = _KEYBDINPUT(
        wVk=VK_F15, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0
    )

    _send(key_down, key_up)


def get_idle_seconds() -> float:
    """
    Return seconds since the last input event observed by the OS for the
    current desktop session. Combines `GetLastInputInfo` and
    `GetTickCount`, handling the 32-bit wraparound at ~49.7 days.

    Use this immediately after `send_mouse_jitter` / `send_f15` to
    self-verify that the injection was accepted. Expect a value < 1.0
    on success; a value ≥ N (where N is your jiggle interval) means the
    injection silently failed — see `docs/windows-internals.md` §7
    (RDP disconnect, locked workstation, session 0 isolation).
    """
    _bind()
    assert _user32 is not None and _kernel32 is not None
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if _user32.GetLastInputInfo(ctypes.byref(info)) == 0:
        raise ctypes.WinError(ctypes.get_last_error())

    now_ticks = _kernel32.GetTickCount()
    # Both values are unsigned 32-bit; subtract modulo 2**32 to handle wrap.
    delta_ms = (now_ticks - info.dwTime) & 0xFFFFFFFF
    return delta_ms / 1000.0


# --------------------------------------------------------------------------- #
# Smoke test (manual): `python -m zig.winapi`
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    if not _IS_WINDOWS:
        print(f"non-Windows platform ({sys.platform}); skipping live test")
        sys.exit(0)

    print(f"sizeof(INPUT)        = {ctypes.sizeof(_INPUT)} bytes")
    print(f"sizeof(LASTINPUTINFO)= {ctypes.sizeof(_LASTINPUTINFO)} bytes")

    print(f"idle before jiggle   = {get_idle_seconds():.3f} s")
    prevent_sleep()
    send_mouse_jitter()
    send_f15()
    time.sleep(0.05)
    print(f"idle after jiggle    = {get_idle_seconds():.3f} s  (expect < 0.1)")
    allow_sleep()
