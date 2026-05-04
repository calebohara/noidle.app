# Windows Internals Brief: Keeping a Machine "Active"

> Scope: technical reference for `mouse_ziggler`. Goal — keep Windows and user-mode
> presence apps (Microsoft Teams, Slack, Outlook, Skype, Discord, Lync legacy) in
> the "Available" / non-idle state without the user touching the input devices.

---

## 1. How Teams (and almost everyone else) detects idle

Microsoft Teams determines presence-idle via the standard Win32 user-input idle
counter. The single API call is:

```c
BOOL GetLastInputInfo(PLASTINPUTINFO plii);
```

`LASTINPUTINFO::dwTime` is a `DWORD` of `GetTickCount` ticks (ms since boot,
wraps every ~49.7 days) recording the most recent keyboard or mouse input event
processed by the **interactive desktop session** the calling process is attached
to. Teams polls this on a timer (commonly ~30–60 s) and compares
`GetTickCount() - dwTime` against the user's "Show me as Away when I've been
inactive for N minutes" setting (default 5 min in Teams; OS-level "Away" kicks
in around the user's screensaver / lock policy).

References:
- MSDN: `GetLastInputInfo` — <https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-getlastinputinfo>
- MSDN: `LASTINPUTINFO` struct — <https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-lastinputinfo>

Key property: **`dwTime` is updated only by the kernel raw-input path
(`win32k!xxxUpdateGlobalsForKeyboard` / `xxxUpdateGlobalsForMouse`).** Anything
that reaches the desktop input queue counts: physical HID, `SendInput`,
synthesized injected input from Remote Desktop, accessibility input. Things
that do **not** count: `SetCursorPos` alone (no input event), `mouse_event`
with no movement and no buttons (filtered), `keybd_event` to the system
without a real VK, `PostMessage(WM_MOUSEMOVE, ...)` to a window (it bypasses
the input queue), and `SetThreadExecutionState` (it touches the power
subsystem, not the input subsystem).

---

## 2. Why `SetThreadExecutionState` is necessary but NOT sufficient

```c
SetThreadExecutionState(
    ES_CONTINUOUS |
    ES_SYSTEM_REQUIRED |
    ES_DISPLAY_REQUIRED |
    ES_AWAYMODE_REQUIRED);
```

What this does:
- `ES_CONTINUOUS` — the request persists until cleared, instead of one-shot.
- `ES_SYSTEM_REQUIRED` — resets the system idle timer; prevents S3/S4 sleep.
- `ES_DISPLAY_REQUIRED` — keeps the monitor from blanking.
- `ES_AWAYMODE_REQUIRED` — on desktop SKUs, allows the box to look "off" while
  staying in S0 (mostly only honored on Media Center / certain server SKUs;
  ignored on modern client Windows but harmless).

What this does **not** do: it does not touch `LASTINPUTINFO::dwTime`. The
power subsystem and the user-input subsystem are independent. So Teams will
**still** flip you to Away because, from its perspective, you have not
generated input. You also need real input injection.

Reference:
- MSDN: `SetThreadExecutionState` — <https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate>

---

## 3. Actually resetting the idle timer: `SendInput`

`SendInput` is the only documented way to push synthetic events through
`win32k`'s raw input path so they update `LASTINPUTINFO`. The deprecated
`mouse_event` / `keybd_event` shims call into it on modern Windows.

### 3a. Mouse jitter — the filtering trap

A `MOUSEINPUT` with `dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE` and
`dx=0, dy=0` is **collapsed/filtered** by the input stack — no movement, no
counter update. Same for `MOUSEEVENTF_MOVE` with `dx=0, dy=0` relative.
You must move at least one pixel. The reliable pattern is a relative
`(+1, 0)` followed by a relative `(-1, 0)` so the cursor returns to its
origin and does not drift across the screen over hours.

```c
INPUT in = {0};
in.type = INPUT_MOUSE;
in.mi.dx = 1; in.mi.dy = 0;
in.mi.dwFlags = MOUSEEVENTF_MOVE; // relative
SendInput(1, &in, sizeof(INPUT));
in.mi.dx = -1;
SendInput(1, &in, sizeof(INPUT));
```

### 3b. Keyboard — choose a VK no app reacts to

`VK_F15` (0x7E) is the canonical choice. F13–F24 are defined VKs but no
mainstream keyboard ships them and almost no application binds them, so the
key is silently ignored at the app layer while still counting as input at
the OS layer. `VK_NONAME` (0xFC, sometimes 0xFF as `VK_OEM_FF`) is also
used by some commercial jigglers; F15 is safer because it is a fully
documented virtual key.

