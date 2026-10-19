# TODO

## Next up

- [ ] **Jailbreak controls** via our own tweak **scrcrappy-agent** (separate repo `~/source/scrcrappy-agent`, design approved 2026-10-19). ZXTouch was audited and rejected (unauthenticated root-capable socket on 0.0.0.0:6000, passwordless sudo rule, unsigned builds). The old ZXTouch plan is superseded; `scrcrappy/zxtouch.py` on the `jailbreak` branch goes away.
- [ ] Later (advanced): full terminal over SSH (OpenSSH on the phone, through `usbmux.connect(22)`).
- [ ] Later: hardware buttons (Home, lock, volume) and opening apps via scrcrappy-agent.

## Usability

- [ ] BLE link speed: since the device advertises as a keyboard (appearance 0x03C1, keyboard-first descriptor) the phone delivers ~1 report / 15 ms (was ≥125/s as a mouse), so reports are paced at 15 ms and the cursor feels a bit less immediate than at the start. Experiment: advertise as a mouse again (keep keyboard-first + LED descriptor), re-pair, re-measure throughput at 8 ms and check the Hardware Keyboard setting still appears. User decided to keep 15 ms for now (usable).
- [x] AssistiveTouch actions are now user-added custom buttons with in-app binding steps (+ on the toolbar).
- [ ] Mouse wheel doesn't scroll iOS Settings lists (works in other apps). Investigate (wheel report size/pacing? AssistiveTouch scroll mode?).
- [ ] Long, mostly-vertical cursor moves land 5–10% short of the target. Options: calibrate the vertical axis too, or correct from the video (closed loop).
- [ ] Paste types US layout, printable ASCII only; other characters are skipped. Other layouts / accented characters via Option dead keys.
- [ ] Optional `--ctrl-as-cmd`: send Ctrl as Cmd so Ctrl+C/V/A work as iPhone shortcuts.

## Verify

- [x] Custom buttons: Edit… and Remove confirmed by the user.
- [x] Saved config restores custom buttons / natural scrolling / pinned state after a restart: confirmed by the user.
- [x] Toolbar: first click acts (SDL focus click-through) and the pill hides while another app is focused: confirmed by user.
- [ ] Tooltip window may take keyboard focus on some window managers (lost keystrokes right after hovering the pill).
- [ ] ESP32 firmware has never run on real hardware (only compiled for esp32 / -c3 / -s3).
- [ ] macOS untested end to end: patched qvh (clear-halt removal), pill positioning, click-through.

## Housekeeping

- [x] `toolbar.py`: chevron constants use `\u` escapes.
- [ ] `toolbar.py`: tooltip font built twice per show.
- [ ] Laptop Bluetooth adapter was left `Pairable: yes` by early spikes (original value unknown).
