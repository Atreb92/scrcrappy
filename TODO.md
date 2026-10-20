# TODO

## Next up

- [x] **Jailbreak controls**: `--mouse agent` talks to scrcrappy-agent (`~/source/scrcrappy-agent`, PROTOCOL.md); client vendored as `scrcrappy/agent_client.py`.
- [ ] Agent on the phone: check landscape taps land right (orientation 3/4 table in `geometry.py`), pinch, wheel swipe feel (`SWIPE`, hold before lift), screenshot upright in landscape.
- [ ] Agent: pairing code is shown in the terminal only, not in the window.
- [ ] Later (advanced): full terminal over SSH (OpenSSH on the phone, through `usbmux.connect(22)`).
- [ ] Later: volume buttons and opening apps via scrcrappy-agent (Home / switcher / lock are on the toolbar).

- [ ] AI control, later: phone buttons (Home / lock / switcher), single keys, pinch, "wait until the screen settles", opening apps, on-screen element lists (agent features needed for the last two).
- [ ] usbmuxd wedges (lockdown error -8) after scrcrappy's USB reset while the phone is locked; only unlocking / replugging helps. Investigate avoiding the reset or waiting for unlock.

## Usability

- [ ] BLE link speed: since the device advertises as a keyboard (appearance 0x03C1, keyboard-first descriptor) the phone delivers ~1 report / 15 ms (was ≥125/s as a mouse), so reports are paced at 15 ms and the cursor feels a bit less immediate than at the start. Experiment: advertise as a mouse again (keep keyboard-first + LED descriptor), re-pair, re-measure throughput at 8 ms and check the Hardware Keyboard setting still appears. User decided to keep 15 ms for now (usable).
- [x] AssistiveTouch actions are now user-added custom buttons with in-app binding steps (+ on the toolbar).
- [ ] Mouse wheel doesn't scroll iOS Settings lists (works in other apps). Investigate (wheel report size/pacing? AssistiveTouch scroll mode?).
- [ ] Long, mostly-vertical cursor moves land 5–10% short of the target. Options: calibrate the vertical axis too, or correct from the video (closed loop).
- [ ] Paste types US layout, printable ASCII only; other characters are skipped. Other layouts / accented characters via Option dead keys.
- [ ] Optional `--ctrl-as-cmd`: send Ctrl as Cmd so Ctrl+C/V/A work as iPhone shortcuts.

## Verify

- [ ] Packaging: release workflow, release wheel and Homebrew formula are untested — run them once the repo is on GitHub and a Mac is at hand (docs/releasing.md).
- [x] Licence: MIT (2026-10-19).
- [x] Custom buttons: Edit… and Remove confirmed by the user.
- [x] Saved config restores custom buttons / natural scrolling / pinned state after a restart: confirmed by the user.
- [x] Toolbar: first click acts (SDL focus click-through): confirmed by user (the pill is gone: the bar is part of the phone window).
- [ ] ESP32 firmware has never run on real hardware (only compiled for esp32 / -c3 / -s3).
- [ ] macOS untested end to end: patched qvh (clear-halt removal), click-through, the bar and Settings overlay.

## Wayland

- [x] Bar and Settings overlay inside the phone window (docs/superpowers/specs/2026-10-20-bar-settings-overlay-design.md).
- [x] Native Wayland by default in a Wayland session, X11 fallback / `--x11`; the right-click menu is an in-window overlay (only the Add/Edit dialog is a window).
- [ ] Wayland, not yet checked by hand: the Add/Edit dialog (compositor-placed), the window icon (needs a `scrcrappy.desktop`; the app id is `scrcrappy`), HiDPI / fractional scaling, other compositors than KDE.
- [ ] Settings panel isn't scrollable: a window shorter than about 430 px clips its bottom.
- [ ] Bar overflow: many custom buttons shrink the buttons; add an overflow menu.

## Housekeeping

- [ ] Laptop Bluetooth adapter was left `Pairable: yes` by early spikes (original value unknown).
