"""User-facing 'What's New' window shown when a new release is available.

Replaces the old toast-plus-auto-browser-open behavior with a real
dialog that summarizes the release notes in plain English and gives
the user three explicit choices: Download, Remind me later, or Skip
this version.

Pure stdlib (tkinter + ttk) so the PyInstaller bundle stays small.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger("zig.whats_new")

Choice = Literal["download", "later", "skip"]

# Conventional-commit prefix → user-friendly bucket
_CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("Added",   ("feat", "add")),
    ("Fixed",   ("fix", "bug", "hotfix")),
    ("Changed", ("refactor", "perf", "style", "chore", "ci", "build")),
    ("Removed", ("remove", "drop")),
    ("Docs",    ("docs", "doc")),
]


@dataclass
class _ParsedNotes:
    sections: dict[str, list[str]]   # "Added" → ["Nice popup window", ...]
    other:    list[str]              # Lines that didn't match a known prefix


def parse_release_notes(markdown: str) -> _ParsedNotes:
    """Turn GitHub's auto-generated release-notes markdown into clean,
    categorized bullet text.

    GitHub's format looks like::

        ## What's Changed
        * feat: nice popup window by @calebohara in #5
        * fix: typo in tray tooltip by @calebohara in #6

        **Full Changelog**: https://github.com/.../compare/v0.3.0...v0.3.1

    We strip the boilerplate, drop the "by @user in #N" attribution,
    map conventional-commit prefixes to friendly buckets, and group
    everything that didn't fit under "Other notes".
    """
    sections: dict[str, list[str]] = {label: [] for label, _ in _CATEGORIES}
    other: list[str] = []

    # Drop the "Full Changelog" trailer entirely — the Download button
    # gets the user to a richer view than that one URL anyway.
    text = re.sub(r"\*\*Full Changelog\*\*:.*", "", markdown, flags=re.IGNORECASE)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip section headers (## What's Changed, ### New Contributors, etc.)
        if line.startswith("#"):
            continue
        # Strip leading bullets and asterisks
        line = re.sub(r"^[\*\-•]\s*", "", line)
        # Strip "by @user in #N" attribution
        line = re.sub(r"\s+by\s+@\S+(?:\s+in\s+#\d+)?\s*$", "", line)
        # Strip trailing PR refs without "by" prefix
        line = re.sub(r"\s+in\s+#\d+\s*$", "", line)
        # Strip remaining markdown emphasis
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = line.strip()
        if not line:
            continue

        bucket = _classify(line)
        if bucket is None:
            other.append(line)
        else:
            sections[bucket].append(_strip_prefix(line))

    return _ParsedNotes(sections=sections, other=other)


_MAX_LINE_LEN = 200


def _classify(line: str) -> str | None:
    head = line.split(":", 1)[0].strip().lower()
    head = head.rstrip("!")  # conventional-commit breaking-change marker (e.g. "feat!:")
    head = re.sub(r"\(.*\)$", "", head).strip()  # strip "feat(scope)"
    for label, prefixes in _CATEGORIES:
        if head in prefixes:
            return label
    return None


def _strip_prefix(line: str) -> str:
    """Strip 'feat: ', 'fix(scope): ', 'feat!: ' — bucket already conveys type.
    Truncate ridiculously long lines so the window stays tidy.
    """
    cleaned = re.sub(r"^[a-zA-Z]+(\([^)]*\))?!?\s*:\s*", "", line).strip()
    if len(cleaned) > _MAX_LINE_LEN:
        cleaned = cleaned[: _MAX_LINE_LEN - 1].rstrip() + "…"
    return cleaned


def show_whats_new(
    *,
    current_version: str,
    latest_version: str,
    release_notes: str,
    release_url: str,
) -> Choice:
    """Open a modal 'What's New' window. Blocks until the user clicks a
    button or closes the window. Returns the choice as a string so the
    caller can decide whether to skip, remind later, or download.

    Falls back to "later" on any tkinter import/runtime failure (e.g.
    headless CI), so callers don't need to special-case the import.
    """
    try:
        return _show(current_version, latest_version, release_notes, release_url)
    except Exception:
        log.exception("whats_new window failed; defaulting to 'later'")
        try:
            webbrowser.open(release_url)
        except Exception:
            pass
        return "later"


_CHOICE_EXIT_CODES: dict[Choice, int] = {"download": 0, "later": 1, "skip": 2}
_EXIT_TO_CHOICE: dict[int, Choice] = {v: k for k, v in _CHOICE_EXIT_CODES.items()}


def run_subprocess_dialog() -> int:
    """Entry point invoked by the launcher's `--whats-new` flag.

    Reads a JSON payload from stdin, shows the modal, and exits with the
    user's choice mapped to an exit code (0=download, 1=later, 2=skip,
    3=error). This is what tray.py spawns as a child process so tkinter
    runs on its OWN main thread instead of a daemon background thread —
    which is undefined behavior on macOS and a silent corrupter on Windows.
    """
    import json

    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        log.exception("whats_new subprocess: bad stdin JSON")
        return 3
    try:
        choice = show_whats_new(
            current_version=str(payload["current_version"]),
            latest_version=str(payload["latest_version"]),
            release_notes=str(payload.get("release_notes", "")),
            release_url=str(payload["release_url"]),
        )
    except Exception:
        log.exception("whats_new subprocess: show failed")
        return 3
    return _CHOICE_EXIT_CODES.get(choice, 3)


def _resolve_subprocess_argv() -> list[str]:
    """When frozen by PyInstaller sys.executable IS the bundle, so
    `[bundle, "--whats-new"]` re-launches into our own --whats-new branch.
    In dev (not frozen) sys.executable is python; we need to pass the
    launcher script as argv[1].
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--whats-new"]
    # Dev: re-invoke ourselves via `python <launcher> --whats-new`.
    # sys.argv[0] is the launcher script that originally started this
    # process, which knows how to dispatch --whats-new.
    return [sys.executable, sys.argv[0], "--whats-new"]


