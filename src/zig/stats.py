"""Thread-safe runtime statistics for the jiggler loop."""

from __future__ import annotations

import threading
import time

__all__ = ["Stats"]


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.tick_count: int = 0
        self.skipped_active: int = 0
        self.skipped_screenshare: int = 0
        self.started_at: float | None = None
        self.last_idle_seconds: float | None = None

    def record_jiggle(self, idle_seconds: float | None = None) -> None:
        with self._lock:
            self.tick_count += 1
            if idle_seconds is not None:
                self.last_idle_seconds = idle_seconds

    def record_skip(self, reason: str) -> None:
        with self._lock:
            if reason == "active":
                self.skipped_active += 1
            elif reason == "screenshare":
                self.skipped_screenshare += 1
            else:
                raise ValueError(f"unknown skip reason: {reason!r}")

    def started(self) -> None:
        with self._lock:
            self.started_at = time.monotonic()

    def stopped(self) -> None:
        with self._lock:
            self.started_at = None

    def summary(self) -> str:
        with self._lock:
            uptime = self._format_uptime(self.started_at)
            idle = (
                f"{self.last_idle_seconds:.1f}s"
                if self.last_idle_seconds is not None
                else "n/a"
            )
            return (
                f"Uptime: {uptime}\n"
                f"Jiggles: {self.tick_count}\n"
                f"Skipped (active): {self.skipped_active}\n"
                f"Skipped (screenshare): {self.skipped_screenshare}\n"
                f"Last idle: {idle}"
            )

    @staticmethod
    def _format_uptime(started_at: float | None) -> str:
        if started_at is None:
            return "stopped"
        seconds = max(0, int(time.monotonic() - started_at))
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"


# INTEGRATION: instantiate one Stats() in JigglerTray.__init__ as
#   self.stats = Stats(); self.stats.started(). Pass it into the jiggler
#   worker (jiggler.py) so the tick loop calls stats.record_jiggle(idle)
#   on every successful injection and stats.record_skip("active") /
#   stats.record_skip("screenshare") whenever the policy decides to skip.
#   Add a "Show stats" menu item to the pystray Menu whose handler does
#   icon.notify(self.stats.summary(), title="MouseZiggler"). On quit,
#   call self.stats.stopped() before icon.stop() so a final summary read
#   shows "Uptime: stopped". Stats is internally locked, so the tray
#   thread, jiggler thread, and hotkey thread can all touch it safely.
