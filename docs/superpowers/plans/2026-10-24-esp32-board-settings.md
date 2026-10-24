# ESP32 board section in Settings + button press feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings shows the ESP32 board's pairing/connection state with a confirmed "Forget phone & allow pairing" button, and every in-window button shows hover/pressed feedback.

**Architecture:** The firmware's `?` reply becomes a full state snapshot; `Link` parses it into `paired` / `peer` / `connected` and records `last_seen`; `Settings` polls `?` once a second while open and renders a status line + button from `Link`. A pure `shade()` helper in `toolbar.py` gives hover/pressed colours to the bar, Settings and the right-click menu.

**Tech Stack:** Python 3 / pygame (tests: pytest, SDL dummy driver), Arduino C++ on NimBLE-Arduino 2.3.2 (PlatformIO, `esp32dev` / `esp32-c3` / `esp32-s3`).

**Spec:** `docs/superpowers/specs/2026-10-24-esp32-board-settings-design.md` (read it first; mockup layout A).

## Global Constraints

- Work on branch `esp32-board-settings`, created from `main` (the uncommitted spec, plan and TODO.md edit come along). Commit per task; do not merge.
- Tests: `.venv/bin/pytest -q`, no phone or board. Firmware must compile for `esp32dev`, `esp32-c3` and `esp32-s3` (`pio run -e <env>`).
- Line protocol stays backward compatible: `ready`, `connected`, `pairing` keep their meaning; `ble` helper (`blemouse.py`) is not changed.
- Poll `?` once a second only while Settings is open; "Board not answering" after no line for 2.5 s; Forget confirm lasts 3 s.
- Status texts, exactly: `Connected to {name} (…{id})` (no name: `Connected (…{id})`), `Open to pairing`, `Paired, not connected`, `Board not answering`, `Reflash the board for status`. Dot colours: green connected, blue blinking about 1 Hz for open to pairing, grey for the rest. Button: `Forget phone & allow pairing`, confirm state `Click again to confirm`. Toast: `Board is open to pairing. Forget it on the phone too.`
- Never open or reset the serial port from the UI; reuse the `Link`.
- Match surrounding code style: terse comments, `ponytail:` comments only for real ceilings.

## Review Focus

- Board unplugged while Settings is open: status goes to "Board not answering", no exception (writes already swallow `OSError`).
- Settings closed and reopened mid-confirm: the confirm state is gone.
- `board` is `None` (ble, agent, none modes): no section, no `?` traffic, no crash.
- Phone name with spaces, empty, control characters or 200+ chars: shown stripped and truncated, never breaks the status line.
- Old firmware (`?` answers `ready` only): "Reflash the board for status", Forget still sends `p`.
- Mouse pressed on a button, dragged off and released: no click, pressed look cleared.

---

### Task 1: Firmware state snapshot

**Files:**
- Modify: `firmware/esp32-mouse/src/main.cpp` (header comment of the protocol too)

**Interfaces:**
- Produces: `?` answers `ready`, then `unpaired` or `paired <id>`, then (phone connected) `connected` and `peer <id> <name>`. New unsolicited `disconnected` on link loss. `p` also disconnects a live peer, keeps advertising, answers `pairing`. `<id>` = last two bytes of the peer identity address, uppercase hex `3F:A2`. `<name>` = the phone's GAP Device Name (UUID 0x2A00), may be empty.

