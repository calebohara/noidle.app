from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

from .winapi import (
    allow_sleep,
    get_idle_seconds,
    prevent_sleep,
    send_f15,
    send_mouse_jitter,
)

log = logging.getLogger("zig.jiggler")

Method = Literal["mouse", "key", "both"]

_JITTER_RATIO = 0.20
_CORRECTION_DELAY_S = 0.05
_MIN_INTERVAL_S = 1.0


@dataclass
class JigglerState:
    running: bool = False
    last_jiggle_at: Optional[float] = None
    last_idle_seconds: Optional[float] = None
    tick_count: int = 0


@dataclass
class Jiggler:
    interval_seconds: float = 45.0
    method: Method = "both"
    jitter_pixels: int = 1
    on_state_change: Optional[Callable[[JigglerState], None]] = None

    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _state: JigglerState = field(default_factory=JigglerState, init=False, repr=False)

    @property
    def state(self) -> JigglerState:
        with self._lock:
            return JigglerState(
                running=self._state.running,
                last_jiggle_at=self._state.last_jiggle_at,
                last_idle_seconds=self._state.last_idle_seconds,
                tick_count=self._state.tick_count,
            )

    def set_interval(self, seconds: float) -> None:
        if seconds < _MIN_INTERVAL_S:
            raise ValueError(f"interval must be >= {_MIN_INTERVAL_S}s")
        with self._lock:
            self.interval_seconds = float(seconds)

    def set_method(self, method: Method) -> None:
        if method not in ("mouse", "key", "both"):
            raise ValueError(f"invalid method: {method}")
        with self._lock:
            self.method = method

    def start(self) -> None:
        with self._lock:
            if self._state.running:
                return
            self._stop.clear()
            self._state.running = True
            prevent_sleep()
            self._thread = threading.Thread(
                target=self._run, name="zig-jiggler", daemon=True
            )
            self._thread.start()
        self._notify()
        log.info("jiggler started method=%s interval=%.1fs", self.method, self.interval_seconds)

    def stop(self) -> None:
        with self._lock:
            if not self._state.running:
                return
            self._state.running = False
            self._stop.set()
            t = self._thread
            self._thread = None
        if t is not None:
            t.join(timeout=5.0)
        try:
            allow_sleep()
        finally:
            self._notify()
            log.info("jiggler stopped")

    def _next_delay(self) -> float:
        with self._lock:
            base = self.interval_seconds
        spread = base * _JITTER_RATIO
        delay = base + random.uniform(-spread, spread)
        return max(_MIN_INTERVAL_S, delay)

    def _do_jiggle(self) -> None:
        with self._lock:
            method = self.method
            px = self.jitter_pixels

        if method in ("mouse", "both"):
            send_mouse_jitter(+px, 0)
            if self._stop.wait(_CORRECTION_DELAY_S):
                return
            send_mouse_jitter(-px, 0)

        if method in ("key", "both"):
            send_f15()

        idle = None
        try:
            idle = float(get_idle_seconds())
        except Exception:
            log.exception("get_idle_seconds failed")

        with self._lock:
            self._state.last_jiggle_at = time.time()
            self._state.last_idle_seconds = idle
            self._state.tick_count += 1

        if idle is not None and idle > 2.0:
            log.warning("post-jiggle idle=%.2fs (expected ~0)", idle)
        else:
            log.debug("jiggle ok idle=%s", idle)

        self._notify()

    def _run(self) -> None:
        try:
            self._do_jiggle()
            while not self._stop.is_set():
                if self._stop.wait(self._next_delay()):
                    break
                self._do_jiggle()
        except Exception:
            log.exception("jiggler loop crashed")
        finally:
            with self._lock:
                self._state.running = False
            try:
                allow_sleep()
            except Exception:
                log.exception("allow_sleep failed during cleanup")

    def _notify(self) -> None:
        cb = self.on_state_change
        if cb is None:
            return
        try:
            cb(self.state)
        except Exception:
            log.exception("on_state_change callback failed")
