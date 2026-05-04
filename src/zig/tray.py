from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from .autostart import current_target as autostart_target
from .autostart import disable as autostart_disable
from .autostart import enable as autostart_enable
from .autostart import is_enabled as autostart_is_enabled
from .config import Config, config_path, load as load_config, save as save_config
from .hotkey import HotkeyListener
from .jiggler import Jiggler, JigglerState, Method
from .logging_setup import log_dir, setup_file_logging
from .stats import Stats
from .updater import (
    CURRENT_VERSION,
    UpdateInfo,
    check_for_update,
    is_offerable,
    should_check_now,
)
from .whats_new import launch_whats_new_subprocess, mock_for_preview
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
    ("10 minutes", 600),
    ("30 minutes", 1800),
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
    """Open a folder/file with the OS handler. Creates the folder first if
    it's a directory that doesn't exist yet — fixes the v0.3.3 bug where
    'Open data folder' silently failed on a fresh install before any save.
    """
    try:
        if p.is_dir() or (not p.exists() and p.suffix == ""):
            p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
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
        self._hotkey_error: str = ""  # Empty if registered OK; user-facing message otherwise.
        self._last_offered_version: str = ""
        self._quitting = threading.Event()  # Short-circuits callbacks during shutdown.

        self._icon = pystray.Icon(
            "noidle",
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
            # Hotkey-status indicator: the visibility predicate hides it when
            # registration succeeded so it only nags when there's a real
            # problem the user needs to know about.
            MenuItem(lambda _i: f"⚠ Hotkey unavailable: {self._hotkey_error}",
                     self._show_hotkey_error,
                     visible=lambda _i: bool(self._hotkey_error)),
            Menu.SEPARATOR,
            MenuItem("Show stats", self._show_stats),
            MenuItem("Reset stats", self._reset_stats),
            MenuItem("Show idle time", self._show_idle),
            MenuItem("Check for updates now", self._manual_update_check),
            MenuItem("Preview update dialog", self._preview_whats_new),
            MenuItem("Open log", self._open_log),
            MenuItem("Open data folder", self._open_data_folder),
            MenuItem("Show autostart target", self._show_autostart_target),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    # ---- factories for radio items -------------------------------------- #

    def _make_set_interval(self, secs: float):
        def _set(_icon, _item) -> None:
            if self._quitting.is_set():
                return
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
            if self._quitting.is_set():
                return
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
        if self._quitting.is_set():
            return
        if self.jiggler.state.running:
            self.jiggler.stop()
            self.stats.stopped()
        else:
            self.jiggler.start()
            self.stats.started()
        self._refresh()

    def _toggle_smart_pause(self, _icon, _item) -> None:
        if self._quitting.is_set():
            return
        new = not self.config.smart_pause
        self.config.smart_pause = new
        self.jiggler.set_smart_pause(new)
        self._save()
        self._refresh()

    def _toggle_pause_share(self, _icon, _item) -> None:
        if self._quitting.is_set():
            return
        new = not self.config.pause_on_screen_share
        self.config.pause_on_screen_share = new
        self.jiggler.set_pause_on_screen_share(new)
        self._save()
        self._refresh()

    def _toggle_autostart(self, _icon, _item) -> None:
        if self._quitting.is_set():
            return
        try:
            if autostart_is_enabled():
                autostart_disable()
                self.config.autostart = False
            else:
                autostart_enable()
                self.config.autostart = True
            self._save()
        except RuntimeError as e:
            self._notify(str(e))
        self._refresh()

    def _toggle_update_check(self, _icon, _item) -> None:
        if self._quitting.is_set():
            return
        self.config.check_for_updates = not self.config.check_for_updates
        self._save()
        self._refresh()

    # ---- actions -------------------------------------------------------- #

    def _show_stats(self, _icon, _item) -> None:
        self._notify(self.stats.summary())

    def _reset_stats(self, _icon, _item) -> None:
        self.stats.reset()
        self._notify("Stats reset.")

    def _show_idle(self, _icon, _item) -> None:
        try:
            idle = get_idle_seconds()
        except Exception:
            idle = -1.0
        self._notify(f"Idle: {idle:.1f}s")

    def _show_hotkey_error(self, _icon, _item) -> None:
        if self._hotkey_error:
            self._notify(
                f"Couldn't register {self.config.hotkey}: {self._hotkey_error}\n"
                "Another app may already own this chord. Edit config.json to change it."
            )

    def _show_autostart_target(self, _icon, _item) -> None:
        try:
            self._notify(autostart_target())
        except RuntimeError as e:
            self._notify(str(e))

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
        if self._quitting.is_set():
            return
        threading.Thread(target=self._do_update_check, args=(True,), daemon=True).start()

    def _do_update_check(self, manual: bool) -> None:
        if self._quitting.is_set():
            return
        info = check_for_update()
        # Always record the attempt so the cache is honored next launch.
        self.config.last_update_check_at = time.time()
        self.config.last_update_check_failed = info is None
        self._save()

        if info is None:
            if manual:
                self._notify("Update check failed (offline?)")
            return
        if not info.is_newer:
            if manual:
                self._notify(f"Up to date (v{info.current})")
            return
        # Auto-checks honor "Skip this version" as a *floor*: only re-prompt
        # when the new version is strictly newer than what was skipped.
        # Manual checks always show so the user can override.
        if not manual and not is_offerable(info.latest, self.config.skipped_version):
            log.info("update v%s gated by skipped_version=%r", info.latest, self.config.skipped_version)
            return
        self._open_whats_new(info)

    def _open_whats_new(self, info: UpdateInfo) -> None:
        if self._quitting.is_set():
            return
        self._last_offered_version = info.latest
        # Run the dialog in a SUBPROCESS so tkinter executes on its own main
        # thread. Spawning daemon threads that call tk.Tk() is a documented
        # crash on macOS and a silent corrupter on Windows.
        threading.Thread(
            target=self._launch_whats_new_thread,
            args=(info.current, info.latest, info.body, info.url),
            daemon=True,
        ).start()

    def _launch_whats_new_thread(self, current: str, latest: str, body: str, url: str) -> None:
        try:
            choice = launch_whats_new_subprocess(
                current_version=current,
                latest_version=latest,
                release_notes=body,
                release_url=url,
            )
        except Exception:
            log.exception("whats_new subprocess failed")
            return
        if self._quitting.is_set():
            return
        self._handle_update_choice(choice)

    def _handle_update_choice(self, choice: str) -> None:
        if choice == "skip":
            try:
                latest = self._last_offered_version
                if latest:
                    self.config.skipped_version = latest
                    self._save()
            except Exception:
                log.exception("save skipped_version failed")
        elif choice == "download":
            log.info("user chose to download update")
        else:
            log.info("user dismissed update window")

    def _preview_whats_new(self, _icon, _item) -> None:
        # Debug menu item: opens the window with mock data so the user
        # can see what an update prompt looks like without waiting.
        # IMPORTANT: do NOT touch _last_offered_version — clicking Skip in
        # the preview must not poison the real config with the mock version.
        if self._quitting.is_set():
            return
        kwargs = mock_for_preview()
        threading.Thread(
            target=self._launch_preview_thread,
            args=(kwargs,),
            daemon=True,
        ).start()

    def _launch_preview_thread(self, kwargs: dict) -> None:
        try:
            launch_whats_new_subprocess(**kwargs)
        except Exception:
            log.exception("preview subprocess failed")

    def _quit(self, _icon, _item) -> None:
        # Set the shutdown flag FIRST so any in-flight callbacks short-circuit
        # before we start tearing things down.
        self._quitting.set()
        try:
            if self._hotkey is not None:
                try:
                    self._hotkey.stop()
                except Exception:
                    log.exception("hotkey stop failed")
            self.jiggler.stop()
            self.stats.stopped()
        finally:
            try:
                self._icon.stop()
            except Exception:
                log.exception("icon.stop failed")

    # ---- internals ------------------------------------------------------ #

    def _on_state_change(self, _state: JigglerState) -> None:
        if self._quitting.is_set():
            return
        self._refresh()

    def _refresh(self) -> None:
        if self._quitting.is_set():
            return
        st = self.jiggler.state
        try:
            self._icon.icon = _make_icon(_ACTIVE_RGB if st.running else _PAUSED_RGB)
            self._icon.title = self._tooltip(st)
            self._icon.update_menu()
        except Exception:
            log.debug("_refresh failed", exc_info=True)

    def _save(self) -> None:
        try:
            save_config(self.config)
        except Exception:
            log.exception("save_config failed")

    def _notify(self, message: str) -> None:
        """Wrapper around icon.notify that won't blow up during shutdown."""
        if self._quitting.is_set():
            return
        try:
            self._icon.notify(message, "noidle")
        except Exception:
            log.debug("notify failed", exc_info=True)

    def _tooltip(self, st: JigglerState) -> str:
        status = "running" if st.running else "paused"
        hotkey_line = self.config.hotkey if not self._hotkey_error else f"{self.config.hotkey} (unavailable)"
        return (
            f"noidle.app — {status}\n"
            f"method: {self.jiggler.method}  every {self.jiggler.interval_seconds:.0f}s\n"
            f"hotkey: {hotkey_line}\n"
            f"last jiggle: {_format_last(st.last_jiggle_at)}"
        )

    # ---- public --------------------------------------------------------- #

    def run(self) -> None:
        # Hotkey: register first, surface failures immediately. A silent
        # failure (the v0.3.3 behavior) means the user presses Ctrl+Alt+Z
        # forever expecting it to work.
        try:
            self._hotkey = HotkeyListener(self.config.hotkey, self._hotkey_pressed)
            self._hotkey.start()
        except NotImplementedError:
            # Off-Windows dev — don't surface as user-facing error, the
            # menu still works.
            log.warning("global hotkey unavailable on this platform; tray menu still works")
        except Exception as exc:
            self._hotkey_error = str(exc) or type(exc).__name__
            log.warning("hotkey registration failed: %s", self._hotkey_error)
            # Schedule a notification once the icon is up; doing it before
            # icon.run() is racy with pystray's setup.
            threading.Thread(
                target=self._notify_hotkey_failure_after_start,
                daemon=True,
            ).start()

        # Auto-clear stale skipped_version: if the user previously skipped
        # v0.4.0 and is now running v0.4.0+, their skip is by definition
        # satisfied — clear it so future patches don't get silently gated.
        if self.config.skipped_version and not is_offerable(self.config.skipped_version, CURRENT_VERSION):
            log.info("clearing stale skipped_version=%r (current=%s)",
                     self.config.skipped_version, CURRENT_VERSION)
            self.config.skipped_version = ""
            self._save()

        # Update check: rate-limited via cached timestamps in the config so
        # captive portals + 60+ launches/day don't get the user 403'd.
        if (self.config.check_for_updates
                and should_check_now(self.config.last_update_check_at,
                                     self.config.last_update_check_failed)):
            threading.Thread(target=self._do_update_check, args=(False,), daemon=True).start()

        self._icon.run()

    def _notify_hotkey_failure_after_start(self) -> None:
        # Wait a beat for the icon to be visible before notifying.
        time.sleep(2.0)
        self._notify(
            f"Couldn't register hotkey {self.config.hotkey}: {self._hotkey_error}.\n"
            "The tray menu still works. Edit config.json to change the chord."
        )

    def _hotkey_pressed(self) -> None:
        # Runs on the hotkey listener thread; pystray marshals icon updates.
        if self._quitting.is_set():
            return
        self._toggle(self._icon, None)


def run_tray() -> None:
    log_path = setup_file_logging()
    log.info("noidle.app v%s tray starting (log=%s, data=%s)",
             CURRENT_VERSION, log_path, log_dir())

    cfg = load_config()
    jiggler = Jiggler(
        interval_seconds=cfg.interval_seconds,
        method=cfg.method,  # type: ignore[arg-type]
        smart_pause=cfg.smart_pause,
        pause_on_screen_share=cfg.pause_on_screen_share,
    )
    TrayApp(jiggler, cfg, log_path).run()
