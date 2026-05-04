"""PyInstaller-friendly entry point.

Uses absolute imports (PyInstaller runs the entry script as a top-level
module with no parent package, which breaks `from .tray import ...`).
Adds src/ to sys.path so dev runs (`python noidle.py`) work too.

Wraps startup in a top-level exception handler that writes any crash to
%LOCALAPPDATA%\\noidle\\crash.log so users get a debuggable artifact
instead of a raw "Failed to execute script" Windows dialog.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

_HERE = Path(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
_SRC = _HERE / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _crash_log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    d = base / "noidle"
    d.mkdir(parents=True, exist_ok=True)
    return d / "crash.log"


def _write_crash(exc: BaseException) -> Path:
    p = _crash_log_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {datetime.now().isoformat()} =====\n")
        f.write(f"argv: {sys.argv!r}\n")
        f.write(f"frozen: {getattr(sys, 'frozen', False)}\n")
        f.write(f"executable: {sys.executable}\n")
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    return p


def _enumerate_zig_modules() -> list[str]:
    """Discover every src/zig/*.py module via pkgutil so the smoke test
    catches a future module that someone forgot to add to a hand-curated
    list. Mirrors what `--collect-submodules zig` does in PyInstaller.
    """
    import pkgutil
    import zig
    return sorted(
        f"zig.{m.name}"
        for m in pkgutil.iter_modules(zig.__path__)
        if not m.ispkg and not m.name.startswith("_")
    )


def _smoke() -> int:
    """Import + instantiate everything the live app touches, then exit 0.

    Catches:
      - Relative-import regressions
      - Constructor signature drift between modules
      - Missing-symbol regressions in winapi
      - send_mouse_jitter signature drift
      - Markdown parser regressions (incl. empty-release-notes case)
      - Newly-added zig.* modules failing to import in the bundle
    """
    import importlib

    # Discover and import every zig.* submodule.
    for name in _enumerate_zig_modules():
        try:
            importlib.import_module(name)
        except Exception as exc:
            print(f"smoke FAIL: cannot import {name}: {exc!r}", flush=True)
            return 4

    import zig.config
    import zig.hotkey
    import zig.jiggler
    import zig.stats
    import zig.updater
    import zig.whats_new
    import zig.winapi

    # Markdown parser sanity (categorized release body).
    parsed = zig.whats_new.parse_release_notes(
        "## What's Changed\n"
        "* feat: foo by @x in #1\n"
        "* fix: bar by @y in #2\n"
        "* feat!: breaking change baz by @z in #3\n"
    )
    assert parsed.sections["Added"] == ["foo", "breaking change baz"], parsed.sections
    assert parsed.sections["Fixed"] == ["bar"], parsed.sections

    # Empty-release-notes case (the v0.3.0/v0.3.3 actual scenario): the
    # parser must not throw and must produce an empty grouping the dialog
    # can render as "(No release notes provided.)".
    empty = zig.whats_new.parse_release_notes("")
    assert all(not v for v in empty.sections.values()), empty.sections
    assert not empty.other, empty.other

    # GitHub's just-Full-Changelog body (the "no merged PRs" case): same
    # as empty after the parser strips the trailer.
    only_changelog = zig.whats_new.parse_release_notes(
        "**Full Changelog**: https://github.com/x/y/compare/v0.3.3...v0.3.4\n"
    )
    assert all(not v for v in only_changelog.sections.values()), only_changelog.sections
    assert not only_changelog.other, only_changelog.other

    # Jiggler API surface.
    j = zig.jiggler.Jiggler(interval_seconds=10.0, method="both")
    assert j.state.running is False
    j.set_interval(20.0)
    j.set_method("mouse")
    j.set_smart_pause(False)
    j.set_pause_on_screen_share(False)
    assert j.method == "mouse"

    # Win32 surface.
    for name in ("prevent_sleep", "allow_sleep", "send_mouse_jitter",
                 "send_f15", "get_idle_seconds"):
        if not hasattr(zig.winapi, name):
            print(f"smoke FAIL: zig.winapi missing {name}", flush=True)
            return 2

    import inspect
    sig = inspect.signature(zig.winapi.send_mouse_jitter)
    if len(sig.parameters) != 0:
        print(f"smoke FAIL: send_mouse_jitter has params {sig}", flush=True)
        return 3

    # Config surface (all fields the tray expects).
    cfg = zig.config.load()
    for field_name in ("interval_seconds", "method", "smart_pause",
                       "pause_on_screen_share", "autostart", "hotkey",
                       "skipped_version", "last_update_check_at",
                       "last_update_check_failed"):
        assert hasattr(cfg, field_name), f"Config missing {field_name}"

    # Hotkey parser.
    mods, vk = zig.hotkey.parse_hotkey("ctrl+alt+z")
    assert mods != 0 and vk != 0

    # Updater rate-limit + offerable helpers.
    assert zig.updater.should_check_now(0, False) is True
    assert zig.updater.should_check_now(__import__("time").time(), False) is False
    assert zig.updater.is_offerable("0.4.0", "") is True
    assert zig.updater.is_offerable("0.4.0", "0.4.0") is False
    assert zig.updater.is_offerable("0.4.1", "0.4.0") is True
    assert zig.updater._is_safe_release_url("https://github.com/x/y/releases/tag/v1") is True
    assert zig.updater._is_safe_release_url("javascript:alert(1)") is False
    assert zig.updater._is_safe_release_url("file:///etc/passwd") is False

    # Stats.
    s = zig.stats.Stats()
    s.started()
    s.record_jiggle()
    s.record_skip("active")
    assert "Jiggles" in s.summary()
    s.reset()

    print("smoke ok", flush=True)
    return 0


def main() -> int:
    if "--smoke" in sys.argv:
        return _smoke()
    if "--version" in sys.argv:
        print("noidle.app 0.3.4", flush=True)
        return 0
    if "--whats-new" in sys.argv:
        # Subprocess entry: tkinter runs on its own main thread. Tray
        # spawns this child to show the update dialog without violating
        # tkinter's main-thread-only contract.
        from zig.whats_new import run_subprocess_dialog
        return run_subprocess_dialog()
    from zig.tray import run_tray
    run_tray()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        path = _write_crash(exc)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"noidle.app crashed.\n\nDetails written to:\n{path}\n\n{exc!r}",
                "noidle.app — crash",
                0x10,
            )
        except Exception:
            pass
        raise SystemExit(1)
