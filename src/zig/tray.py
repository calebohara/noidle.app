from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Tuple

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

from .jiggler import Jiggler, JigglerState, Method
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
    d.ellipse((pad, pad, _ICON_SIZE - pad, _ICON_SIZE - pad), fill=rgb + (255,), outline=_RING_RGB + (255,), width=2)
    return img


def _format_last(ts: float | None) -> str:
    if ts is None:
        return "never"
    delta = max(0, int(time.time() - ts))
    when = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    return f"{when} ({delta}s ago)"


class TrayApp:
    def __init__(self, jiggler: Jiggler) -> None:
        self.jiggler = jiggler
        self.jiggler.on_state_change = self._on_state_change
        self._icon = pystray.Icon(
            "mouse_ziggler",
            icon=_make_icon(_PAUSED_RGB),
            title=self._tooltip(self.jiggler.state),
            menu=self._build_menu(),
        )

    def _build_menu(self) -> Menu:
        return Menu(
            MenuItem(
                lambda _i: "Pause" if self.jiggler.state.running else "Start",
                self._toggle,
                default=True,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "Interval",
                Menu(*[
                    MenuItem(
                        label,
                        self._make_set_interval(secs),
                        checked=self._make_interval_checked(secs),
                        radio=True,
                    )
                    for label, secs in _INTERVAL_PRESETS
                ]),
            ),
            MenuItem(
                "Method",
                Menu(*[
                    MenuItem(
                        label,
                        self._make_set_method(method),
                        checked=self._make_method_checked(method),
                        radio=True,
                    )
                    for label, method in _METHOD_PRESETS
                ]),
            ),
            Menu.SEPARATOR,
            MenuItem("Show idle time", self._show_idle),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    def _make_set_interval(self, secs: float):
        def _set(_icon, _item) -> None:
            self.jiggler.set_interval(secs)
            self._refresh()
        return _set

    def _make_interval_checked(self, secs: float):
        def _checked(_item) -> bool:
            return abs(self.jiggler.interval_seconds - secs) < 0.5
        return _checked

    def _make_set_method(self, method: Method):
        def _set(_icon, _item) -> None:
            self.jiggler.set_method(method)
            self._refresh()
        return _set

    def _make_method_checked(self, method: Method):
        def _checked(_item) -> bool:
            return self.jiggler.method == method
        return _checked

    def _toggle(self, _icon, _item) -> None:
        if self.jiggler.state.running:
            self.jiggler.stop()
        else:
            self.jiggler.start()
        self._refresh()

    def _show_idle(self, _icon, _item) -> None:
        try:
            idle = get_idle_seconds()
        except Exception:
            idle = -1
        self._icon.notify(f"Idle: {idle:.1f}s", "mouse_ziggler")

    def _quit(self, _icon, _item) -> None:
        try:
            self.jiggler.stop()
        finally:
            self._icon.stop()

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

    def _tooltip(self, st: JigglerState) -> str:
        status = "running" if st.running else "paused"
        return (
            f"mouse_ziggler — {status}\n"
            f"method: {self.jiggler.method}  every {self.jiggler.interval_seconds:.0f}s\n"
            f"last jiggle: {_format_last(st.last_jiggle_at)}"
        )

    def run(self) -> None:
        self._icon.run()


def run_tray() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    jiggler = Jiggler()
    TrayApp(jiggler).run()
