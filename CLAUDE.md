# scrcrappy — notes for a new session

scrcpy for iOS: mirror an iPhone over USB (patched qvh → PyAV → pygame window) and control it with a
BLE mouse/keyboard (Linux adapter or ESP32, steering the AssistiveTouch cursor), with crappytouch
(our SpringBoard tweak, `~/source/crappytouch`, jailbroken phones), or from AI agents
(`scrcrappy agent …` CLI, MCP in the window). User-facing docs: README.md. Open items: TODO.md.

## Map

- `__main__.py` CLI (flags win over saved settings; `scrcrappy agent …` dispatches to `agent_cli.py`)
- `app.py` window loop, BLE `Controller`; `toolbar.py` bar (button strip under the phone image); `dialog.py` Settings + right-click menu (overlays in the main window), Add-button dialog (its own window)
- `debuglog.py` opt-in rotating log + the scrubbing rules (every record and report passes `scrub`); `diagnose.py` `--diagnose-esp32` / `--report`
- `modes.py` the four input modes as `Mode` bundles; `start_mode` is used by the launcher and by the window's live switch (Settings › Input)
- `agent.py` agent backend (Session: worker thread, replies posted back as pygame USEREVENTs; may start without a socket and
  connects by itself, `state` = connected / reconnecting / unreachable for the Settings row; requests are dropped while down)
- `agent_client.py` vendored from crappytouch (keep in sync with its `client/`); `usbmux.py` stdlib usbmuxd
- `ai.py` AI tools + LED/rings/lock; `mcp.py` stdlib MCP server (127.0.0.1:7331, Bearer token); `actions.py` shared percent-coordinate logic
- `mouse.py` pointer steering (a gain table per axis; reports paced to `Link.pace()`, the interval the ESP32 reports), `calibrate.py` (x measured, y checked, ~90 s), `links.py` + `blemouse.py` (BLE helper, system python), `keyqueue.py`
- `geometry.py` coordinate/rotation maps; `video.py` qvh capture, `LatestFrame` (get = take, peek = newest)
- `config.py` → `~/.config/scrcrappy/config.json` (mode 600, holds the MCP token); gain + agent key files live there too

## Dev loop

- Tests: `.venv/bin/pytest -q` (~570 tests, ~2.5 min, no phone needed; SDL dummy driver).
- Run from source: `.venv/bin/scrcrappy --mouse agent|ble|esp32 [--mcp]`.
- The user's daily copy is pipx: after changes `rm -rf build dist && pipx install --force .`.
- qvh: `scripts/build-qvh.sh` → `scrcrappy/bin/qvh` (shipped in the package). It uses `git apply`, not
  `patch`: `~/.cargo/bin/patch` on this machine is not GNU patch and silently applies nothing.
- Work on a branch, merge to `main` with `--no-ff` when the user says so.

## Phone gotchas (iPhone 8, iOS 16.7.1, Dopamine)

- After a phone reboot: re-run Dopamine (jailbreak is gone), then touch the screen once before agent taps work.
- usbmuxd can wedge (`lockdown error -8`, `idevice_id -l` hangs) after scrcrappy's USB reset while the
  phone is locked: ask the user to unlock / replug. scrcrappy now times out after 5 s with that hint.
- BLE overshoot / undershoot = the phone's pointer speed changed: Settings › Calibrate (or `--calibrate`).
- Scroll direction: BT / ESP32 send a wheel report (iOS's own mouse-scroll setting decides), agent swipes a finger; the agent's
  sign is set to match a phone with iOS's default. One setting, Settings › Invert scrolling (`invert_scroll`), flips all modes.
- Starting the video (qvh) drops the agent's usbmuxd tunnel once; the Session reconnects by itself.
- The window never waits for a control device: the ESP32 handshake, the BT helper's start and the agent connection (pairing
  included) run on threads; a failure is `Link.error` / `Session.state` (toast + Settings), not an exception at start.
- Never `pkill -f <pattern>` from the shell tool: it matches the tool's own command line and kills it.

## Process the user likes

Brainstorm → design doc in `docs/superpowers/specs/` → plan in `docs/superpowers/plans/` → build inline
on a branch with TDD → one fresh reviewer at the end → merge. Show mockups (browser companion) for UI.
