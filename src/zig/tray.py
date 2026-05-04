from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Tuple

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from .activity import is_teams_screen_sharing
from .autostart import current_target as autostart_target
from .autostart import disable as autostart_disable
from .autostart import enable as autostart_enable
from .autostart import is_enabled as autostart_is_enabled
from .config import Config, config_path, load as load_config, save as save_config
from .hotkey import HotkeyListener
from .jiggler import Jiggler, JigglerState, Method
from .logging_setup import log_dir, setup_file_logging
from .stats import Stats
from .updater import check_for_update
from .winapi import get_idle_seconds

log = logging.getLogger("zig.tray")

_ICON_SIZE = 64
_ACTIVE_RGB: Tuple[int, int, int] = (46, 204, 113)
_PAUSED_RGB: Tuple[int, int, int] = (140, 140, 140)
_RING_RGB: Tuple[int, int, int] = (30, 30, 30)

_INTERVAL_PRESETS: list[tuple[str, float]] = [
    ("15 seconds", 15),
    ("30 seconds", 30),
    ("45 seconds", 45),
    ("60 seconds", 60),
    ("90 seconds", 90),
    ("2 minutes", 120),
    ("5 minutes", 300),
]

_METHOD_PRESETS: list[tuple[str, Method]] = [
    ("Mouse only", "mouse"),
    ("Key only (F15)", "key"),
    ("Both", "both"),
]


