# Switch the input mode without restarting (design)

Date: 2026-10-25. Decided with the user in chat: switch from Settings, instantly, window and video stay up; when the
new mode cannot start, stay on the old mode and show a toast.

## Why

The mode (None / BT / ESP32 / Agent) is chosen at launch: `__main__.py` builds the link, key queue, agent session and
calibrator once and hands them to `app.run`, and Settings › Input only edits the saved default ("next launch").
Changing mode means closing and reopening the app, which also restarts the video.

## What changes

- Clicking a mode in Settings › Input switches to it **now**. The yellow "next launch" tag is removed. The video
  capture, window and Settings panel stay as they are; the chosen mode is saved as today (`cfg.mouse`), **only after
  the switch succeeded**.
- `--mouse` still sets the starting mode (flags win over the saved mode for that run, as today). `--port` likewise.
- **Switch order**: build the new mode first, then tear down the old one, so a failed start leaves the old mode
  untouched. Teardown: release held mouse buttons and keys (`controller.release_all()`), stop the pointer, stop the
  `KeyQueue`, close the link (ESP32 serial / BLE helper process) or the agent session.
- **Failure**: toast with the reason (the same texts the launcher prints today, e.g. `no scrcrappy ESP32 firmware
  answering on /dev/ttyUSB0`, `Bluetooth mouse helper failed to start`, `agent: …`), the old mode stays, the mode
  selector shows the old mode again, nothing is saved.
- **Slow starts** (BLE helper up to 10 s, ESP32 handshake up to 10 s, agent connect): the new mode is built on a
  worker thread and handed back to the window thread (`post_run`), never on the UI thread. While it starts, the
  window title reads `scrcrappy — switching to <mode>…`, the old mode keeps working, and further mode clicks are
  ignored.
- **Not allowed while busy**: a switch is refused with a toast (`Not while calibrating` / `Not while an AI action runs`)
  during a calibration and while an AI tool holds the lock.
- What follows the mode (all rebuilt on a successful switch): the toolbar items (`has_input`, agent buttons), the
  custom buttons (`cfg.customs["<serial>/<mode>"]`), the Add-dialog device name (`scrcrappy PC` / `scrcrappy ESP32`),
  the Calibrate section (BT / ESP32 only), the ESP32 board section (ESP32 only), the pointer, the Bluetooth
  `connected()` flag, key repeat settings (agent mode sets `pygame.key.set_repeat`; other modes must clear it),
  and the AI tools: `AiControl` is re-pointed at the new session / keys / pointer / calibrate hook (its `tools()` is
  read per request, so the tool list changes with the mode). The MCP server itself keeps running.
- **Changing the ESP32 port while in ESP32 mode** (Settings › Port, committed with Enter or by leaving the field)
  restarts the ESP32 mode on the new port, with the same failure rules; the port is saved only on success.
- Choosing the mode that is already active does nothing.
- **On macOS the BT cell is not selectable** (the Linux adapter helper doesn't exist there): it is drawn grayed out,
  ignores clicks, and its tooltip says "Needs Linux (use ESP32 or Agent on macOS)". Selectable modes are decided in
  one place (a function of `sys.platform`) so Settings and the switch agree; `start_mode("ble")` on macOS still
  fails with the existing message if reached some other way (e.g. a saved `mouse: ble` or `--mouse ble`).

## Goals

- Move between all four modes any number of times in one run, with the phone video uninterrupted.
- A failed switch never leaves the app without a working previous mode, never leaks a helper process or an open
  serial port, and never leaves a key or button held on the phone.

## Non-goals

- Switching the phone, the video source, the MCP server on/off (existing switch), or `--calibrate`.
- Running two modes at once.
- Remembering a different mode per phone.
- Hot-plugging the ESP32 (unplugging while active is handled as today: the status says "not answering").

## Anti-goals

- Blocking the UI thread on a slow start.
- Saving a mode that failed to start (the next launch would fail the same way).
- A second code path for starting a mode: the launcher and the switch use the same function.

## Constraints

- Linux and macOS (`--mouse ble` is Linux only; on macOS the BT mode fails with the existing message).
- The BLE helper (`blemouse.py`) and ESP32 firmware are unchanged.
- Tests need no phone or board (`.venv/bin/pytest -q`): fake links / sessions injected through the factory.

## Settled from the code and by the assistant (builder-check answers)

- **Ownership**: `AiControl` and the MCP server are created inside `app.run` (`ai = AiControl(...)`, `ai.enable`) and
  already exist for every mode; the MCP on/off state is independent of the input mode. `run` receives the first mode
  from `main()` and switches later modes itself. Toasts exist (`bar.toast`).
- **AI during a switch**: the new mode is built on the worker thread without touching `AiControl`. The swap itself
  (release held input, tear down the old mode, re-point `AiControl`/controller/toolbar) runs synchronously on the
  window thread, so a tool call sees either the old mode or the new one. While building, tools keep running on the
  old mode. If a tool has started by the time the build finishes, the swap waits (checked every frame) until the
  tool's lock clears instead of interrupting it.
- **Selector**: keeps showing the old mode until the switch succeeds (no optimistic highlight); the title says
  `switching to <mode>…`; the old mode stays fully usable meanwhile; `release_all()` runs on the window thread just
  before the swap.
- **Coexistence**: "new first, then tear down" holds for every pair of different modes (BT helper process, ESP32
  serial port, agent tunnel are separate resources). The one exception is **ESP32 → ESP32 on a changed port** (and any
  other same-resource restart): tear the old mode down first, build the new one, and on failure rebuild the old mode
  on the old port (toast says the old mode was restored).
- **Success per mode** = what the launcher waits for today: BT helper printed ready; ESP32 handshake answered
  (the phone's Bluetooth connection is not required, as at launch); agent: `agent.connect()` returned (its later
  reconnects are the session's own business).
- **Launcher failure** is unchanged: if the first mode fails at launch the app prints the error and exits 1.
  `start_mode(name, port)` raises `ModeError(message)` (a `RuntimeError`) with the text that is toasted or printed.
  `--calibrate` keeps its launch-only path in `main()` and is not part of this.
- **Saving**: a successful switch saves `cfg.mouse`; a successful ESP32 start saves `cfg.port` only when the port
  differs from the saved one and came from Settings (a `--port` given on the command line is for that run and is
  not saved unless the user edits the field). At the next launch flags still win over saved values.

## Left to the builder

The shape of the "mode bundle" and the factory (suggested: a small dataclass holding make_pointer, keys, session,
calibrator, link, connected, device_name and a `close()`, built by one `start_mode(name, port)` that
`__main__.main` also uses for the first mode), how `app.run` receives it, the toast wording beyond the examples,
and the order of the teardown steps inside the "stop" phase.

## Decided by the assistant, not the user (check these)

- The mode is saved only after a successful switch.
- Switching is refused during a calibration and during an AI action.
- Changing the port in ESP32 mode restarts the mode.
- The window title shows `switching to <mode>…`; other mode clicks are ignored meanwhile.
- The new mode is built before the old one is torn down.
