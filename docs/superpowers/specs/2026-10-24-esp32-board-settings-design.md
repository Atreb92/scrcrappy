# ESP32 board section in Settings + button press feedback (design)

Date: 2026-10-24. Mockup reviewed with the user (layout A, compact).

## Why

After switching iPhones there was no confident way to put the ESP32 back into pairing mode: the only route was
`echo p > /dev/ttyUSB0` with scrcrappy closed, and opening the port resets the board, which can swallow the `p`
(seen on 2026-10-22). Nothing in the window says whether the board is paired, connected, or open to a new phone.
Separately, no button in the app shows that it was pressed.

## What changes

### 1. Settings › "ESP32 board" section (ESP32 mode only, under the Port row)

- **Status line**: a dot and a text, from the board's own report:
  - green, "Connected to {name} (…{id})": a phone is connected. `name` is what the phone gives the board
    (iOS 16.7 gives the generic `iPhone`, measured 2026-10-24, not the user's own name); `id` is the last two
    bytes of the phone's identity address, so two phones can be told apart.
  - blue, blinking (about 1 Hz): "Open to pairing": no phone bonded, or after Forget.
  - grey: "Paired, not connected" (bonded, phone out of range or Bluetooth off).
  - grey: "Board not answering" (no reply to two consecutive polls).
- **One button**: "Forget phone & allow pairing". First click turns it into "Click again to confirm" for 3 s
  (in the panel, no extra window); the second click sends `p`. When the board answers `pairing` the window toasts
  "Board is open to pairing. Forget it on the phone too." (iOS keeps its own pairing; the user still has to do that).
- The status refreshes by asking the board `?` once a second **only while the Settings panel is open**.
- No "paired with N phones" line (the board allows one phone), no Disconnect button, no firmware row.

### 2. Firmware (`firmware/esp32-mouse/src/main.cpp`) and `Link`

The line protocol stays backward compatible (`ready`, `connected`, `pairing` keep their meaning).

- `?` now answers `ready`, then exactly one of `unpaired` / `paired <id>`, then, if a phone is connected,
  `connected` and `peer <id> <name>`.
- New unsolicited line `disconnected` from the server's `onDisconnect`.
- Peer name: read the phone's GAP Device Name (UUID 0x2A00) with `ble_gattc_read_by_uuid` from
  `onAuthenticationComplete` (proved on the real board: returns `iPhone`). Cached until disconnect; empty or a
  failed read gives no name, and the UI then shows "Connected (…id)".
- `p` also disconnects a live peer and keeps advertising, so the board really is open to pairing at once
  (the 2026-10-22 failed re-pair after `p` was never explained; this removes one possible cause).
- `Link` (`links.py`) parses these lines into `link.paired: bool | None`, `link.peer: tuple[str, str] | None` and
  clears `connected` on `disconnected`. New `Link.query()` (sends `?`) and `Link.forget()` (sends `p`, ESP32 only;
  the `ble` helper ignores unknown lines, so nothing breaks there). The reader thread must hand the `pairing`
  reply to the window thread (`post_run`) for the toast.

### 3. Button press feedback (everywhere)

Every clickable button gets three looks: normal, hover (exists on the bar; added for panel buttons), pressed
(darker fill and 1 px smaller while the mouse is down on it; releasing outside cancels). Applies to the toolbar
buttons, Settings buttons (Calibrate, Copy MCP config, folder browse, the new Forget button) and the right-click
menu rows. The Add/Edit dialog is its own window: include its buttons if the helper makes that trivial,
otherwise leave them and say so. One shared helper (draw state from `hover` / `pressed`), not per-button code.

## Goals

- At a glance: is the board paired, connected, open to pairing, or not answering.
- One confident action to open the board to a new phone, without closing scrcrappy or touching the port.
- Visible press feedback on every in-window button.

## Non-goals

- Naming the phone with its real name (not available over Bluetooth on iOS 16; no guessing from the USB phone).
- Forgetting the pairing on the iPhone itself (impossible from here; the toast says so).
- Disconnect without forgetting, multi-phone support, firmware version display, animations beyond the blink.
- The Linux `--mouse ble` helper's pairing policy (separate TODO).

## Anti-goals

- Opening or resetting the serial port from the UI (it reboots the board): reuse the Link scrcrappy holds.
- Polling the board while Settings is closed (cursor traffic shares that line).
- A Forget that fires on one stray click.

## Constraints

- Tests need no phone or board (`.venv/bin/pytest -q`): cover the line parser, the status → text/colour
  mapping, the confirm-then-send flow, and press-state hit logic with fake links; match the existing
  `tests/test_dialog.py` style. Firmware: must still compile for `esp32dev`, `esp32-c3`, `esp32-s3`; run on the
  classic ESP32 test board (D0WD-V3) before merging.
- The panel grows by about 90 px; existing small-window scrolling keeps it usable.
- Docs: README (Settings table, ESP32 pairing paragraph: replace the `echo p` advice with the button) and
  TODO.md (close the "Forget paired phone" item).

## Settled from the code (builder-check answers)

- **Writes are already safe**: `Link._line` does one `os.write` per line, so `?` / `p` from the window thread
  never interleave with cursor reports from the controller thread; no lock needed. The reader thread owns the
  parsing; `Link` fields it sets (`paired`, `peer`) are plain attributes read by the window thread.
- **Snapshots**: each `ready` line starts a fresh snapshot, so the parser resets `paired`, `peer` and `connected`
  to unknown/clear on `ready` and the lines that follow refill them. A board reboot therefore clears a stale green
  dot at the next poll (at most 1 s while Settings is open).
- **Old firmware** (answers `?` with `ready` only, `paired` stays None while the link is live): the status reads
  grey "Reflash the board for status"; the Forget button still works (old `p` already exists).
- **`p` already deletes every bond** (`deleteAllBonds`, `main.cpp:103`), so the poll after Forget answers
  `unpaired`; `disconnected` and `pairing` arrive first, in that order.
- **Press feedback size**: `Settings`, `Menu` and the bar act on `MOUSEBUTTONUP` only. Each gains a `pressed`
  hit name set on `MOUSEBUTTONDOWN` (button 1) and cleared on `MOUSEBUTTONUP` / focus loss; the draw code uses it.
  A small change in each, so the menu rows stay in scope; the Add/Edit dialog stays optional as written.

## Left to the builder

Exact colours, blink timing, layout metrics, how the confirm state is stored, the id format (any stable short
hex), and where the shared press-state helper lives (`toolbar.py` already owns `ui_font` and `draw_tip`).

## Decided by the assistant, not the user (check these)

- Two-step confirm in the panel instead of a dialog.
- The extra "Paired, not connected" state and the id next to the name.
- `p` also disconnecting the peer.
- Poll interval 1 s, "not answering" after two misses, confirm timeout 3 s.
- Press feedback also on the right-click menu rows.