def launch_whats_new_subprocess(
    *,
    current_version: str,
    latest_version: str,
    release_notes: str,
    release_url: str,
    timeout: float = 1800.0,
) -> Choice:
    """Spawn the dialog as a child process. Returns the user's choice.

    Falls back to "later" + opens the browser if the subprocess fails to
    start or never produces a usable exit code.
    """
    import json

    payload = json.dumps({
        "current_version": current_version,
        "latest_version": latest_version,
        "release_notes": release_notes,
        "release_url": release_url,
    })

    try:
        proc = subprocess.Popen(
            _resolve_subprocess_argv(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        log.exception("whats_new: failed to spawn subprocess")
        try:
            webbrowser.open(release_url)
        except Exception:
            pass
        return "later"

    try:
        proc.communicate(input=payload.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        log.warning("whats_new subprocess timed out; killing")
        proc.kill()
        return "later"
    except Exception:
        log.exception("whats_new subprocess communicate failed")
        return "later"

    choice = _EXIT_TO_CHOICE.get(proc.returncode, "later")
    if proc.returncode not in _EXIT_TO_CHOICE:
        log.warning("whats_new subprocess exited with %d (treating as 'later')", proc.returncode)
    return choice


# Re-export for callers that haven't migrated yet (kept private to
# discourage new direct uses — the subprocess path is now the right one).
show_whats_new_async = None  # type: ignore[assignment]


def _show(current: str, latest: str, notes: str, url: str) -> Choice:
    import tkinter as tk
    from tkinter import ttk

    parsed = parse_release_notes(notes)

    choice: dict[str, Choice] = {"value": "later"}

    root = tk.Tk()
    root.title("noidle.app — What's New")
    root.geometry("520x440")
    root.minsize(440, 320)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    style = ttk.Style(root)
    if "vista" in style.theme_names() and sys.platform == "win32":
        style.theme_use("vista")

    header = ttk.Frame(root, padding=(18, 16, 18, 4))
    header.pack(fill="x")
    ttk.Label(header, text="✨ Update available", font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(
        header,
        text=f"v{latest}  ·  you're running v{current}",
        foreground="#666",
    ).pack(anchor="w", pady=(2, 0))

    body = ttk.Frame(root, padding=(18, 6))
    body.pack(fill="both", expand=True)

    text = tk.Text(
        body,
        wrap="word",
        height=14,
        relief="flat",
        background="#fafafa",
        font=("Segoe UI", 10),
        padx=12,
        pady=10,
    )
    scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    text.tag_configure("section", font=("Segoe UI", 10, "bold"), spacing1=8, spacing3=4)
    text.tag_configure("bullet", lmargin1=18, lmargin2=32, spacing1=2)
    text.tag_configure("empty", foreground="#999", font=("Segoe UI", 10, "italic"))

    rendered_anything = False
    for label, _ in _CATEGORIES:
        items = parsed.sections.get(label, [])
        if not items:
            continue
        rendered_anything = True
        text.insert("end", f"{label}\n", "section")
        for item in items:
            text.insert("end", f"  • {item}\n", "bullet")

    if parsed.other:
        rendered_anything = True
        text.insert("end", "Other notes\n", "section")
        for item in parsed.other:
            text.insert("end", f"  • {item}\n", "bullet")

    if not rendered_anything:
        text.insert("end", "(No release notes provided.)\n", "empty")

    text.configure(state="disabled")

    footer = ttk.Frame(root, padding=(18, 8, 18, 16))
    footer.pack(fill="x")

    def _click(c: Choice) -> None:
        choice["value"] = c
        root.destroy()

    ttk.Button(footer, text="Skip this version",
               command=lambda: _click("skip")).pack(side="left")
    ttk.Button(footer, text="Remind me later",
               command=lambda: _click("later")).pack(side="right", padx=(8, 0))
    download_btn = ttk.Button(footer, text="Download",
                              command=lambda: _click("download"))
    download_btn.pack(side="right")
    download_btn.focus_set()

    root.protocol("WM_DELETE_WINDOW", lambda: _click("later"))
    root.bind("<Return>", lambda _e: _click("download"))
    root.bind("<Escape>", lambda _e: _click("later"))

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 3}")

    root.mainloop()

    result = choice["value"]
    if result == "download":
        try:
            webbrowser.open(url)
        except Exception:
            log.exception("opening release URL failed")
    return result


def mock_for_preview() -> dict[str, str]:
    """Return arguments for show_whats_new() with realistic mock data.
    Used by the tray's 'Preview update dialog' debug menu item so users
    (and developers) can see what the window looks like without waiting
    for a real release.
    """
    return {
        "current_version": "0.3.0",
        "latest_version": "0.3.99",
        "release_notes": (
            "## What's Changed\n"
            "* feat: nice 'What's New' window with friendly changelog by @calebohara in #5\n"
            "* feat: skip-this-version preference persists across launches by @calebohara in #5\n"
            "* fix: tray tooltip showed stale tick count after pause by @calebohara in #6\n"
            "* chore: pin WiX to v4.0.5 for stable MSI builds by @calebohara in #4\n"
            "* docs: friendlier README copy by @calebohara in #3\n"
            "\n"
            "**Full Changelog**: https://github.com/calebohara/noidle.app/compare/v0.3.0...v0.3.99\n"
        ),
        "release_url": "https://github.com/calebohara/noidle.app/releases/latest",
    }
