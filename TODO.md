# TODO

## Next up

- [ ] **Jailbreak controls** (ZXTouch on palera1n/Dopamine): absolute taps and multitouch, phone ↔ computer clipboard, enables the toolbar's Copy button. Plan: `docs/superpowers/plans/2026-10-19-scrcrappy-jailbreak-mvp.md`.

## Usability

- [ ] **Home / App switcher need a one-time AssistiveTouch mapping on the phone**, per Bluetooth device (scrcrappy PC, scrcrappy ESP32), and silently do a right-click / nothing until it's done. Make it discoverable: show that setup is needed, guide through it, remember per phone + device that it's done.
- [ ] Mouse wheel doesn't scroll iOS Settings lists (works in other apps). Investigate (wheel report size/pacing? AssistiveTouch scroll mode?).
- [ ] Long, mostly-vertical cursor moves land 5–10% short of the target. Options: calibrate the vertical axis too, or correct from the video (closed loop).
- [ ] Paste types US layout, printable ASCII only; other characters are skipped. Other layouts / accented characters via Option dead keys.
- [ ] Optional `--ctrl-as-cmd`: send Ctrl as Cmd so Ctrl+C/V/A work as iPhone shortcuts.

## Verify

- [ ] Toolbar: first click acts (SDL focus click-through) and the pill hides while another app is focused: user to confirm.
- [ ] Tooltip window may take keyboard focus on some window managers (lost keystrokes right after hovering the pill).
- [ ] ESP32 firmware has never run on real hardware (only compiled for esp32 / -c3 / -s3).
- [ ] macOS untested end to end: patched qvh (clear-halt removal), pill positioning, click-through.

## Housekeeping

- [ ] `toolbar.py`: chevron constants are literal private-use characters (use `\u` escapes); `CHEVRON_COLLAPSE` unused.
- [ ] `toolbar.py`: tooltip font built twice per show.
- [ ] Laptop Bluetooth adapter was left `Pairable: yes` by early spikes (original value unknown).
