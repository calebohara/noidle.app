"""GitHub Releases update checker.

Hardened in v0.3.4:
- URL scheme/host whitelist (rejects javascript:, file://, ms-msdt:, etc.)
- Caller-controlled rate limiting via `min_check_interval` arg, so the tray
  can throttle launch-time checks against config-stored last-check timestamps
- Returns None on any network/parse failure so the tray never crashes on a
  flaky connection or hostile API response
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

CURRENT_VERSION = "0.3.4"

_RELEASES_URL = "https://api.github.com/repos/calebohara/noidle.app/releases/latest"
_ALLOWED_SCHEMES = ("https",)
_ALLOWED_HOSTS = ("github.com", "www.github.com")
_BODY_MAX_BYTES = 64 * 1024  # don't render arbitrary-size release bodies in the dialog

log = logging.getLogger("zig.updater")


@dataclass
class UpdateInfo:
    current: str
    latest: str
    url: str
    is_newer: bool
    body: str = ""  # Raw markdown release notes from GitHub
    checked_at: float = 0.0  # Unix timestamp of when this info was fetched


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


def _is_safe_release_url(url: str) -> bool:
    """Reject anything that's not an https://github.com/... URL.

    Without this, a tampered-or-attacker-controlled API response could yield
    `javascript:`, `file://`, `\\\\attacker\\share\\x.exe`, `ms-msdt:`
    (Follina-class), etc. — and `webbrowser.open()` on Windows will hand
    non-http schemes off to shell handlers.
    """
    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in _ALLOWED_SCHEMES:
        return False
    host = u.hostname or ""
    if host.lower() not in _ALLOWED_HOSTS:
        return False
    return True


def check_for_update(timeout: float = 5.0) -> Optional[UpdateInfo]:
    """Fetch the latest GitHub release and return an UpdateInfo, or None on
    any failure. The caller is responsible for rate-limiting (see
    `should_check_now`) and for honoring the user's "skip this version"
    preference (see `is_offerable`).
    """
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

    if not isinstance(payload, dict):
        return None

    tag = payload.get("tag_name")
    url = payload.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str):
        return None
    if not _is_safe_release_url(url):
        log.warning("rejecting release URL with unsafe scheme/host: %r", url)
        return None

    latest = tag.lstrip("vV").strip()
    if not latest:
        return None

    body = payload.get("body") or ""
    if not isinstance(body, str):
        body = ""
    if len(body.encode("utf-8", errors="replace")) > _BODY_MAX_BYTES:
        body = body[:_BODY_MAX_BYTES] + "\n\n…(truncated)"

    return UpdateInfo(
        current=CURRENT_VERSION,
        latest=latest,
        url=url,
        is_newer=_is_newer(latest, CURRENT_VERSION),
        body=body,
        checked_at=time.time(),
    )


# ---- Rate limiting helpers (called by tray before/after check_for_update) -- #

# Don't poll GitHub on every launch — captive portals and 60+ launches/day
# can lead to 403 rate limiting and a permanently-stuck client.
_MIN_INTERVAL_OK_S = 6 * 3600        # 6 hours after a successful check
_MIN_INTERVAL_FAIL_S = 24 * 3600     # 24 hours after a failed check (back off)


def should_check_now(last_checked_at: float, last_failed: bool, *, now: Optional[float] = None) -> bool:
    """True if enough time has passed since the last check to try again."""
    if now is None:
        now = time.time()
    if last_checked_at <= 0:
        return True
    floor = _MIN_INTERVAL_FAIL_S if last_failed else _MIN_INTERVAL_OK_S
    return (now - last_checked_at) >= floor


def is_offerable(latest: str, skipped_version: str) -> bool:
    """`skipped_version` is a *floor*: an update is offerable only if it's
    strictly newer than what the user previously skipped. When CURRENT_VERSION
    surpasses skipped_version the tray should clear the skip — that's the
    caller's responsibility, not ours.
    """
    if not skipped_version:
        return True
    return _is_newer(latest, skipped_version)
