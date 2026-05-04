from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(name)-20s %(levelname)-7s %(message)s"
_MAX_BYTES = 1024 * 1024
_BACKUP_COUNT = 3
_HANDLER_ATTR = "_zig_file_handler"


def log_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "noidle"
    return Path.home() / ".local" / "state" / "noidle"


def _log_path() -> Path:
    return log_dir() / "zig.log"


def setup_file_logging(level: int = logging.INFO) -> Path:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    existing = getattr(root, _HANDLER_ATTR, None)
    if existing is not None:
        root.setLevel(min(root.level or level, level))
        return path

    handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.setLevel(level)

    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    setattr(root, _HANDLER_ATTR, handler)
    return path


# INTEGRATION:
# In tray.py startup (before constructing the tray icon):
#     from .logging_setup import setup_file_logging, log_dir
#     LOG_PATH = setup_file_logging()
#     LOG_DIR = log_dir()
# Add tray menu items:
#     pystray.MenuItem("Open log", lambda: os.startfile(LOG_PATH))
#     pystray.MenuItem("Open folder", lambda: os.startfile(LOG_DIR))
# On non-Windows dev, swap os.startfile for subprocess.Popen(["xdg-open", path]).
# Call setup_file_logging() exactly once at app entry; safe to call again
# (idempotent) from __main__.py if tray is launched standalone.
