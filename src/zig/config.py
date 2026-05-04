from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger("zig.config")

# Process-wide lock for save(). Multiple threads (tray menu callbacks +
# the What's New worker writing skipped_version) can race in here; without
# a lock the JSON on disk can be a half-merged mix of two threads' Config
# snapshots.
_save_lock = threading.Lock()

_APP_DIR_NAME = "noidle"
_CONFIG_FILENAME = "config.json"
_VALID_METHODS = ("mouse", "key", "both")
_MIN_INTERVAL_S = 1.0
_DEFAULT_INTERVAL_S = 45.0
_DEFAULT_METHOD = "both"


@dataclass
class Config:
    interval_seconds: float = 45.0
    method: str = "both"
    smart_pause: bool = True
    pause_on_screen_share: bool = True
    autostart: bool = False
    check_for_updates: bool = True
    hotkey: str = "ctrl+alt+z"
    # skipped_version is a *floor*: when CURRENT_VERSION >= skipped_version,
    # the skip is auto-cleared so the user is re-prompted on the next jump.
    # Stored as a dotted string ("0.4.0"); empty means "no skip in effect".
    skipped_version: str = ""
    # Update-check rate limiting (UTC unix timestamps, 0 = never).
    last_update_check_at: float = 0.0
    last_update_check_failed: bool = False


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
    return root / _APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / _CONFIG_FILENAME


def _coerce(raw: dict) -> Config:
    allowed = {f.name for f in fields(Config)}
    cleaned = {k: v for k, v in raw.items() if k in allowed}
    cfg = Config(**cleaned)

    if cfg.method not in _VALID_METHODS:
        log.warning("invalid method=%r in config; falling back to %r", cfg.method, _DEFAULT_METHOD)
        cfg.method = _DEFAULT_METHOD

    try:
        cfg.interval_seconds = float(cfg.interval_seconds)
    except (TypeError, ValueError):
        log.warning("invalid interval_seconds=%r; falling back to %.1f", cfg.interval_seconds, _DEFAULT_INTERVAL_S)
        cfg.interval_seconds = _DEFAULT_INTERVAL_S

    if cfg.interval_seconds < _MIN_INTERVAL_S:
        log.warning("interval_seconds=%.3f < %.1f; falling back to %.1f", cfg.interval_seconds, _MIN_INTERVAL_S, _DEFAULT_INTERVAL_S)
        cfg.interval_seconds = _DEFAULT_INTERVAL_S

    cfg.smart_pause = bool(cfg.smart_pause)
    cfg.pause_on_screen_share = bool(cfg.pause_on_screen_share)
    cfg.autostart = bool(cfg.autostart)
    cfg.check_for_updates = bool(cfg.check_for_updates)
    cfg.hotkey = str(cfg.hotkey)

    return cfg


def load() -> Config:
    path = config_path()
    if not path.exists():
        return Config()
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("config at %s unreadable (%s); using defaults", path, e)
        return Config()
    if not isinstance(raw, dict):
        log.warning("config at %s is not a JSON object; using defaults", path)
        return Config()
    return _coerce(raw)


def save(config: Config) -> None:
    """Atomic, lock-protected save. Multiple threads (tray menu callbacks +
    What's New worker writing skipped_version) call this concurrently; the
    process-wide _save_lock ensures the on-disk JSON is never a half-merged
    interleave of two snapshots.
    """
    with _save_lock:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        data = json.dumps(asdict(config), indent=2, sort_keys=True)
        with tmp.open("w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        log.debug("config saved to %s", path)


# INTEGRATION: tray.py / __main__.py / jiggler.py wiring for v0.2.0
# INTEGRATION: __main__.py — load on startup and pass into Jiggler:
# INTEGRATION:   from .config import load as load_config, save as save_config
# INTEGRATION:   cfg = load_config()
# INTEGRATION:   jiggler = Jiggler(interval_seconds=cfg.interval_seconds, method=cfg.method)
# INTEGRATION:   tray = Tray(jiggler=jiggler, config=cfg, on_config_change=save_config)
# INTEGRATION:
# INTEGRATION: tray.py — call save_config(cfg) whenever the user toggles a menu item:
# INTEGRATION:   def _on_set_method(self, method: str) -> None:
# INTEGRATION:       self.jiggler.set_method(method); self.config.method = method
# INTEGRATION:       save_config(self.config)
# INTEGRATION:   def _on_set_interval(self, seconds: float) -> None:
# INTEGRATION:       self.jiggler.set_interval(seconds); self.config.interval_seconds = seconds
# INTEGRATION:       save_config(self.config)
# INTEGRATION:   Same pattern for smart_pause, pause_on_screen_share, autostart,
# INTEGRATION:   check_for_updates, hotkey — mutate self.config then save_config(self.config).
# INTEGRATION:
# INTEGRATION: tray.py "Open log folder" / "Open config folder" menu item:
# INTEGRATION:   from .config import config_path
# INTEGRATION:   os.startfile(config_path().parent)   # Windows
# INTEGRATION:
# INTEGRATION: jiggler.py — no changes required; existing set_interval / set_method
# INTEGRATION:   already enforce the same MIN_INTERVAL_S=1.0 and method whitelist.
# INTEGRATION:
# INTEGRATION: hotkey module (when added) should call cfg.hotkey to read the binding;
# INTEGRATION:   parsing/normalization lives there, not here — config stays string-only.
