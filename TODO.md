# TODO

## Next up

- [x] **Jailbreak controls**: `--mouse agent` talks to crappytouch (`~/source/crappytouch`, PROTOCOL.md); client vendored as `scrcrappy/agent_client.py`.
- [ ] Agent on the phone: check landscape taps land right (orientation 3/4 table in `geometry.py`), pinch, wheel swipe feel (`SWIPE`, hold before lift), screenshot upright in landscape.
- [ ] Agent: pairing code is shown in the terminal only, not in the window.
- [ ] Later (advanced): full terminal over SSH (OpenSSH on the phone, through `usbmux.connect(22)`).
- [x] Opening apps via crappytouch 0.3.0 (`apps` / `open`): MCP `list_apps` / `open_app` and `scrcrappy agent --apps` / `--open`. Needs the 0.3.0 agent on the phone.
- [x] Open a URL or deeplink via agent 0.5.0 (`open_url`): MCP `open_url` and `scrcrappy agent --open-url`.
- [ ] Later: volume buttons via crappytouch; an app launcher in the toolbar (Home / switcher / lock are there already).

- [x] AI control, agent mode: `home`, `switcher` and `lock` tools.
- [ ] AI control, later: single keys, pinch, "wait until the screen settles", on-screen element lists (agent feature needed for the last).
- [ ] usbmuxd wedges (lockdown error -8) after scrcrappy's USB reset while the phone is locked; only unlocking / replugging helps. Investigate avoiding the reset or waiting for unlock.

## Usability

- [x] Screenshot button in Bluetooth / ESP32 mode: saves the mirrored video frame, same in-window toast as agent mode.

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
- [x] ESP32 firmware ran on real hardware: classic ESP32 (D0WD-V3, CH340) pairs with the iPhone 8 and steers the cursor. -C3 / -S3 still untested.
- [x] macOS video: qvh cannot work there (libusb `-99` on the second context; QuickTime interface claim fails with `out of resources`, also as root), so macOS captures through AVFoundation (`video.capture_avf`, spec 2026-10-21). Mirroring and `--mouse agent` confirmed by the user.
- [ ] macOS: rotation, click-through, the bar and Settings overlay, several iPhones at once (the first capture device that is not a screen wins), `--calibrate` (its 3 s start-up wait), Homebrew formula (macOS path untested until the next release).
- [ ] Flaky tests: `tests/test_app.py` fails on some runs after the agent / AI tests (different test each time, also on `main`). Order-dependent pygame window state.

- [ ] Flatpak for Linux (bundles libusb; usbmuxd / BLE helper access need sandbox holes, so decide after pipx + brew are proven).
- [ ] Linux aarch64 and macOS wheels in CI (qvh is native); brew covers macOS until then.

## Wayland

- [x] Bar and Settings overlay inside the phone window (docs/superpowers/specs/2026-10-20-bar-settings-overlay-design.md).
- [x] Native Wayland by default in a Wayland session, X11 fallback / `--x11`; the right-click menu is an in-window overlay (only the Add/Edit dialog is a window).
- [x] Wayland: the Add/Edit dialog works (confirmed by the user).
- [ ] Wayland: the window icon comes from `packaging/scrcrappy.desktop` (app id `scrcrappy`; install steps in the README, untested); HiDPI / fractional scaling and compositors other than KDE not checked.
- [x] Settings panel scrolls with the mouse wheel when the window is shorter than it.
- [ ] Bar overflow: many custom buttons shrink the buttons; add an overflow menu.

## Housekeeping

- [ ] MCP `calibrate` waits its full 120 s (holding the one-tool-at-a-time lock) if the window is closed during a run; have a failed post end the wait.

- [ ] No test drives the main loop's event routing end to end (overlays → popups → bar → phone controller); only the pieces are tested.

- [ ] Laptop Bluetooth adapter was left `Pairable: yes` by early spikes (original value unknown).

- [ ] Settings › "Forget paired phone" (ESP32 mode only): send the board a `p` line over the serial link it already holds, confirm first, toast on the board's `pairing` reply. Needs a mockup; build after the ESP32-C3 test confirms the one-phone pairing in `firmware/esp32-mouse` works (today: `echo p > /dev/ttyUSB0` with scrcrappy closed).
- [ ] Laptop Bluetooth helper (`--mouse ble`) accepts every pairing while it runs and the bonds stay after exit; decide how to restrict it without re-pairing each run.
