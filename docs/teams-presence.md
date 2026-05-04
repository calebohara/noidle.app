# Microsoft Teams Presence: Technical Brief for `mouse_ziggler`

Authoritative source: [Microsoft Learn — User presence in Teams](https://learn.microsoft.com/en-us/microsoftteams/presence-admins) (last updated Feb 2026).

## 1. Presence states

Per Microsoft Learn, states split into **user-configured** and **app-configured**:

| State | Color | Set by |
|---|---|---|
| Available | Green | User OR app (idle reset) |
| Busy / In a call / In a meeting | Red | App (calendar/call) — user can also pick Busy |
| Do Not Disturb / Presenting / Focusing | Red | User (DND); App (Presenting, Focusing via MyAnalytics) |
| Away | Yellow | **App (idle, lock, sleep)** OR user |
| Be Right Back | Yellow | User only — never auto-set |
| Appear Offline | Gray | User |
| Offline | Gray | App (no device logged in) |

Aggregated priority order (most → least available): Available, Busy, In a meeting, In a call, DND, BRB, Away, Offline.

## 2. Auto-Away threshold

Default is **~5 minutes of system idle time**. Microsoft has not exposed this as a tenant or user policy — confirmed across 2024–2026 Q&A threads on learn.microsoft.com. New Teams (post-2024 WebView2 client) trips faster than classic Teams in practice. After lock, status moves Away immediately, then to Offline at ~15 minutes.

## 3. What Teams actually polls

New Teams (2024+, WebView2/React, `ms-teams.exe`) uses **OS-level idle detection** — keyboard *and* mouse input measured against the system idle counter, i.e. the value returned by `GetLastInputInfo`. This is system-wide (not Teams-window-scoped), which is why any synthetic input that reaches the OS input queue resets the timer. There is no separate Teams input hook or WMI poll; the prevailing reverse-engineering consensus (Medium/dev.to writeups on the WebView2 architecture) is that Teams reads `GetLastInputInfo` from the native shell process and forwards the idle state to the WebView. Critically: **the system idle counter does not advance while a session is locked, but lock itself forces Away regardless of input.**

## 4. Calendar integration

A scheduled Outlook meeting marks the user **In a meeting (Busy)** and a jiggler will **not** override it. Calendar-driven states sit higher in the precedence stack than app-idle Available. This is by design: less-available states win.

## 5. Manual override behavior

A user-set Available is treated as a session-level preference but **automatic signals can still demote it**: lock/sleep/calendar will pull status to Away or In a meeting. Manual durations expire after 1 day (Busy/DND) or 7 days (others). Manual Available cannot be "pinned" against the idle timer.

## 6. Edge cases that defeat naive jigglers

- **Win+L lock** — Teams flips to Away **immediately**, regardless of input injection. Idle counter freezes while locked. **A jiggler cannot beat this.**
- **RDP disconnect** — session continues server-side; Teams running in the RDP session keeps last input timestamp until the session is reaped or the box sleeps.
- **Lid close** — triggers sleep → Offline within minutes (sleep policy dependent).
- **Multi-device** — presence aggregates from the **most-recently-active** device (DND > Busy > Available > Away). A green mobile session masks a yellow desktop.

## 7. README guidance

Be explicit with users:
- Works for: idle-only Away on an unlocked, awake desktop session.
- Does **not** work for: locked workstation, sleep, lid-close, calendar-driven Busy, admin DND policies.
- For lock-defeat, document that the only reliable workaround is preventing the lock itself (power policy / Caps-Lock clip / hardware jiggler) — and flag the security tradeoff.