def _make_icon(rgb: Tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 4
    d.ellipse((pad, pad, _ICON_SIZE - pad, _ICON_SIZE - pad),
              fill=rgb + (255,), outline=_RING_RGB + (255,), width=2)
    return img


def _format_last(ts: float | None) -> str:
    if ts is None:
        return "never"
    delta = max(0, int(time.time() - ts))
    when = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    return f"{when} ({delta}s ago)"


def _safe_autostart_is_enabled() -> bool:
    try:
        return autostart_is_enabled()
    except Exception:
        return False


def _open_path(p: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class TrayApp:
    def __init__(self, jiggler: Jiggler, config: Config, log_path: Path) -> None:
        self.jiggler = jiggler
        self.config = config
        self.log_path = log_path
        self.stats = Stats()
        self.jiggler.stats = self.stats
        self.jiggler.on_state_change = self._on_state_change

        self._hotkey: HotkeyListener | None = None

        self._icon = pystray.Icon(
            "mouse_ziggler",
            icon=_make_icon(_PAUSED_RGB),
            title=self._tooltip(self.jiggler.state),
            menu=self._build_menu(),
        )

    # ---- menu ----------------------------------------------------------- #

    def _build_menu(self) -> Menu:
        return Menu(
            MenuItem(
                lambda _i: "Pause" if self.jiggler.state.running else "Start",
                self._toggle,
                default=True,
            ),
            Menu.SEPARATOR,
            MenuItem("Interval", Menu(*[
                MenuItem(label, self._make_set_interval(s),
                         checked=self._make_interval_checked(s), radio=True)
                for label, s in _INTERVAL_PRESETS
            ])),
            MenuItem("Method", Menu(*[
                MenuItem(label, self._make_set_method(m),
                         checked=self._make_method_checked(m), radio=True)
                for label, m in _METHOD_PRESETS
            ])),
            Menu.SEPARATOR,
            MenuItem("Smart pause when active",
                     self._toggle_smart_pause,
                     checked=lambda _i: self.config.smart_pause),
            MenuItem("Pause during Teams screen share",
                     self._toggle_pause_share,
                     checked=lambda _i: self.config.pause_on_screen_share),
            MenuItem("Start with Windows",
                     self._toggle_autostart,
                     checked=lambda _i: _safe_autostart_is_enabled()),
            MenuItem("Check for updates on launch",
                     self._toggle_update_check,
                     checked=lambda _i: self.config.check_for_updates),
            Menu.SEPARATOR,
            MenuItem("Show stats", self._show_stats),
            MenuItem("Show idle time", self._show_idle),
            MenuItem("Check for updates now", self._manual_update_check),
            MenuItem("Open log", self._open_log),
            MenuItem("Open data folder", self._open_data_folder),
            MenuItem("Show autostart target", self._show_autostart_target),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    # ---- factories for radio items -------------------------------------- #

    def _make_set_interval(self, secs: float):
        def _set(_icon, _item) -> None:
            self.jiggler.set_interval(secs)
            self.config.interval_seconds = secs
            self._save()
            self._refresh()
        return _set

    def _make_interval_checked(self, secs: float):
        def _checked(_item) -> bool:
            return abs(self.jiggler.interval_seconds - secs) < 0.5
        return _checked

    def _make_set_method(self, method: Method):
        def _set(_icon, _item) -> None:
            self.jiggler.set_method(method)
            self.config.method = method
            self._save()
            self._refresh()
        return _set

    def _make_method_checked(self, method: Method):
        def _checked(_item) -> bool:
            return self.jiggler.method == method
        return _checked

    # ---- toggles -------------------------------------------------------- #

    def _toggle(self, _icon, _item) -> None:
        if self.jiggler.state.running:
            self.jiggler.stop()
            self.stats.stopped()
        else:
            self.jiggler.start()
            self.stats.started()
        self._refresh()

    def _toggle_smart_pause(self, _icon, _item) -> None:
        new = not self.config.smart_pause
        self.config.smart_pause = new
        self.jiggler.set_smart_pause(new)
        self._save()
        self._refresh()

    def _toggle_pause_share(self, _icon, _item) -> None:
        new = not self.config.pause_on_screen_share
        self.config.pause_on_screen_share = new
        self.jiggler.set_pause_on_screen_share(new)
        self._save()
        self._refresh()

    def _toggle_autostart(self, _icon, _item) -> None:
        try:
            if autostart_is_enabled():
                autostart_disable()
                self.config.autostart = False
            else:
                autostart_enable()
                self.config.autostart = True
            self._save()
        except RuntimeError as e:
            self._icon.notify(str(e), "mouse_ziggler")
        self._refresh()

    def _toggle_update_check(self, _icon, _item) -> None:
        self.config.check_for_updates = not self.config.check_for_updates
        self._save()
        self._refresh()

    # ---- actions -------------------------------------------------------- #

    def _show_stats(self, _icon, _item) -> None:
        self._icon.notify(self.stats.summary(), "mouse_ziggler")

    def _show_idle(self, _icon, _item) -> None:
        try:
            idle = get_idle_seconds()
        except Exception:
            idle = -1.0
        self._icon.notify(f"Idle: {idle:.1f}s", "mouse_ziggler")

    def _show_autostart_target(self, _icon, _item) -> None:
        try:
            self._icon.notify(autostart_target(), "mouse_ziggler")
        except RuntimeError as e:
            self._icon.notify(str(e), "mouse_ziggler")

    def _open_log(self, _icon, _item) -> None:
        try:
            _open_path(self.log_path)
        except Exception:
            log.exception("open log failed")

    def _open_data_folder(self, _icon, _item) -> None:
        try:
            _open_path(config_path().parent)
        except Exception:
            log.exception("open data folder failed")

    def _manual_update_check(self, _icon, _item) -> None:
        threading.Thread(target=self._do_update_check, args=(True,), daemon=True).start()

    def _do_update_check(self, manual: bool) -> None:
        info = check_for_update()
        if info is None:
            if manual:
                self._icon.notify("Update check failed (offline?)", "mouse_ziggler")
            return
        if info.is_newer:
            self._icon.notify(
                f"Update available: v{info.latest} (you have v{info.current})\nClick tray icon menu → download",
                "mouse_ziggler",
            )
            try:
                webbrowser.open(info.url)
            except Exception:
                pass
        elif manual:
            self._icon.notify(f"Up to date (v{info.current})", "mouse_ziggler")

    def _quit(self, _icon, _item) -> None:
        try:
            if self._hotkey is not None:
                try:
                    self._hotkey.stop()
                except Exception:
                    log.exception("hotkey stop failed")
            self.jiggler.stop()
            self.stats.stopped()
        finally:
            self._icon.stop()

    # ---- internals ------------------------------------------------------ #

    def _on_state_change(self, _state: JigglerState) -> None:
        self._refresh()

    def _refresh(self) -> None:
        st = self.jiggler.state
        self._icon.icon = _make_icon(_ACTIVE_RGB if st.running else _PAUSED_RGB)
        self._icon.title = self._tooltip(st)
        try:
            self._icon.update_menu()
        except Exception:
            log.debug("update_menu failed", exc_info=True)

    def _save(self) -> None:
        try:
            save_config(self.config)
        except Exception:
            log.exception("save_config failed")

    def _tooltip(self, st: JigglerState) -> str:
        status = "running" if st.running else "paused"
        return (
            f"mouse_ziggler — {status}\n"
            f"method: {self.jiggler.method}  every {self.jiggler.interval_seconds:.0f}s\n"
            f"last jiggle: {_format_last(st.last_jiggle_at)}"
        )

    # ---- public --------------------------------------------------------- #

    def run(self) -> None:
        try:
            self._hotkey = HotkeyListener(self.config.hotkey, self._hotkey_pressed)
            self._hotkey.start()
        except NotImplementedError:
            log.warning("global hotkey unavailable on this platform; tray menu still works")
        except Exception:
            log.exception("hotkey startup failed; continuing without it")

        if self.config.check_for_updates:
            threading.Thread(target=self._do_update_check, args=(False,), daemon=True).start()

        self._icon.run()

    def _hotkey_pressed(self) -> None:
        # Runs on the hotkey listener thread; pystray marshals icon updates.
        self._toggle(self._icon, None)


def run_tray() -> None:
    log_path = setup_file_logging()
    log.info("mouse_ziggler tray starting (log=%s, data=%s)", log_path, log_dir())

    cfg = load_config()
    jiggler = Jiggler(
        interval_seconds=cfg.interval_seconds,
        method=cfg.method,  # type: ignore[arg-type]
        smart_pause=cfg.smart_pause,
        pause_on_screen_share=cfg.pause_on_screen_share,
    )
    TrayApp(jiggler, cfg, log_path).run()
