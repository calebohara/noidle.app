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


_SINGLE_INSTANCE_NAME = "Global\\noidle.app.singleinstance"


def _acquire_single_instance() -> object | None:
    """Try to acquire a process-wide named mutex. Returns the handle on
    success (caller must hold the reference for the process lifetime),
    None if another instance already holds it.

    On non-Windows, returns a sentinel so dev runs aren't blocked.
    """
    if sys.platform != "win32":
        return object()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_NAME)
        if not handle:
            return None
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            # Another instance owns it; release our handle and bail.
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:
        # Fail-open: if mutex creation hits an unexpected error, allow
        # the launch rather than locking the user out of their own app.
        return object()


def _install_cleanup_handlers() -> None:
    """Ensure prevent_sleep() is undone even on KeyboardInterrupt or a
    crash that bypasses the tray's normal shutdown. allow_sleep() is
    idempotent and safe to call many times.
    """
    import atexit
    import signal

    def _cleanup(*_a) -> None:
        try:
            from noidle.winapi import allow_sleep
            allow_sleep()
        except Exception:
            pass

    def _on_signal(*_a) -> None:
        _cleanup()
        sys.exit(130)

    atexit.register(_cleanup)
    try:
        signal.signal(signal.SIGINT, _on_signal)
    except (ValueError, OSError):
        # Not in main thread or signal not supported on this platform.
        pass
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, _on_signal)  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            pass


def _crash_log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    d = base / "noidle"
    d.mkdir(parents=True, exist_ok=True)
    if d.is_symlink():
        raise RuntimeError(f"noidle log directory is a symlink or junction: {d}")
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