Send a key DOWN immediately followed by a key UP (`KEYEVENTF_KEYUP`). Hold
duration is irrelevant; what matters is that both events flow through
`SendInput`.

### 3c. The `INPUT` struct in C and ctypes

C layout (winuser.h, x64; on x86 the union members differ in size):

```c
typedef struct tagINPUT {
    DWORD type;                        // 0=mouse 1=keyboard 2=hardware
    union {
        MOUSEINPUT    mi;
        KEYBDINPUT    ki;
        HARDWAREINPUT hi;
    } DUMMYUNIONNAME;
} INPUT, *PINPUT;
```

The union must be sized to the **largest** member (`MOUSEINPUT` on x64 = 32
bytes, full `INPUT` = 40 bytes due to 8-byte alignment + the leading `type`
DWORD + 4 bytes of pad). `sizeof(INPUT)` is `28` on x86 and `40` on x64 —
this is exactly what `cb` must be in the `SendInput` call. Get this wrong
and `SendInput` returns `0` and `GetLastError() == ERROR_INVALID_PARAMETER
(87)`. The Python module pads the union explicitly; see `winapi.py`.

References:
- MSDN: `SendInput` — <https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput>
- MSDN: `INPUT` — <https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-input>
- MSDN: Virtual-Key Codes — <https://learn.microsoft.com/windows/win32/inputdev/virtual-key-codes>

---

## 4. `PowerCreateRequest` / `PowerSetRequest` — the modern path (Win7+/Win8+)

Since Windows 7 the recommended power-availability API is the
`POWER_REQUEST` family:

```c
HANDLE h = PowerCreateRequest(&reasonContext);   // REASON_CONTEXT with a string
PowerSetRequest(h, PowerRequestSystemRequired);  // and/or PowerRequestDisplayRequired
// ... work ...
PowerClearRequest(h, PowerRequestSystemRequired);
CloseHandle(h);
```

Pros vs `SetThreadExecutionState`:
- **Visible reason string** in `powercfg /requests`, so admins can audit
  who is holding the wakelock.
- **Per-request handles** — you can hold multiple distinct reasons and
  release them independently; far cleaner lifecycle than the single
  per-thread `ES_CONTINUOUS` flag.
- Survives some scenarios where `STES` is dropped (e.g. thread exit if
  you forgot `ES_CONTINUOUS`).
- `PowerRequestExecutionRequired` (Win8+) covers Modern Standby / Connected
  Standby boxes where `ES_SYSTEM_REQUIRED` no longer keeps the CPU live.

Cons:
- More boilerplate (`REASON_CONTEXT`, `DIAGNOSTIC_REASON_VERSION`, a wide
  string).
- Same fundamental limitation: it does **not** reset `LASTINPUTINFO`. You
  still need `SendInput` for presence apps.

References:
- MSDN: `PowerCreateRequest` — <https://learn.microsoft.com/windows/win32/api/powerbase/nf-powerbase-powercreaterequest>
- MSDN: `PowerSetRequest` — <https://learn.microsoft.com/windows/win32/api/powerbase/nf-powerbase-powersetrequest>
- MSDN: `REASON_CONTEXT` — <https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-reason_context>

Recommendation for `mouse_ziggler` v1: stay on `SetThreadExecutionState`
because it is one call, no struct marshaling, and we are not targeting
Modern Standby SKUs. Migrate to `PowerSetRequest` in v2 if/when we want
the audit trail.

---

## 5. Verifying the wakelock with `powercfg /requests`

From an **elevated** cmd/PowerShell:

```
powercfg /requests
```

Expected output if `SetThreadExecutionState(ES_SYSTEM_REQUIRED |
ES_DISPLAY_REQUIRED | ES_CONTINUOUS)` is active in our process:

```
DISPLAY:
[PROCESS] \Device\HarddiskVolumeN\...\python.exe

SYSTEM:
[PROCESS] \Device\HarddiskVolumeN\...\python.exe

AWAYMODE:
None.

EXECUTION:
None.

PERFBOOST:
None.

ACTIVELOCKSCREEN:
None.
```

If `mouse_ziggler.exe` (or `python.exe` while developing) shows up under
`DISPLAY` and `SYSTEM`, the power request is live. If it does not, either
the process exited, `ES_CONTINUOUS` was missing, or another `STES` call
cleared it. `powercfg /requestsoverride` lets us pin a request for a
process by name as a last-resort fallback (requires admin and a reboot to
take full effect for services).

