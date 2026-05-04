"""Global hotkey registration via Win32 RegisterHotKey."""

from __future__ import annotations

import ctypes
import itertools
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes

__all__ = ["parse_hotkey", "HotkeyListener", "MOD_ALT", "MOD_CONTROL", "MOD_SHIFT", "MOD_WIN"]

MOD_ALT = 0x1
MOD_CONTROL = 0x2
MOD_SHIFT = 0x4
MOD_WIN = 0x8

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_MODIFIER_MAP = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

# Process-wide sequence so multiple HotkeyListener instances never share an ID.
# RegisterHotKey IDs in the range 0x0000..0xBFFF are reserved for unowned use;
# we start at 1 and just rely on no other code in this process going high.
_id_seq = itertools.count(1)
_id_lock = threading.Lock()


def _next_id() -> int:
    with _id_lock:
        return next(_id_seq)


def parse_hotkey(spec: str) -> tuple[int, int]:
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError(f"empty hotkey spec: {spec!r}")
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"no tokens in hotkey spec: {spec!r}")
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m not in _MODIFIER_MAP:
            raise ValueError(f"unknown modifier {m!r} in {spec!r}")
        modifiers |= _MODIFIER_MAP[m]
    if len(key) != 1 or not ("a" <= key <= "z"):
        raise ValueError(f"key must be a-z, got {key!r} in {spec!r}")
    vk = 0x41 + (ord(key) - ord("a"))
    return modifiers, vk


def _bind_user32_kernel32():
    """Bind only on Windows; return (user32, kernel32) with full prototypes."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    # BOOL RegisterHotKey(HWND, int, UINT, UINT)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    user32.RegisterHotKey.restype = wintypes.BOOL

    # BOOL UnregisterHotKey(HWND, int)
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL

    # BOOL GetMessageW(LPMSG, HWND, UINT, UINT) — returns 0/-1/non-zero
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
    user32.GetMessageW.restype = ctypes.c_int  # signed: -1 is the documented error

    # BOOL PostThreadMessageW(DWORD, UINT, WPARAM, LPARAM)
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL

    # DWORD GetCurrentThreadId(void)
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    return user32, kernel32


class HotkeyListener:
    """Register a global Win32 hotkey on a dedicated daemon thread.

    Public API:
      start() — begin listening; raises if registration fails (e.g. another
                app already owns the chord). Caller should catch and
                surface to the user.
      stop()  — unregister and shut down the listener thread.
      registered (bool) — read-only, True once start() succeeded.
    """

    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self._modifiers, self._vk = parse_hotkey(spec)
        self._callback = callback
        self._id = _next_id()  # per-instance, never collides
        self._thread: threading.Thread | None = None
        self._tid: int | None = None  # set ONLY after RegisterHotKey succeeds
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._stopped = threading.Event()
        self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def start(self) -> None:
        if not sys.platform.startswith("win"):
            raise NotImplementedError("HotkeyListener requires Windows")
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="HotkeyListener", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._error is not None:
            # The thread has already exited via the early-return path; clean
            # up state so a subsequent stop() is a safe no-op.
            self._thread = None
            self._tid = None
            raise self._error

    def stop(self) -> None:
        # Guard rails: if start() never succeeded, nothing to do.
        thread = self._thread
        tid = self._tid
        if thread is None or tid is None:
            return
        try:
            user32, _ = _bind_user32_kernel32()
            user32.PostThreadMessageW(wintypes.DWORD(tid), WM_QUIT, wintypes.WPARAM(0), wintypes.LPARAM(0))
        except Exception:
            pass
        thread.join(timeout=2.0)
        self._thread = None
        self._tid = None
        self._registered = False

    def _run(self) -> None:
        try:
            user32, kernel32 = _bind_user32_kernel32()
            tid = int(kernel32.GetCurrentThreadId())
            ok = user32.RegisterHotKey(None, self._id, self._modifiers, self._vk)
            if not ok:
                err = ctypes.get_last_error() or 0
                raise OSError(err, ctypes.FormatError(err) if err else "RegisterHotKey returned FALSE")
            # Only publish thread state after successful registration so a
            # later stop() can't try to PostThreadMessageW to a thread that
            # already exited via the exception path.
            self._tid = tid
            self._registered = True
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self._id:
                    try:
                        self._callback()
                    except Exception:
                        pass
        finally:
            try:
                user32.UnregisterHotKey(None, self._id)
            except Exception:
                pass
            self._stopped.set()