- [ ] **Step 1: Peer name read.** In `ServerCallbacks::onAuthenticationComplete` (first line, before the `isBonded` check) call `ble_gattc_read_by_uuid(info.getConnHandle(), 1, 0xffff, &gap.u, cb, nullptr)` with `BLE_UUID16_INIT(0x2A00)` (proven on this board 2026-10-24: callback gets the name in `a->om`, `os_mbuf_copydata`). Store name and id in static buffers (`peerName[64]`, `peerId[6]`), id from `info.getIdAddress()`; clear both in `onDisconnect`.
- [ ] **Step 2: `onDisconnect` prints `disconnected`.**
- [ ] **Step 3: `?` handler** prints the snapshot above (`paired` = `NimBLEDevice::getNumBonds() > 0`; id from the stored bond via `NimBLEDevice::getBondedAddress(0)` when no peer is connected; `peer` line only when `subscribed`).
- [ ] **Step 4: `p` handler**: after `deleteAllBonds()`, if a peer is connected `server->disconnect(handle)` (keep the handle from `onAuthenticationComplete`/`onConnect`); advertising restarts via the existing `advertiseOnDisconnect(true)`. Update the file header comment.
- [ ] **Step 5: Compile** all three envs: `cd firmware/esp32-mouse && for e in esp32dev esp32-c3 esp32-s3; do pio run -e $e | tail -2; done`. Expected: 3 × SUCCESS.
- [ ] **Step 6: Flash `esp32dev` and check on the board** (ask the user to be at the phone): stop scrcrappy first; with the pipx-venv pyserial script from the earlier session send `?` once ready: expect `ready`, `paired …`, and with the phone connected `connected` + `peer 3F:A2 iPhone` style lines; send `p`: expect `disconnected`, `pairing`, then `?` → `unpaired`. Report the real output to the user.
- [ ] **Step 7: Commit** `firmware: report pairing state and peer on "?"; "p" drops the peer`.

### Task 2: Link parses the snapshot

**Files:**
- Modify: `scrcrappy/links.py` (docstring protocol list too)
- Test: `tests/test_links.py`

**Interfaces:**
- Produces on `Link`: `paired: bool | None`, `peer: tuple[str, str] | None` (id, name), `last_seen: float` (`time.monotonic()` at any received line), `on_pairing: Callable[[], None] | None` (called on the reader thread for a `pairing` line), `query() -> None` (sends `?`), `forget() -> None` (sends `p`). `connected` is cleared by `disconnected` and by every `ready`; each `ready` also resets `paired` and `peer` to None. Lines: `unpaired` → `paired=False`; `paired <id>` → `True`; `peer <id> <name>` → `peer=(id, name)` (name may be empty or contain spaces).

