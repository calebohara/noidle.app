# mouse_ziggler

[![Build](https://github.com/calebohara/mouse_ziggler/actions/workflows/build.yml/badge.svg)](https://github.com/calebohara/mouse_ziggler/actions/workflows/build.yml)
[![Lint](https://github.com/calebohara/mouse_ziggler/actions/workflows/lint.yml/badge.svg)](https://github.com/calebohara/mouse_ziggler/actions/workflows/lint.yml)
[![Latest release](https://img.shields.io/github/v/release/calebohara/mouse_ziggler?label=latest%20release&color=brightgreen)](https://github.com/calebohara/mouse_ziggler/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/calebohara/mouse_ziggler/total?color=blue)](https://github.com/calebohara/mouse_ziggler/releases)
[![Last commit](https://img.shields.io/github/last-commit/calebohara/mouse_ziggler)](https://github.com/calebohara/mouse_ziggler/commits/main)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

A serious Windows mouse jiggler that keeps your machine — and your Microsoft Teams presence dot — visibly **green**.

It is more than a power setting. `mouse_ziggler` injects real synthetic input through the Win32 `SendInput` API so the OS-wide idle counter (`GetLastInputInfo`) — the same counter Teams polls — actually resets. It also pins `SetThreadExecutionState` so the screen and system never sleep underneath you.

> **Heads up:** A jiggler can keep you Available while you're at the keyboard but stepped away from the mouse. It cannot defeat the lock screen, an Outlook meeting on your calendar, or corporate EDR that hooks `WH_MOUSE_LL`. See [Honest Limits](#honest-limits) below.

---

## Download

Grab the latest signed-release `.exe` from the Releases page:

**▶ [Download MouseZiggler.exe](https://github.com/calebohara/mouse_ziggler/releases/latest)** — single-file portable
**📦 [Download MouseZiggler.msi](https://github.com/calebohara/mouse_ziggler/releases/latest)** — per-user installer (no admin), adds to Start Menu

Double-click, the icon lands in your system tray, right-click it to Start.

<!-- LATEST_RELEASE_START -->
<!-- This block is auto-updated by .github/workflows/update-readme.yml on every release. -->

### Latest release: [`v0.1.2`](https://github.com/calebohara/mouse_ziggler/releases/tag/v0.1.2) — v0.1.2
Published: `2026-05-04T11:47:54Z`

<details>
<summary>Release notes</summary>

**Full Changelog**: https://github.com/calebohara/mouse_ziggler/compare/v0.1.1...v0.1.2

</details>

<!-- LATEST_RELEASE_END -->

---

## What it actually does

On every tick (default ~45s, randomized ±20% so the cadence doesn't look robotic):

1. **Mouse jitter** — `SendInput` moves the cursor `(+1, 0)`, waits 50ms, then `(-1, 0)` so it never drifts off-screen.
2. **Invisible keypress** — `VK_F15`, a key no modern app binds. The OS counts it as input; nothing visible happens.
3. **Wakelock** — `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)` so the display and system stay awake.
4. **Self-verification** — calls `GetLastInputInfo()` right after each tick. If the idle counter didn't reset (RDP disconnect, locked workstation, session 0), it logs a warning instead of silently lying.

You can flip between mouse-only, key-only, or both from the tray menu.

---

## Usage

### Tray controls
- **▶ Start / ⏸ Pause** — toggles the jiggle loop (also bound to **Ctrl+Alt+Z** global hotkey)
- **Interval** — 15s, 30s, 45s, 60s, 90s, 2m, 5m
- **Method** — Mouse / Key / Both
- **Smart pause when active** — skips the jiggle if you're already typing/mousing (no cursor twitches mid-click)
- **Pause during Teams screen share** — auto-pauses when Teams is broadcasting your screen
- **Start with Windows** — adds/removes a `HKCU\Run` registry entry, no admin needed
- **Check for updates on launch** — pings GitHub Releases; notifies if a new version is out
- **Show stats** — uptime, total jiggles, skipped (active / screenshare)
- **Show idle time** — current `GetLastInputInfo` reading (for sanity-checking)
- **Open log / Open data folder** — jumps to `%LOCALAPPDATA%\MouseZiggler\zig.log` and `%APPDATA%\MouseZiggler\`
- **Quit**

All settings persist atomically to `%APPDATA%\MouseZiggler\config.json` (survives mid-write crashes).

### From source (developers)
```powershell
git clone https://github.com/calebohara/mouse_ziggler.git
cd mouse_ziggler
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m zig
```

### Verify it's working
Open an admin PowerShell and run:
```powershell
powercfg /requests
```
You should see `MouseZiggler.exe` (or `python.exe` in dev mode) listed under **DISPLAY** and **SYSTEM**.

---

## Honest Limits

What `mouse_ziggler` **can** do:
- Keep Teams' presence dot **Available** instead of Away
- Keep the display from blanking and the box from sleeping
- Survive long reads, long thinking, long lunches at your desk

What it **cannot** do (and no software jiggler can):
- **Locked workstation** (Win+L) — Teams forces Away regardless of input. By OS design.
- **Calendar-driven status** — if Outlook says you're in a meeting, Teams shows Busy.
- **Corporate EDR / UEBA** (CrowdStrike, Sentinel, Teramind, ActivTrak) — these hook `WH_MOUSE_LL` and read the `LLMHF_INJECTED` flag. They will see this for what it is. Don't run this on a managed work laptop without permission.
- **RDP disconnect** — `SendInput` doesn't fire in a disconnected session.

If you need stealth-against-EDR, you need hardware (a Pro Micro flashed with a HID jiggler sketch). That's on the v2 roadmap; see [docs/hid-vs-software.md](docs/hid-vs-software.md).

---

## Antivirus & SmartScreen

PyInstaller `.exe`s are routinely flagged as suspicious by Windows Defender SmartScreen, and sometimes by other AV vendors. **This is a false positive driven by the bundling format**, not the contents — malware authors also use PyInstaller, so heuristics flag the wrapper.

The first time you run `MouseZiggler.exe`, expect a "Windows protected your PC" dialog:

1. Click **More info**
2. Click **Run anyway**

Until/unless the project gets a code-signing certificate (out of scope for v1), this is the expected UX. For peace of mind, every release `.exe` can be inspected on [VirusTotal](https://www.virustotal.com/) before running. The full source is in this repo — read it.

---

## Architecture

```
src/zig/
├── winapi.py    # ctypes wrappers: SendInput, SetThreadExecutionState, GetLastInputInfo
├── jiggler.py   # threaded engine, ±20% interval randomization, drift-corrected jitter
├── tray.py      # pystray UI, dynamic icon, runtime config
└── __main__.py  # entry point — `python -m zig`
```

Deep dives:
- [docs/windows-internals.md](docs/windows-internals.md) — every Win32 call, why it's necessary, and the gotchas
- [docs/teams-presence.md](docs/teams-presence.md) — how Teams determines presence and where jigglers hit a wall
- [docs/hid-vs-software.md](docs/hid-vs-software.md) — software vs kernel vs hardware injection, and the EDR detection story
- [docs/release.md](docs/release.md) — how to cut a release

---

## Building the .exe yourself

A push of a tag like `v0.1.0` triggers `.github/workflows/build.yml`, which runs on a `windows-latest` GitHub Actions runner, builds with PyInstaller, and attaches `MouseZiggler.exe` to a GitHub Release. To build locally on Windows:

```powershell
pip install pyinstaller
python scripts/make_icon.py   # only if assets/icon.ico is missing
pyinstaller --onefile --noconsole --name MouseZiggler --icon assets/icon.ico --add-data "assets;assets" src/zig/__main__.py
```

Output: `dist/MouseZiggler.exe`.

---

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built with five specialist engineers in parallel: Windows internals, Teams presence, HID hardware, app architecture, and Windows release pipeline. See commit history for the breakdown.
