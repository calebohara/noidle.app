# HID vs. Software: How Mouse Input Is Detected on Windows

## The Three Layers of Mouse Input

Windows accepts mouse input at three layers. Ordered from "most real" to "most detectable":

### 1. HARDWARE (USB HID)
A physical USB device enumerates with a real **HID Report Descriptor** and emits standard mouse reports over USB. The OS sees an honest peripheral. Examples:
- Commercial dongles like **Vaydeer** USB jigglers
- **Arduino Pro Micro / Leonardo** flashed with HID firmware
- Any ATmega32u4 / RP2040 board running QMK or CircuitPython

There is no software flag distinguishing these reports from a real Logitech mouse. To user-mode, kernel-mode, and EDR alike, this is indistinguishable from a human moving a mouse.

### 2. KERNEL (Driver-Level Injection)
Tools like the open-source **Interception** driver inject events at the kernel input stack, *below* the layer where the `LLMHF_INJECTED` flag is stamped. To user-mode applications (including most monitoring tools), kernel injection looks identical to hardware. Detection requires kernel-callback-based EDR.

### 3. USER MODE (`SendInput`)
The Win32 `SendInput()` call is the easiest and most common approach. The OS marks every synthetic event with two flags visible in `MSLLHOOKSTRUCT.flags` to any low-level hook:
- `LLMHF_INJECTED` (0x00000001)
- `LLMHF_LOWER_IL_INJECTED` (0x00000002)

Any process that installs `SetWindowsHookEx(WH_MOUSE_LL)` can read these flags and trivially identify the input as synthetic.

## What Microsoft Teams Actually Checks

Teams uses **`GetLastInputInfo()`** to determine idleness. This API returns only the timestamp of the last input event — it does **not** distinguish injected from real input. Therefore `SendInput` is fully sufficient to keep Teams "Available." This is the v1 design assumption.

## What DOES Detect Software Jigglers

Corporate EDR / UEBA platforms — **CrowdStrike Falcon, Microsoft Sentinel, Teramind, ActivTrak, Veriato** — install low-level mouse hooks and inspect `LLMHF_INJECTED`. They flag synthetic input within seconds. If you are on a managed corporate endpoint with one of these agents, a `SendInput`-based jiggler is detectable. Be honest about this with users.

## Hardware Mode (v2 Roadmap, Out of Scope for v1)

A future "Hardware Mode" can sidestep all software-layer detection by using a $5 microcontroller as a HID device:
- **Arduino Leonardo / Pro Micro** with `Mouse.h` (built-in HID library)
- **Raspberry Pi Pico** with CircuitPython `adafruit_hid.mouse`
- **QMK firmware** for any compatible board

The host PC sees a generic HID mouse — no software flag, no driver fingerprint.

## v1 Recommendation

Ship `SendInput` with relative micro-movements (1–2 px) and an occasional **F15** keypress (a key no application binds, but which still resets the idle timer). This is sufficient against Teams' default behavior and acceptable for personal-use scenarios. **It is not stealth against EDR-monitored corporate endpoints.** Document this trade-off in the README.
