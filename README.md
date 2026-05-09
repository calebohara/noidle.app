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

Want to verify the binary you just downloaded? Every release ships a `SHA256SUMS.txt` and [cosign](https://docs.sigstore.dev/) signatures (`.sig` + `.pem`). See **[SIGNING.md](SIGNING.md)** for the one-liner verify commands.

<!-- LATEST_RELEASE_START -->
<!-- This block is auto-updated by .github/workflows/update-readme.yml on every release. -->

### Latest release: [`v0.3.8`](https://github.com/calebohara/noidle.app/releases/tag/v0.3.8) — v0.3.8
Published: `2026-05-09T21:26:30Z`

<details>
<summary>Release notes</summary>

### Security

* **HIGH-1 fixed** — symlink/junction attack on log directory writes: `path.is_symlink()` guard added in `logging_setup.py` and `noidle.py _crash_log_path()`. A pre-positioned attacker who turned `%LOCALAPPDATA%\noidle\` into a junction could no longer weaponize noidle as an arbitrary file-write primitive.
* **HIGH-2 fixed** — all GitHub Actions in `build.yml`, `lint.yml`, and `update-readme.yml` pinned to immutable commit SHAs (was: mutable major-version tags). Supply-chain compromise via re-pointed upstream tag is no longer possible.

### Added

* **Full pytest suite** — 5 new platform-independent test modules covering updater (version comparison, URL safety, rate limiting), hotkey parsing, config coercion + round-trips, whats_new parsing, and jiggler API validation. Runs on Linux/macOS/Windows CI with no Win32 calls.
* **Version consistency smoke check** — `_smoke()` now reads `pyproject.toml` via `tomllib` and asserts `zig.__version__` matches. Catches accidental version drift before a PyInstaller bundle ships.
* **Landing page: Open Graph image** — `og:image` was a `data:` URI (universally rejected by social crawlers). Now served as `https://noidle.app/og.svg` — social previews work on X, LinkedIn, Slack, iMessage.
* **Landing page: CSP + X-Frame-Options** — added to `vercel.json` headers.
* **Landing page: live taskbar clock** — date element now also updates in real time.

### Fixed

* `jiggler.start()` state corruption — `_state.running 

</details>

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

- **▶ Start / ⏸ Pause** — also bound to the global hotkey **Ctrl+Alt+Z** (rebindable in `config.json` to any `a`–`z` or `f1`–`f24`; `f13`–`f24` are the safest because no app uses them)
- **Interval** — 15s, 30s, 45s, 60s, 90s, 2m, 5m, 10m, 30m (or any custom value via `config.json` — appears as "Custom (Ns)" in the menu)
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

### Run the test suite

The `tests/` directory contains platform-independent pytest tests that run on Linux, macOS, and Windows (no Win32 calls — safe for CI runners):

```bash
pip install pytest
pytest tests/ -v
```

Covers: version comparison, URL safety, rate limiting, config coercion + round-trips, hotkey parsing, release-note parsing, and jiggler API validation.

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

This goes away once the project has an Authenticode code-signing certificate. We've applied to the [SignPath.io OSS Foundation](https://signpath.io/foundation) for one (free for qualifying open-source projects); see [SECURITY.md](SECURITY.md) for status.

In the meantime, every release ships:
- **`SHA256SUMS.txt`** — verify with `Get-FileHash` (PowerShell) or `sha256sum`
- **[Cosign keyless signatures](https://docs.sigstore.dev/)** (`.sig` + `.pem`) — cryptographic proof the binary was built by THIS repo's tagged release on GitHub Actions, anchored in the public Sigstore Rekor transparency log

Full instructions in **[SIGNING.md](SIGNING.md)**. Source is in this repo — read it. You can also upload the `.exe` to [VirusTotal](https://www.virustotal.com/) before running.

---

## Architecture

```
src/zig/
├── __init__.py      # __version__ — single source of truth for version
├── winapi.py        # ctypes wrappers: SendInput, SetThreadExecutionState, GetLastInputInfo, GetTickCount64
├── jiggler.py       # threaded engine, ±20% interval randomization, adaptive smart-pause
├── tray.py          # pystray UI, dynamic icon, runtime config, bounded shutdown watchdog
├── config.py        # atomic JSON persistence (%APPDATA%\noidle\config.json), thread-safe
├── autostart.py     # HKCU\Run toggle, install-mode aware (MSI vs portable distinct values)
├── activity.py      # smart-pause + Teams screen-share detection (cached WinDLL binding)
├── logging_setup.py # rotating log file in %LOCALAPPDATA%\noidle\ (symlink-safe)
├── updater.py       # GitHub Releases poll, URL whitelist, 6h/24h rate limit
├── hotkey.py        # global hotkey (Win32 RegisterHotKey), per-instance ID, F1–F24 supported
├── stats.py         # uptime + tick counters, thread-safe
└── whats_new.py     # tk subprocess dialog for updates + critical alerts (HiDPI-aware)
noidle.py            # entry point — `python noidle.py` or PyInstaller bundle, single-instance mutex
tests/
├── conftest.py          # adds src/ to sys.path
├── test_config.py       # coercion rules, load/save round-trips, corrupt JSON fallback
├── test_hotkey.py       # parse_hotkey: valid combos, F-key range, error paths
├── test_jiggler.py      # Jiggler API surface, set_interval/set_method validation
├── test_updater.py      # version comparison, URL safety, rate limiting, is_offerable
└── test_whats_new.py    # parse_release_notes: categories, trailer stripping, attribution removal
public/
├── index.html       # landing page — single-file, no build step
├── og.svg           # Open Graph social preview image (1200×630)
└── robots.txt       # crawler directives
```

Deep dives:
- [docs/windows-internals.md](docs/windows-internals.md) — every Win32 call, why it's necessary, and the gotchas
- [docs/teams-presence.md](docs/teams-presence.md) — how Teams determines presence and where input-based tools hit a wall
- [docs/hid-vs-software.md](docs/hid-vs-software.md) — software vs kernel vs hardware injection, and the EDR detection story
- [docs/release.md](docs/release.md) — how to cut a release
- [SECURITY.md](SECURITY.md) — open audit findings and threat model
- [SIGNING.md](SIGNING.md) — verifying release binaries

---

## Building yourself

A push of a tag like `v0.3.7` triggers `.github/workflows/build.yml`, which runs on a `windows-latest` GitHub Actions runner, builds with PyInstaller, packages a per-user MSI with WiX v4, generates SHA256 checksums + cosign keyless signatures, and attaches all artifacts to a GitHub Release. To build the `.exe` locally on Windows:

```powershell
pip install "pyinstaller==6.11.1"
python scripts/make_icon.py   # only if assets/icon.ico is missing
pyinstaller --onefile --noconsole --name noidle --icon assets/icon.ico `
            --add-data "assets;assets" --paths src `
            --collect-submodules zig `
            noidle.py
```

Output: `dist/noidle.exe`.

---

## Security & known issues

The codebase has been through a deep audit — 5 specialist reviewers, 119 findings across concurrency, security, Win32, packaging, and UX. As of v0.3.7 + post-release fixes, **43 critical/high audit findings have been resolved** across v0.3.4–v0.3.7:

- **v0.3.4 (11 fixes)**: tkinter-on-thread crash → subprocess; shell injection in update-readme.yml; URL scheme whitelist; rate-limited update checks; "Skip this version" floor semantics; hotkey-failure visibility; smoke gate for empty release notes.
- **v0.3.5 (15 fixes)**: GetTickCount64 (no 49.7d wraparound); F1–F24 hotkey support; single-instance mutex; atexit cleanup so Ctrl+C doesn't pin the system awake; HiDPI-aware dialogs; bounded shutdown watchdog; install-mode-aware skipped_version floor.
- **v0.3.6 + v0.3.7 (15 fixes)**: install-mode-aware autostart (MSI vs portable distinct registry values, no more collisions); cosign keyless signing for every release artifact via GitHub OIDC; SHA256SUMS.txt for tamper-evidence; startup-critical alerts use Tk dialog instead of Focus-Assist-swallowed tray balloons.
- **v0.3.8 (2 security fixes + reliability)**: HIGH-1 symlink/junction guard on log directory writes (`logging_setup.py`, `noidle.py`); HIGH-2 all GitHub Actions SHA-pinned to commit SHAs across all three workflow files.

Additional reliability fixes on main (not audit items): `jiggler.start()` state corruption on `prevent_sleep()` failure; `HotkeyListener` registration timeout race; `packaging` library added to dependencies (fixes pre-release version comparison in updater fallback path); smoke test `assert` statements hardened against `python -O`; version consistency check added.

Remaining open items are tracked in [SECURITY.md](SECURITY.md):
- **CRIT-A** — Authenticode code signing (still open; cosign + SHA256 are shipped, but SmartScreen needs Authenticode). [SignPath.io OSS](https://signpath.io/foundation) application is the path forward.
- **CRIT-C** — Focus Assist swallows informational tray balloons (low impact; the *important* alerts now use Tk dialogs).

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

Built with parallel specialist engineers: Windows internals, Teams presence, HID hardware, app architecture, Windows release pipeline, plus persistence, autostart, smart-pause, logging, updater, hotkey, stats, and MSI packaging. See commit history for the breakdown.
