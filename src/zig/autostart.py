from __future__ import annotations

import os
import sys

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:
    winreg = None  # type: ignore[assignment]

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "noidle"


def _require_windows() -> None:
    if winreg is None:
        raise RuntimeError("autostart only available on Windows")


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path and not path.startswith('"') else path


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _launcher_script() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(pkg_dir, "..", ".."))
    return os.path.join(repo_root, "noidle.py")


def current_target() -> str:
    if _frozen():
        return _quote(os.path.abspath(sys.executable))
    return f"{_quote(os.path.abspath(sys.executable))} {_quote(_launcher_script())}"


def is_enabled() -> bool:
    _require_windows()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            data, _ = winreg.QueryValueEx(key, _VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return str(data).strip() == current_target().strip()


def enable() -> None:
    _require_windows()
    target = current_target()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, target)


def disable() -> None:
    _require_windows()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        return


# INTEGRATION:
# In src/zig/tray.py, add `from .autostart import is_enabled, enable, disable, current_target`.
# Add a checkable MenuItem under the Method submenu separator:
#     MenuItem(
#         "Start with Windows",
#         self._toggle_autostart,
#         checked=lambda _i: _safe_is_enabled(),
#     ),
# And a debug item under "Show idle time":
#     MenuItem("Show autostart target", self._show_autostart_target),
# Callbacks on TrayApp:
#     def _toggle_autostart(self, _icon, _item):
#         try:
#             (disable if is_enabled() else enable)()
#         except RuntimeError as e:
#             self._icon.notify(str(e), "noidle")
#         self._refresh()
#     def _show_autostart_target(self, _icon, _item):
#         self._icon.notify(current_target(), "noidle")
# Wrap is_enabled() in a `_safe_is_enabled` helper that returns False on RuntimeError
# so the menu still renders during macOS dev runs.