- [ ] **Step 1: Write failing tests** with a fake `read` (queue of byte chunks, then `b""`): `test_snapshot_fills_state` (feed `ready\npaired 3F:A2\nconnected\npeer 3F:A2 My iPhone\n` → `paired is True`, `peer == ("3F:A2", "My iPhone")`, `connected.is_set()`); `test_disconnected_clears_connected`; `test_ready_resets_state` (a second `ready` clears `paired`, `peer`, `connected`); `test_empty_peer_name` (`peer 3F:A2` → `("3F:A2", "")`); `test_pairing_calls_hook`; `test_query_and_forget_write_lines` (captured writes `b"?\n"`, `b"p\n"`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_links.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the interface above inside `Link.reader`'s line loop (replace the dict-of-events lookup with a small if-chain; `ready` and `connected` keep setting their Events).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/test_links.py -q` → PASS (existing handshake test included).
- [ ] **Step 5: Commit** `links: parse the board's pairing snapshot`.

### Task 3: Settings board section and wiring

**Files:**
- Modify: `scrcrappy/dialog.py` (`Settings`), `scrcrappy/app.py` (`run` signature + `open_settings` + loop), `scrcrappy/__main__.py:~118` (pass the link)
- Test: `tests/test_dialog.py`

**Interfaces:**
- Consumes: `Link` from Task 2.
- Produces: `board_status(link: Link, now: float) -> tuple[str, str]` in `dialog.py`, returning `(colour, text)` with `colour` in `"green" | "blue" | "grey"` and the exact texts from Global Constraints (`"Board not answering"` when `now - link.last_seen > 2.5`; `"Reflash the board for status"` when `link.paired is None` and the link is live; `"Paired, not connected"` when `paired` and not connected; `"Open to pairing"` when `paired is False`; connected wins over paired). `Settings.__init__` gains `board: Link | None = None`; `Settings.tick(now: float | None = None) -> None` (polls `board.query()` at most once a second, only if `board` and the panel is not closed); `app.run(..., board: Link | None = None)`; `__main__` passes `board=link if args.mouse == "esp32" else None`.

- [ ] **Step 1: Write failing tests** (fake link object with the Task 2 attributes): `test_board_status_*` for every row of the mapping incl. name sanitising (strip control chars, truncate to 24 chars + `…`); `test_board_section_only_with_board_and_esp32_mode` (hits has `"forget"` only then); `test_forget_needs_two_clicks` (first click: no `forget()` call, label `Click again to confirm`; second within 3 s: one `forget()` call; a click after 3 s starts over); `test_confirm_cleared_on_close_and_reopen`; `test_tick_polls_once_a_second_only_while_open`; `test_pairing_hook_shows_toast` where the toast text is exactly the spec's.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_dialog.py -q` → FAIL.
- [ ] **Step 3: Implement** `board_status`, the `"forget"` hit and layout rows under the Port row in `Settings._layout`/`draw` (dot + status text, then the pill button right-aligned like Copy MCP config; the blue dot blinks via `int(now * 2) % 2`), `tick`, and the confirm logic in `_click`. In `app.run`: pass `board` to `Settings(...)`, call `settings.tick()` once per frame while it exists, and set `board.on_pairing = lambda: post_run(lambda: bar.toast("Board is open to pairing. Forget it on the phone too."))` when `board` is given.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → all PASS (the suite is order-flaky in `tests/test_app.py` per TODO.md; rerun once before calling a failure real).
- [ ] **Step 5: Run it for real** with the user: `.venv/bin/scrcrappy --mouse esp32 --port /dev/ttyUSB0`, open Settings, check each status (connected, then Forget + confirm → blue blinking, re-pair → green). Report what was seen.
- [ ] **Step 6: Commit** `Settings: ESP32 board status and Forget phone button`.

### Task 4: Press feedback

**Files:**
- Modify: `scrcrappy/toolbar.py` (helper + `Bar`), `scrcrappy/dialog.py` (`Settings`, `Menu`; `Dialog` buttons only if the helper drops in with a few lines)
- Test: `tests/test_toolbar.py`, `tests/test_dialog.py`, `tests/test_bar.py`

**Interfaces:**
- Produces: `shade(colour: tuple[int, int, int], hover: bool, pressed: bool) -> tuple[int, int, int]` in `toolbar.py` (pressed darker than normal, hover lighter; clamped 0..255). `Bar.pressed: Button | None`, `Settings.pressed: str | None`, `Menu.pressed: str | None`: set on `MOUSEBUTTONDOWN` button 1 over a button, cleared on `MOUSEBUTTONUP` and window focus loss; a click fires only when release is over the same button that was pressed.

- [ ] **Step 1: Write failing tests**: `test_shade_ordering` (pressed < normal < hover per channel sum); `test_bar_press_then_release_elsewhere_does_not_click`; `test_bar_pressed_cleared_on_release`; same two for `Settings` (hit name) and `Menu`.
- [ ] **Step 2: Run** the three test files → FAIL.
- [ ] **Step 3: Implement** `shade` and the `pressed` tracking; draw the bar button circle one px smaller with a darker fill while pressed; Settings/Menu button fills go through `shade(base, hover=self.hover == name, pressed=self.pressed == name)` (covers Calibrate, Copy MCP config, browse, Forget, menu rows, and the mode segments).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → PASS.
- [ ] **Step 5: Look at it** with the user in the running window: every button type visibly reacts to hover and press.
- [ ] **Step 6: Commit** `Buttons show hover and pressed states`.

### Task 5: Docs, TODO, final check

**Files:**
- Modify: `README.md` (Settings table row and the ESP32 pairing paragraph near line 84: replace the `echo p` advice with the button, keep a one-line note about the serial `p` line), `TODO.md` (close the "Forget paired phone" item at line 60, note the status section, mention peer name is the generic `iPhone`), `CLAUDE.md` Map only if a new file was added (none expected).

- [ ] **Step 1: Edit the docs** as above.
- [ ] **Step 2: Run** `.venv/bin/pytest -q` and the three `pio run` compiles → all green.
- [ ] **Step 3: Commit** `Docs: ESP32 board section`, then dispatch one fresh reviewer on the whole branch (`superpowers:requesting-code-review`) and fix what it finds. Leave merging to the user.
