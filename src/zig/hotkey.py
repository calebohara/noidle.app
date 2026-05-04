"""Global hotkey registration via Win32 RegisterHotKey."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable

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


class HotkeyListener:
    _HOTKEY_ID = 1

    def __init__(self, spec: str, callback: Callable[[], None]) -> None:
        self._modifiers, self._vk = parse_hotkey(spec)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._tid: int | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        if not sys.platform.startswith("win"):
            raise NotImplementedError("HotkeyListener requires Windows")
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="HotkeyListener", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._error is not None:
            raise self._error

    def stop(self) -> None:
        if self._thread is None or self._tid is None:
            return
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.PostThreadMessageW(ctypes.c_ulong(self._tid), WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            self._tid = int(kernel32.GetCurrentThreadId())
            ok = user32.RegisterHotKey(None, self._HOTKEY_ID, self._modifiers, self._vk)
            if not ok:
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            return
        self._ready.set()

        from ctypes import wintypes

        msg = wintypes.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == self._HOTKEY_ID:
                    try:
                        self._callback()
                    except Exception:
                        pass
        finally:
            try:
                user32.UnregisterHotKey(None, self._HOTKEY_ID)
            except Exception:
                pass
            self._stopped.set()


# INTEGRATION: tray.py wires this in JigglerTray.__init__ after reading
#   spec = config.get("hotkey", "ctrl+alt+z"). Construct:
#     self._hotkey = HotkeyListener(spec, self._toggle_paused)
#   then call self._hotkey.start() at the end of __init__ (after the
#   pystray Icon is built but before Icon.run). On non-Windows, wrap the
#   start() call in a try/except NotImplementedError and log a warning so
#   dev machines (mac/linux) still launch the tray for UI iteration.
#   In JigglerTray.shutdown() (or the on_quit handler) call
#   self._hotkey.stop() BEFORE icon.stop() so the GetMessage loop drains
#   cleanly. The callback (_toggle_paused) must be cheap and thread-safe
#   — it runs on the listener thread, not the tray thread; do all UI
#   updates by setting a flag the jiggler loop reads, or by calling
#   icon.update_menu() which pystray marshals internally.
