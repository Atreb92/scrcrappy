# Switch the input mode without restarting: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a mode in Settings switches input (None / BT / ESP32 / Agent) at once, without restarting or touching the video; a failed start keeps the old mode and toasts the reason; BT is not selectable on macOS.

**Architecture:** A `Mode` bundle (pointer factory, key queue, agent session, calibrator, link, device name) is built by one `start_mode(name, port, ...)` used by both the launcher and the window. `app.run` keeps its parameters (so existing tests keep working) but rebinds them (`nonlocal`) when it swaps modes: the new mode is built on a worker thread, the swap runs on the window thread. Settings asks `app.run` to switch through callbacks instead of only editing `cfg`.

**Tech Stack:** Python 3 / pygame, pytest (SDL dummy driver, fakes for links and sessions).

**Spec:** `docs/superpowers/specs/2026-10-25-hot-switch-mouse-mode-design.md` (read it first, including "Settled from the code and by the assistant").

## Global Constraints

- Work on branch `hot-switch-mode` (exists, from `main`, spec already committed). Commit per task; do not merge.
- Tests: `.venv/bin/pytest -q`, no phone or board. Existing `app.run(...)` callers/tests keep working unchanged (the new parameters are optional; without a mode factory, Settings keeps today's "applies next launch" behaviour and tag).
- Order on a switch: build new, then tear down old (release held input first); exception: same-resource restart (ESP32 port change) tears down first and rebuilds the old mode if the new one fails.
- Never build a mode on the window thread; only the swap runs there. Never save `cfg.mouse` / `cfg.port` before the switch succeeded.
- Refuse a switch with a toast while calibrating (`Not while calibrating`) or while an AI tool holds the lock (`Not while an AI action runs`); ignore mode clicks while one is being built (title `scrcrappy — switching to <mode>…`).
- On macOS (`sys.platform == "darwin"`) the BT cell is grayed out and ignores clicks; tooltip `Needs Linux (use ESP32 or Agent on macOS)`.
- Toast on success: `Input: <label>` where label is the cell label (`None`, `BT`, `ESP32`, `Agent`).
- Match surrounding code style: terse comments, no speculative options.

## Review Focus

- Switching to the mode that is already active, or clicking twice while one is building: nothing happens, no second build.
- A failed switch leaves everything as before: old controller/pointer working, `cfg.mouse` unchanged, selector still on the old mode, toast shows the reason.
- No leaked resources: after a successful swap the old mode's key queue, link/serial/helper and agent session are closed exactly once; after a failure the half-built new mode is closed.
- Held keys and buttons are released on the phone before the old mode goes away.
- A switch requested during a calibration or while an AI tool runs is refused; a build finishing while an AI tool runs waits for it.
- Agent ↔ BLE: key repeat is set for agent mode and cleared for the others; custom buttons show the new mode's set; toolbar items follow.
- `--mouse ble` on macOS at launch still fails with the existing message.

---

### Task 1: `Mode`, `start_mode`, `selectable`

**Files:**
- Create: `scrcrappy/modes.py`
- Modify: `scrcrappy/__main__.py` (use `start_mode`; the `args.mouse` branches around lines 101-125)
- Test: `tests/test_modes.py`

**Interfaces:**
- Produces in `modes.py`:
  - `class ModeError(RuntimeError)`: message is the user-facing reason.
  - `@dataclass class Mode`: `name: str`, `make_pointer: Callable[[tuple[int, int]], Pointer] | None = None`, `keys: KeyQueue | None = None`, `session: agent.Session | None = None`, `calibrator: Calibrator | None = None`, `link: Link | None = None`, `device_name: str = "scrcrappy PC"`; properties `board -> Link | None` (the link when `name == "esp32"`), `connected -> Callable[[], bool]` (the link's `connected.is_set`, else `lambda: True`), method `close() -> None` (stops `keys`, closes `link`, closes `session`; each exactly once, tolerating `None`).
  - `LABELS = {"none": "None", "ble": "BT", "esp32": "ESP32", "agent": "Agent"}`.
  - `selectable(name: str, platform: str = sys.platform) -> bool` (`False` only for `"ble"` on `"darwin"`).
  - `start_mode(name: str, port: str, serial: str, frames: LatestFrame, ble_python: str = "/usr/bin/python3") -> Mode`: `none` → bare Mode; `ble`/`esp32` → `links.ble(ble_python)` / `links.esp32(port)` + `KeyQueue(link.send_keys)` started + `make_pointer` + `Calibrator(serial, link.send, frames)` (exactly what `__main__` builds today); `agent` → `agent.Session(agent.connect(socket.gethostname()).sock, reopen=...)` as today; any `OSError` / `RuntimeError` / `agent.AgentError` becomes `ModeError(str(e))`; `ble` on macOS raises `ModeError("Bluetooth mouse needs Linux: use ESP32 or Agent on macOS")`. Nothing is left open when it raises.
- Consumes (existing): `links.ble`, `links.esp32`, `agent.Session`, `agent.connect`, `mouse.Pointer`, `mouse.Gain`, `calibrate.load`, `calibrate.Calibrator`, `KeyQueue`.

- [ ] **Step 1: Write failing tests** in `tests/test_modes.py` with fakes monkeypatched into `modes.links` / `modes.agent`: `test_none_has_no_input`; `test_esp32_builds_link_keys_pointer_and_calibrator` (fake link records `close`; `mode.board is mode.link`; `connected()` follows the link's event); `test_ble_board_is_none`; `test_failures_become_mode_errors` (OSError / RuntimeError / AgentError from each factory → `ModeError` with the message; fake keys never started); `test_close_closes_each_resource_once` (call `close()` twice, counters 1); `test_selectable_blocks_only_ble_on_macos`; `test_ble_on_macos_raises_mode_error`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_modes.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `modes.py` per the interface, moving the construction code out of `__main__.main`.
- [ ] **Step 4: Use it in `__main__.main`**: build the first mode with `start_mode(args.mouse, args.port, serial, frames, args.ble_python)`; on `ModeError` print `error: <message>` to stderr and return 1 (agent errors keep their current `error: agent: …` prefix); the BT-connected note, `--calibrate` path (`mode.link.send`, `mode.link.connected`) and `app.run(...)` arguments come from the Mode (`make_pointer=mode.make_pointer, keys=mode.keys, agent=mode.session, calibrator=mode.calibrator, board=mode.board, connected=mode.connected, device_name=mode.device_name`). `atexit` closes `mode.close`. Existing `tests/test_main.py` must stay green (adjust its monkeypatches to the new seams only where they target moved code).
- [ ] **Step 5: Run** `.venv/bin/pytest -q` → all PASS.
- [ ] **Step 6: Commit** `modes: one start_mode for the launcher (and, next, the window)`.

### Task 2: Settings mode cells ask the app to switch

**Files:**
- Modify: `scrcrappy/dialog.py` (`Settings`: `__init__` kwargs, `_layout`, `_click` mode branch, `draw` tag + cells, `_commit` for the port, new `rebind`)
- Test: `tests/test_dialog.py`

**Interfaces:**
- Consumes: `modes.LABELS`-compatible `MODES` list already in `dialog.py`; `modes.selectable`.
- Produces: `Settings.__init__(..., on_mode: Callable[[str], None] | None = None, on_port: Callable[[str], None] | None = None)`. With `on_mode` given: clicking a selectable cell calls `on_mode(name)` and does **not** touch `cfg.mouse` (the app does that after a successful switch); the "next launch" tag is not drawn; a non-selectable cell (BT on macOS, via `selectable(name)`) is drawn dimmed (`DISABLED` text), ignores clicks and shows the tooltip `Needs Linux (use ESP32 or Agent on macOS)`; clicking the already-selected cell does nothing. Without `on_mode`, behaviour is exactly today's (cfg write + `on_change` + tag). `on_port(port)` is called by `_commit` when the port field changed **and** `cfg.mouse == "esp32"` (instead of writing `cfg.port` itself; the app saves it after success); without `on_port`, today's behaviour. `Settings.rebind(calibration: float | None, board, connected: Callable[[], bool]) -> None` swaps the calibration section (None hides it, resets `tips`), the board section and the connected flag, then `_relayout()`.

- [ ] **Step 1: Write failing tests**: `test_mode_click_asks_the_app_and_leaves_cfg_alone` (`on_mode` gets `"agent"`, `cfg.mouse` unchanged, no `on_change`); `test_same_mode_click_does_nothing`; `test_next_launch_tag_only_without_on_mode` (draw both and compare a pixel in the tag area, or expose `panel.shows_next_launch_tag`); `test_ble_cell_disabled_on_macos` (monkeypatch `dialog.selectable`); `test_port_change_in_esp32_mode_calls_on_port_without_writing_cfg`; `test_port_change_in_other_modes_still_saves_to_cfg`; `test_rebind_swaps_calibration_and_board_sections` (hits gain/lose `"calibrate"` and `"forget"`, `panel.rect.height == panel.height`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_dialog.py -q` → FAIL.
- [ ] **Step 3: Implement** the interface above (mode cell state from `selectable`, tooltip via the existing `tips` / `tip()` path).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → PASS.
- [ ] **Step 5: Commit** `Settings: mode cells and port ask the app to switch`.

### Task 3: Switching inside `app.run`

**Files:**
- Modify: `scrcrappy/app.py` (`run`), `scrcrappy/ai.py` (`AiControl.rebind`)
- Test: `tests/test_app.py`, `tests/test_ai_control.py`

**Interfaces:**
- Consumes: `Mode`, `ModeError`, `LABELS`, `selectable` (Task 1); `Settings(on_mode=, on_port=)`, `Settings.rebind` (Task 2).
- Produces: `app.run(..., start_mode: Callable[[str, str], Mode] | None = None, mode_name: str = "")` (`start_mode(name, port)` builds a Mode and may raise `ModeError`; `mode_name` is the starting mode, used to ignore clicks on it; both default to "no switching"). `AiControl.rebind(session, keys, pointer, calibrate) -> None` re-points the fields the constructor took (pointer as the same kind of callable as the constructor's `pointer`). Inside `run`, `request_switch(name: str, port: str | None = None)` and `swap(new: Mode)`.

Behavior to implement (all rules in the spec's "What changes" and "Settled" sections):
- `request_switch`: no-op if `start_mode` is None, a build is running, or `name` is the active mode and the port is unchanged; refuse with the Global-Constraints toasts while calibrating / AI lock; otherwise set the title and build on a thread (`post_run` the result). Same-resource restart (name is the active mode, port changed): tear the old mode down first (release input, stop controller, `old.close()`), build, and on `ModeError` rebuild the old mode with the old port; if that also fails fall back to a bare `none` Mode and toast that.
- `ready(new)`: stored as `pending`; each frame, if `pending` and not `ai.locked()` and not `calibrating`, `swap(pending)`.
- `failed(error)`: toast the message, restore the title, nothing else changes.
- `swap(new)`: `controller.release_all()` and stop it; `old.close()` (skipped for the already-closed restart case); rebind `make_pointer, keys, agent, calibrator, board, connected, device_name, device_key` (`f"{serial}/{name}"` — pass `serial` into `run` if it is not derivable from the current `device_key`), `customs = cfg.customs.setdefault(device_key, [])`; agent mode creates its `Controller` and `pygame.key.set_repeat(400, 33)`, other modes `pygame.key.set_repeat()` and `controller = None` (the loop rebuilds the BLE controller when the first frame/pointer is available); `ai.rebind(...)`; `cfg.mouse = new.name` (and `cfg.port` when it changed and came from Settings) then `save_or_warn`; `settings.rebind(...)` if open; `bar.set_items(items())`; toast `Input: <label>`; title restored.
- Wire `Settings(..., on_mode=request_switch, on_port=lambda p: request_switch("esp32", p))` only when `start_mode` is given.

- [ ] **Step 1: Write failing tests** (fake `Mode`s built directly; fake factory returning them or raising `ModeError`; use the existing `alive()`-driven harness in `tests/test_app.py`, with a `Bar.__init__` / `Settings.__init__` hook to reach the objects): `test_switch_success_swaps_everything` (old mode's `close` called once, `cfg.mouse` and saved config updated, new `make_pointer` used afterwards, toolbar has agent buttons after → agent, toast `Input: Agent`); `test_failed_switch_keeps_the_old_mode` (cfg.mouse unchanged, old close not called, toast has the error text, no save); `test_switching_to_the_active_mode_is_a_noop` (factory never called); `test_second_click_while_building_is_ignored` (factory called once); `test_switch_refused_while_calibrating` and `test_switch_refused_while_ai_locked` (monkeypatch `AiControl.locked`); `test_swap_waits_for_an_ai_tool` (build finishes while locked → swap happens on the first frame after unlock); `test_held_input_released_before_the_swap` (fake controller records `release_all` before `old.close`); `test_port_change_restarts_esp32_and_rebuilds_old_on_failure`; `test_key_repeat_set_for_agent_and_cleared_otherwise` (`pygame.key.get_repeat()`); `test_ai_control_rebind_changes_the_tool_list` in `tests/test_ai_control.py` (agent session → tools include `home`; rebound to a pointer → they do not).
- [ ] **Step 2: Run** the new tests → FAIL.
- [ ] **Step 3: Implement** `AiControl.rebind` and the `run` changes above; keep every existing parameter and default.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` → PASS (the suite is order-flaky in `tests/test_app.py` per TODO.md; rerun once before calling a failure real).
- [ ] **Step 5: Commit** `app: switch the input mode from Settings without restarting`.

### Task 4: Wire the launcher, live check, docs

**Files:**
- Modify: `scrcrappy/__main__.py` (pass the factory), `README.md` (Settings table row: "Input mode … applies next launch" becomes "switches at once; BT is Linux only"), `TODO.md` (entry for this feature), `CLAUDE.md` Map (`modes.py` line)

- [ ] **Step 1:** In `main`, call `app.run(..., start_mode=lambda name, port: modes.start_mode(name, port, serial, frames, args.ble_python), mode_name=args.mouse, ...)`; keep `atexit` closing whichever mode is active at exit (use a small holder or `run`'s final teardown: `run` closes the active mode in its `finally`, `main` no longer registers `atexit` for the link).
- [ ] **Step 2: Run** `.venv/bin/pytest -q` → PASS.
- [ ] **Step 3: Live check with the user** (`.venv/bin/scrcrappy --mouse esp32 --port /dev/ttyUSB0`): switch ESP32 → None → ESP32 → Agent (expect the toast with the real error if the phone is not jailbroken) → back; change the port to a wrong one and confirm the toast, the old mode restored, and the saved port unchanged; confirm video never stalls. Report the observed results.
- [ ] **Step 4:** Update README / TODO / CLAUDE.md, run the suite once more, commit `Docs: switching the input mode`, then one fresh reviewer on the whole branch (`superpowers:requesting-code-review`); fix what it finds. Leave merging to the user.
