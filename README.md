# noidle.app

[![Build](https://github.com/calebohara/noidle.app/actions/workflows/build.yml/badge.svg)](https://github.com/calebohara/noidle.app/actions/workflows/build.yml)
[![Lint](https://github.com/calebohara/noidle.app/actions/workflows/lint.yml/badge.svg)](https://github.com/calebohara/noidle.app/actions/workflows/lint.yml)
[![Latest release](https://img.shields.io/github/v/release/calebohara/noidle.app?label=latest%20release&color=brightgreen)](https://github.com/calebohara/noidle.app/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/calebohara/noidle.app/total?color=blue)](https://github.com/calebohara/noidle.app/releases)
[![Last commit](https://img.shields.io/github/last-commit/calebohara/noidle.app)](https://github.com/calebohara/noidle.app/commits/main)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

**Stay active. Stay available.** A friendly little Windows tray app that keeps your status fresh — so the green dot in Microsoft Teams stays green, and your machine doesn't drift off into Away while you're reading, thinking, or just away from the keyboard for a minute.

It does this politely: when you're already typing, it stays out of your way. When Teams is sharing your screen, it pauses so nothing twitches in front of your audience. When you walk away, it quietly nudges Windows' input subsystem (the same one Teams checks) just enough to keep your presence current — and pins the screen and system awake so you don't lose your work to a sleep timer.

> **Heads up:** noidle.app keeps you Available while you're at the desk but stepped away from the mouse. It can't override the lock screen, an Outlook meeting on your calendar, or corporate monitoring tools that detect synthetic input. See [Honest limits](#honest-limits) below.

---

## Download

**▶ [Download noidle.exe](https://github.com/calebohara/noidle.app/releases/latest)** — single-file portable
**📦 [Download noidle.msi](https://github.com/calebohara/noidle.app/releases/latest)** — per-user installer (no admin), adds to Start Menu

Double-click. The icon lands in your system tray, right-click it to start.

<!-- LATEST_RELEASE_START -->
<!-- This block is auto-updated by .github/workflows/update-readme.yml on every release. -->
<!-- LATEST_RELEASE_END -->

---

## How it works

Every ~45 seconds (interval is configurable, randomized ±20% so the cadence doesn't look mechanical):

1. **A whisper of input** — `SendInput` nudges the cursor +1/−1 pixel as a single atomic event, then sends an invisible `VK_F15` keypress. The OS counts both as activity; nothing visible happens on screen.
2. **Wakelock** — `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)` so the display and system stay awake.
3. **Self-check** — calls `GetLastInputInfo()` right after, confirms the OS-wide idle counter actually reset. If it didn't (locked workstation, RDP disconnect, session 0), noidle writes a warning to the log instead of silently lying.

Teams, Slack, and Windows all read the same idle counter, so a fresh idle counter means a fresh presence dot.

---

## Tray controls

- **▶ Start / ⏸ Pause** — also bound to the global hotkey **Ctrl+Alt+Z**
- **Interval** — 15s, 30s, 45s, 60s, 90s, 2m, 5m
- **Method** — Mouse / Key (F15) / Both
- **Smart pause when active** — skip a tick if you're already typing or moving the mouse (no surprise cursor twitches mid-click)
- **Pause during Teams screen share** — auto-pauses while Teams is broadcasting your screen
- **Start with Windows** — adds/removes a `HKCU\Run` registry entry, no admin needed
- **Check for updates on launch** — pings the GitHub Releases API and notifies you if there's a newer version
- **Show stats** — uptime, total ticks, skipped (active / screenshare)
- **Show idle time** — current `GetLastInputInfo` reading (handy for sanity-checking)
- **Open log / Open data folder** — jumps to `%LOCALAPPDATA%\noidle\zig.log` and `%APPDATA%\noidle\`
- **Quit**

All settings persist atomically to `%APPDATA%\noidle\config.json` (write-then-rename, so a crash mid-write can't corrupt the file).

---

## From source (developers)

```powershell
git clone https://github.com/calebohara/noidle.app.git
cd noidle.app
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python noidle.py
```

### Confirming it's working
```powershell
powercfg /requests
```
You should see `noidle.exe` (or `python.exe` in dev mode) listed under **DISPLAY** and **SYSTEM**.

---

## Honest limits

What noidle.app **can** do:
- Keep Teams (and Slack, and Windows) seeing you as Available
- Keep the display from blanking and the box from sleeping
- Survive long reads, long thinking sessions, and the occasional quick coffee

What it **cannot** do (and no software-only tool can):
- **Locked workstation** (Win+L) — Teams forces Away regardless of input. By OS design.
- **Calendar-driven status** — if Outlook says you're in a meeting, Teams shows Busy.
- **Corporate EDR / UEBA** (CrowdStrike, Sentinel, Teramind, ActivTrak) — these hook `WH_MOUSE_LL` and read the `LLMHF_INJECTED` flag. They will see this for what it is. Don't run noidle.app on a managed work laptop without permission.
- **RDP disconnect** — `SendInput` doesn't fire in a disconnected session.

If you need stealth against EDR, the only honest path is hardware (a Pro Micro flashed with a HID firmware that looks like a real mouse to the OS). That's on the v2 roadmap; see [docs/hid-vs-software.md](docs/hid-vs-software.md).

---

## Antivirus & SmartScreen

PyInstaller `.exe`s are routinely flagged as suspicious by Windows Defender SmartScreen and some AV vendors. **This is a false positive driven by the bundling format**, not the contents — malware authors also use PyInstaller, so heuristics flag the wrapper.

The first time you run `noidle.exe`, expect a "Windows protected your PC" dialog:

1. Click **More info**
2. Click **Run anyway**

Until/unless the project gets a code-signing certificate (out of scope right now), this is the expected UX. For peace of mind, every release `.exe` can be inspected on [VirusTotal](https://www.virustotal.com/) before running. Full source is in this repo — read it.

---

## Architecture

```
src/zig/
├── winapi.py        # ctypes wrappers: SendInput, SetThreadExecutionState, GetLastInputInfo
├── jiggler.py       # threaded engine, ±20% interval randomization, drift-corrected
├── tray.py          # pystray UI, dynamic icon, runtime config
├── config.py        # atomic JSON persistence (%APPDATA%\noidle\config.json)
├── autostart.py     # HKCU\Run toggle for Start-with-Windows
├── activity.py      # smart-pause + Teams screen-share detection
├── logging_setup.py # rotating log file in %LOCALAPPDATA%\noidle\
├── updater.py       # GitHub Releases poll
├── hotkey.py        # global hotkey (Win32 RegisterHotKey)
└── stats.py         # uptime + tick counters
noidle.py            # entry point — `python noidle.py` or PyInstaller bundle
```

Deep dives:
- [docs/windows-internals.md](docs/windows-internals.md) — every Win32 call, why it's necessary, and the gotchas
- [docs/teams-presence.md](docs/teams-presence.md) — how Teams determines presence and where input-based tools hit a wall
- [docs/hid-vs-software.md](docs/hid-vs-software.md) — software vs kernel vs hardware injection, and the EDR detection story
- [docs/release.md](docs/release.md) — how to cut a release

---

## Building yourself

A push of a tag like `v0.3.0` triggers `.github/workflows/build.yml`, which runs on a `windows-latest` GitHub Actions runner, builds with PyInstaller, packages a per-user MSI with WiX v4, and attaches both `noidle.exe` and `noidle.msi` to a GitHub Release. To build locally on Windows:

```powershell
pip install pyinstaller
python scripts/make_icon.py   # only if assets/icon.ico is missing
pyinstaller --onefile --noconsole --name noidle --icon assets/icon.ico --add-data "assets;assets" --paths src noidle.py
```

Output: `dist/noidle.exe`.

---

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built with parallel specialist engineers: Windows internals, Teams presence, HID hardware, app architecture, Windows release pipeline, plus persistence, autostart, smart-pause, logging, updater, hotkey, stats, and MSI packaging. See commit history for the breakdown.
