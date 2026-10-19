# scrcrappy — scrcpy for iOS (design)

## Intent

Using an iPhone during mobile security work is far less convenient than using an
Android phone with scrcpy. scrcrappy bridges that gap: the iPhone's screen in a
window on the computer, driven with mouse and keyboard, next to the usual tools
(Burp, Frida, terminal).

Priorities (user-ranked): **mouse control >>>> keyboard > clipboard**.

## Constraints

- Computer side runs on **Linux (Fedora)** and **macOS**. Nothing in the core may
  depend on one OS.
- Target device: iPhone X (A11), iOS ≤ 16.6.1, **Dopamine (rootless)** jailbreak.
- Phone connected by USB cable.

## Goals

1. Live video of the phone screen in a desktop window.
2. Mouse control with absolute coordinates: click = tap, drag = swipe, wheel = scroll.
3. Keyboard text input into the focused field on the phone.
4. Paste the computer's clipboard into the phone.
5. Two interchangeable input backends (user decision): **jailbreak** first,
   **ESP32 Bluetooth mouse** later for non-jailbroken devices. Auto-detect at
   startup, with a manual override flag.

## Non-goals (for now)

- Audio, recording, wireless/AirPlay video, multiple devices, web/remote UI.
- Writing our own on-device daemon (see "Decisions").
- Copying from phone clipboard to computer (later phase, if wanted).

## Anti-goals

- Noticeable lag between click and phone reaction. If it feels laggier than
  using the phone, it has failed even if it works.
- Opening any network listener on the computer side. Everything is
  local/USB.

## Decisions

| Area | Decision | Who |
|---|---|---|
| Language | Python | my call, user asked for my pick |
| Video | **quicktime_video_hack (`qvh`)**, run as a subprocess, H.264 piped out and decoded with PyAV | user (qvh), me (subprocess + PyAV) |
| Video fallback | ZXTouch's JPEG screenshot command over the same socket (slow, but works everywhere) | my call |
| Jailbreak input | Existing tweak **ZXTouch Rootless** (gitssie fork), TCP port 6000 on device | agreed: reuse, don't rewrite |
| USB transport | `pymobiledevice3` usbmux port forward, in-process (no `iproxy` needed) | my call |
| Window | pygame (SDL2, same as scrcpy) | my call |

Why not our own daemon now: ZXTouch already does touch (multitouch), text
insertion and screenshots. Reasons that would justify replacing it later:
(1) it exposes `run_shell_command` to anything on the phone that can reach
127.0.0.1:6000, which is an attack surface on a test device; (2) no clipboard, undocumented
protocol, single maintainer. The input backend sits behind one small class, so
swapping it later is local.

## How it behaves

### Mouse (jailbreak backend), my calls modelled on scrcpy
- Left down / move / up → touch down / move / up at the mapped point (finger 1).
- Wheel → short synthesized swipe at the cursor position.
- Ctrl + left drag → pinch (two fingers mirrored around the screen centre, as scrcpy).
- Hotkeys for gestures the iPhone X has no button for:
  Home = swipe up from bottom edge; App switcher = swipe up and hold.

Window coordinates are converted to normalized 0..1 coordinates, then to
whatever unit ZXTouch expects (points vs pixels, to be confirmed in phase 0
via its screen-size/scale command). Letterboxing and rotation are handled in
that one mapping function.

### Keyboard
- Printable text → ZXTouch `insert_text`.
- Backspace / Enter / arrows: **open**. `insert_text` may not cover them; phase 0
  checks. Fallbacks: `move_cursor`, or the shell command route.

### Clipboard
- Ctrl+V in the window → read computer clipboard → `insert_text` with it.
  (Same idea as scrcpy's "inject clipboard as text".) No phone-side pasteboard
  write needed.

### Startup / auto-detect
1. Find the USB device (pymobiledevice3).
2. Try connecting to ZXTouch on device port 6000 → jailbreak backend.
3. Else look for the ESP32 on a serial port → ESP32 backend (later phase).
4. `--input jailbreak|esp32` and `--video qvh|screenshot` override detection.

## Phases

0. **Spike (throwaway).** On the real iPhone X: install ZXTouch, send a tap from a
   10-line script over pymobiledevice3 forwarding; check `qvh` on Fedora shows the
   screen and find how to get its H.264 to stdout/a pipe. Record: does it work on
   this iOS, coordinate unit, latency feel, what `insert_text` handles.
   **If qvh fails on Linux:** the screenshot fallback becomes the primary path on
   Linux and we revisit video before phase 1.
1. **Viewer.** Video in a pygame window, correct aspect ratio.
2. **Mouse.** Tap, drag, scroll through ZXTouch.
3. **Keyboard + clipboard paste.**
4. **Gestures.** Home, app switcher, pinch.
5. **ESP32 backend + auto-detect.** BLE mouse firmware, relative movement,
   AssistiveTouch cursor; closed-loop correction from video only if open-loop is
   too imprecise.
6. **Maybe:** own daemon (security/clipboard), phone→computer clipboard.

## Left to the builder

- Package layout, dependency management, CLI parsing.
- How to read the host clipboard cross-platform.
- ZXTouch wire format details (read from its source).
- Tests: at least the coordinate mapping and the ZXTouch command encoding get a
  small runnable check.
