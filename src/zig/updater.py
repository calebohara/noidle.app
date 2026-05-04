from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

CURRENT_VERSION = "0.3.0"

_RELEASES_URL = "https://api.github.com/repos/calebohara/noidle.app/releases/latest"

log = logging.getLogger("zig.updater")


@dataclass
class UpdateInfo:
    current: str
    latest: str
    url: str
    is_newer: bool


def _parse_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return tuple(parts)
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(latest: str, current: str) -> bool:
    try:
        from packaging.version import InvalidVersion, Version

        try:
            return Version(latest) > Version(current)
        except InvalidVersion:
            pass
    except ImportError:
        pass
    return _parse_tuple(latest) > _parse_tuple(current)


def check_for_update(timeout: float = 5.0) -> Optional[UpdateInfo]:
    req = urllib.request.Request(
        _RELEASES_URL,
        headers={
            "User-Agent": f"noidle.app/{CURRENT_VERSION}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.debug("update check failed: %s", exc)
        return None

    tag = payload.get("tag_name")
    url = payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str):
        return None

    latest = tag.lstrip("vV").strip()
    if not latest:
        return None

    return UpdateInfo(
        current=CURRENT_VERSION,
        latest=latest,
        url=url,
        is_newer=_is_newer(latest, CURRENT_VERSION),
    )


# INTEGRATION:
# In tray.py, run the check on a background thread so the tray never blocks:
#     import threading, webbrowser
#     from .updater import check_for_update
#     def _check():
#         info = check_for_update()
#         if info and info.is_newer:
#             tray_notify(f"Update available: v{info.latest}",
#                         on_click=lambda: webbrowser.open(info.url))
#     threading.Thread(target=_check, daemon=True).start()
# Optional menu item: "Check for updates" -> same _check() but always notify
# (even when up-to-date) so the user gets feedback. None return = silent fail.