Reference:
- MS docs: `powercfg /requests` — <https://learn.microsoft.com/windows-hardware/design/device-experiences/powercfg-command-line-options#requests>

---

## 6. Pixel-jitter pattern recommendation

Every `INTERVAL` seconds (recommend 30–45 s — comfortably under Teams' 5
min Away threshold and well under the OS lock-screen timeout):

1. `SendInput` relative mouse `(+1, 0)`.
2. `SendInput` relative mouse `(-1, 0)`.
3. `SendInput` `VK_F15` down + up.
4. Re-call `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED |
   ES_DISPLAY_REQUIRED)` defensively (cheap, idempotent).
5. Read `GetLastInputInfo` and assert `(GetTickCount() - dwTime) < 2000`.
   If not, the injection silently failed (UIPI / session 0 / locked
   workstation — see §7) and we should log and surface the error.

Net cursor drift after each cycle: **0 pixels**. The (+1, -1) pair is
visually invisible on any display ≥ 96 DPI and survives mouse acceleration
because we use raw relative units, not screen coordinates.

---

## 7. Gotchas

### 7a. RDP sessions
Inside an RDP session, `SendInput` injects into **the RDP session's input
queue**, which is what `GetLastInputInfo` reads on that session. Works
fine. If the RDP session is **disconnected** (not logged off), session 0
isolation kicks in for any helper service and `SendInput` from a
non-session process is a no-op. Run the jiggler **inside the user
session**, not as a SYSTEM service.

### 7b. Locked workstation (Win+L)
On a locked desktop the Secure Desktop owns the input queue. A user-mode
`SendInput` from the previously-active session **does not** reach the
secure desktop and **does not** advance `LASTINPUTINFO` from the locked
session's perspective. The screensaver / lock timeout policy is
independent of presence apps, but Teams running in your user session is
suspended/backgrounded while locked and presence is reported by the
server-side timeout anyway. Conclusion: jiggling cannot defeat a locked
screen, and that is a feature, not a bug. Disable the lock-screen
timeout in Group Policy if that is the actual goal.

### 7c. Session 0 isolation (running as a service)
A Windows service runs in session 0 with no interactive desktop. `SendInput`
from session 0 silently fails (`SendInput` returns 0; `GetLastError()` =
`ERROR_ACCESS_DENIED` 5). To run jiggling automatically on login, register
a **Scheduled Task** with trigger "At log on of <user>" and "Run only
when user is logged on" — this gives you a process in the user's
interactive session.

### 7d. UAC elevation
Elevation is **not required** for `SendInput` into your own session, for
`SetThreadExecutionState`, or for `GetLastInputInfo`. Elevation **is**
required for `powercfg /requests` (to see other processes' requests) and
for `powercfg /requestsoverride`. UIPI will block `SendInput` from a
medium-IL process targeting a high-IL foreground window — but since we
are not targeting a window, just the global input queue, this does not
apply. Run `mouse_ziggler` un-elevated.

### 7e. Multiple monitors / DPI
`MOUSEEVENTF_MOVE` relative is in mickeys (raw mouse units), unaffected
by DPI scaling or monitor layout. `MOUSEEVENTF_ABSOLUTE` uses a
0..65535 normalized coordinate space across the **primary** monitor only
unless you also pass `MOUSEEVENTF_VIRTUALDESK`. We use relative
exclusively — none of this matters.

### 7f. Anti-cheat / EDR detection
Some EDR products (CrowdStrike Falcon, SentinelOne) flag synthetic input
injection from non-whitelisted binaries. `SendInput` from `python.exe` is
common enough to usually pass; a packed standalone `mouse_ziggler.exe`
may earn a closer look. Sign the binary if shipping to managed fleets.

---

## 8. Summary: minimal recipe

1. On startup: `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED
   | ES_DISPLAY_REQUIRED)`.
2. Every 30–45 s: send `(+1, 0)` mouse, `(-1, 0)` mouse, `VK_F15` keystroke
   via `SendInput`.
3. Verify with `GetLastInputInfo`: `(GetTickCount() - dwTime)` should be
   < 2 s right after the jiggle.
4. On shutdown: `SetThreadExecutionState(ES_CONTINUOUS)` to clear flags.
5. Cross-check externally with `powercfg /requests` (elevated).

That recipe is implemented in `src/zig/winapi.py`.