def _enumerate_noidle_modules() -> list[str]:
    """Discover every src/noidle/*.py module via pkgutil so the smoke test
    catches a future module that someone forgot to add to a hand-curated
    list. Mirrors what `--collect-submodules noidle` does in PyInstaller.
    """
    import pkgutil
    import noidle
    return sorted(
        f"noidle.{m.name}"
        for m in pkgutil.iter_modules(noidle.__path__)
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
      - Newly-added noidle.* modules failing to import in the bundle
      - Version mismatch between pyproject.toml and noidle.__version__

    Uses explicit if/raise instead of bare assert so python -O cannot
    silently strip the checks and return a false-positive exit 0.

    Set NOIDLE_SMOKE_TRACE=1 in the env to print a marker before/after
    each import. Useful for CI: when a build hangs silently, the trace
    pinpoints which import didn't complete instead of leaving us with
    empty stdout. Off by default so dev runs stay quiet.
    """
    import importlib

    trace = bool(os.environ.get("NOIDLE_SMOKE_TRACE"))
    if trace:
        print("smoke: start", flush=True)

    # Discover and import every noidle.* submodule.
    for name in _enumerate_noidle_modules():
        if trace:
            print(f"smoke: importing {name}", flush=True)
        try:
            importlib.import_module(name)
        except Exception as exc:
            print(f"smoke FAIL: cannot import {name}: {exc!r}", flush=True)
            return 4
    if trace:
        print("smoke: imports done", flush=True)

    import noidle.config
    import noidle.hotkey
    import noidle.engine
    import noidle.stats
    import noidle.updater
    import noidle.whats_new
    import noidle.winapi

    # Version consistency — only runs from source; pyproject.toml is absent
    # in PyInstaller bundles so the check is silently skipped there.
    # Update BOTH pyproject.toml and src/noidle/__init__.py at each release.
    _pyproject = Path(__file__).parent / "pyproject.toml"
    if _pyproject.exists():
        import tomllib
        with _pyproject.open("rb") as _f:
            _toml_ver = tomllib.load(_f)["project"]["version"]
        from noidle import __version__ as _noidle_ver
        if _noidle_ver != _toml_ver:
            print(f"smoke FAIL: noidle.__version__={_noidle_ver!r} != pyproject.toml={_toml_ver!r}", flush=True)
            return 5

    # Markdown parser sanity (categorized release body).
    parsed = noidle.whats_new.parse_release_notes(
        "## What's Changed\n"
        "* feat: foo by @x in #1\n"
        "* fix: bar by @y in #2\n"
        "* feat!: breaking change baz by @z in #3\n"
    )
    if parsed.sections["Added"] != ["foo", "breaking change baz"]:
        raise AssertionError(f"Markdown Added wrong: {parsed.sections}")
    if parsed.sections["Fixed"] != ["bar"]:
        raise AssertionError(f"Markdown Fixed wrong: {parsed.sections}")

    # Empty-release-notes case (the v0.3.0/v0.3.3 actual scenario): the
    # parser must not throw and must produce an empty grouping the dialog
    # can render as "(No release notes provided.)".
    empty = noidle.whats_new.parse_release_notes("")
    if not all(not v for v in empty.sections.values()):
        raise AssertionError(f"Empty parse non-empty sections: {empty.sections}")
    if empty.other:
        raise AssertionError(f"Empty parse has other: {empty.other}")

    # GitHub's just-Full-Changelog body (the "no merged PRs" case): same
    # as empty after the parser strips the trailer.
    only_changelog = noidle.whats_new.parse_release_notes(
        "**Full Changelog**: https://github.com/x/y/compare/v0.3.3...v0.3.4\n"
    )
    if not all(not v for v in only_changelog.sections.values()):
        raise AssertionError(f"Changelog-only parse non-empty sections: {only_changelog.sections}")
    if only_changelog.other:
        raise AssertionError(f"Changelog-only parse has other: {only_changelog.other}")

    # Engine API surface.
    j = noidle.engine.Engine(interval_seconds=10.0, method="both")
    if j.state.running is not False:
        raise AssertionError("Engine.state.running should be False on init")
    j.set_interval(20.0)
    j.set_method("mouse")
    j.set_smart_pause(False)
    j.set_pause_on_screen_share(False)
    if j.method != "mouse":
        raise AssertionError(f"j.method should be 'mouse', got {j.method!r}")

    # Win32 surface.
    for name in ("prevent_sleep", "allow_sleep", "send_mouse_jitter",
                 "send_f15", "get_idle_seconds"):
        if not hasattr(noidle.winapi, name):
            print(f"smoke FAIL: noidle.winapi missing {name}", flush=True)
            return 2

    import inspect
    sig = inspect.signature(noidle.winapi.send_mouse_jitter)
    if len(sig.parameters) != 0:
        print(f"smoke FAIL: send_mouse_jitter has params {sig}", flush=True)
        return 3

    # Config surface (all fields the tray expects).
    cfg = noidle.config.load()
    for field_name in ("interval_seconds", "method", "smart_pause",
                       "pause_on_screen_share", "autostart", "hotkey",
                       "skipped_version", "last_update_check_at",
                       "last_update_check_failed"):
        if not hasattr(cfg, field_name):
            raise AssertionError(f"Config missing {field_name}")

    # Hotkey parser.
    mods, vk = noidle.hotkey.parse_hotkey("ctrl+alt+z")
    if not (mods != 0 and vk != 0):
        raise AssertionError(f"parse_hotkey returned zero values: mods={mods} vk={vk}")

    # Updater rate-limit + offerable helpers.
    if noidle.updater.should_check_now(0, False) is not True:
        raise AssertionError("should_check_now(0, False) should be True")
    if noidle.updater.should_check_now(__import__("time").time(), False) is not False:
        raise AssertionError("should_check_now(now, False) should be False")
    if noidle.updater.is_offerable("0.4.0", "") is not True:
        raise AssertionError("is_offerable('0.4.0', '') should be True")
    if noidle.updater.is_offerable("0.4.0", "0.4.0") is not False:
        raise AssertionError("is_offerable('0.4.0', '0.4.0') should be False")
    if noidle.updater.is_offerable("0.4.1", "0.4.0") is not True:
        raise AssertionError("is_offerable('0.4.1', '0.4.0') should be True")
    if noidle.updater._is_safe_release_url("https://github.com/x/y/releases/tag/v1") is not True:
        raise AssertionError("safe URL should be True")
    if noidle.updater._is_safe_release_url("javascript:alert(1)") is not False:
        raise AssertionError("javascript: URL should be False")
    if noidle.updater._is_safe_release_url("file:///etc/passwd") is not False:
        raise AssertionError("file: URL should be False")

    # Stats.
    s = noidle.stats.Stats()
    s.started()
    s.record_tick()
    s.record_skip("active")
    if "Ticks" not in s.summary():
        raise AssertionError(f"Stats.summary() missing 'Ticks': {s.summary()!r}")
    s.reset()

    print("smoke ok", flush=True)
    return 0


def main() -> int:
    if "--smoke" in sys.argv:
        # os._exit (not sys.exit / return) skips atexit + threading
        # shutdown. Any import-time non-daemon thread (e.g. the pystray
        # message pump on Windows) would otherwise keep the interpreter
        # alive after _smoke() succeeds, wedging CI's Start-Process -Wait.
        os._exit(_smoke())
    if "--version" in sys.argv:
        from noidle import __version__ as v
        print(f"noidle.app {v}", flush=True)
        return 0
    if "--whats-new" in sys.argv:
        # Subprocess entry: tkinter runs on its own main thread. Tray
        # spawns this child to show the update dialog without violating
        # tkinter's main-thread-only contract. NB: this child must NOT
        # acquire the single-instance mutex — the parent already owns it.
        from noidle.whats_new import run_subprocess_dialog
        return run_subprocess_dialog()
    if "--info-dialog" in sys.argv:
        # Subprocess entry for important alerts that can't rely on
        # Shell_NotifyIcon balloons (Win11 Focus Assist filters them).
        # Reads {title, message} JSON from stdin.
        from noidle.whats_new import run_info_dialog
        return run_info_dialog("", "")

    # Single-instance guard for the actual tray (not for --smoke /
    # --version / --whats-new helper invocations).
    handle = _acquire_single_instance()
    if handle is None:
        # Another tray is running — show a friendly toast (best effort)
        # and exit. We deliberately don't try to focus the existing
        # instance because pystray icons aren't focusable.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "noidle.app is already running — check your system tray.",
                    "noidle.app",
                    0x40,  # MB_ICONINFORMATION
                )
            except Exception:
                pass
        return 0

    _install_cleanup_handlers()
    # Hold a reference to `handle` for the lifetime of the process so the
    # mutex isn't released by the OS. (The cleanup handler doesn't close
    # it explicitly — when the process exits the OS reclaims the handle.)
    globals()["__single_instance_handle__"] = handle

    from noidle.tray import run_tray
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
