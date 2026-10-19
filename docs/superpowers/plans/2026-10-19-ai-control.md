# AI Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI agents drive the iPhone through `scrcrappy agent …` (one action per call, agent mode) and through an MCP server inside the running window (both modes), with percent coordinates, an input lock and a status LED.

**Architecture:** `actions.py` holds the pure, shared parts (coordinate mapping, touch sequences, typing choice, screenshot processing). `agent_cli.py` runs one action over a synchronous agent connection. `mcp.py` is a stdlib Streamable-HTTP JSON-RPC server that calls tool functions; `app.py` supplies those tools for the active mode and shows the lock, rings and LED.

**Tech Stack:** Python stdlib (`http.server`, `json`, `secrets`, `hmac`), pygame-ce (PNG decode / rotate / scale), existing agent client.

**Spec:** `docs/superpowers/specs/2026-10-19-ai-control-design.md`

## Global Constraints

- Coordinates: percent 0–100 (decimals) of the upright screenshot, x left→right, y top→bottom; outside 0–100 → error.
- Screenshots: long edge ≤ 1568 px (aspect kept); reply has `width`, `height`, `orientation`.
- Orientation names: `portrait`, `portrait-upside-down`, `landscape-left`, `landscape-right`; Bluetooth/ESP32: `portrait` / `landscape` only.
- Defaults: tap 80 ms down→up; long-press 1000 ms; swipe 300 ms; moves every ~16 ms.
- Typing (agent): whole text typable by `typing_us.keystrokes` (0 skipped) → `key` per character; else `text` (paste). Reply `typed_with: "keys" | "paste"`.
- CLI stdout: exactly one JSON object; failure → `{"ok": false, "error": …}`, exit 1. Pygame banner suppressed.
- MCP: `127.0.0.1:7331/mcp`, `Authorization: Bearer <token>` (token in config.json), non-local `Origin` refused, one tool call at a time.
- LED: green on/idle, yellow = any MCP request in the last 30 s, red = tool call running (input locked).

## Review Focus

- Landscape: percent coordinates must land on the same spot the AI saw in the upright screenshot (Task 1 test for orientations 3 and 4).
- A tool call whose agent request fails (e.g. clipboard prompt timeout) must return an error, not hang the MCP request (Task 4 test).
- The input lock must be released when a tool call raises (Task 4 test).
- Requests without the token, or with `Origin: http://evil.example`, get 401/403 and run nothing (Task 3 test).
- CLI stdout stays pure JSON even when pairing or the pygame import would print (Task 2 test).

---

### Task 1: `actions.py`, the shared pure parts

**Files:** Create `scrcrappy/actions.py`; Test `tests/test_actions.py`

**Interfaces — Produces:**
- `ORIENTATIONS = {1: "portrait", 2: "portrait-upside-down", 3: "landscape-right", 4: "landscape-left"}` (3 = Home button on the right).
- `parse_point(text: str, extra: bool = False) -> tuple[float, ...]` — `"x,y"` or `"x,y,ms"` (and `"x1,y1,x2,y2[,ms]"` via `parse_points`); raises `ValueError` with a readable message when out of 0–100 or malformed.
- `to_portrait(x: float, y: float, orientation: int) -> tuple[float, float]` — percent of upright image → agent fractions, via `geometry.to_device(…, rect=(0,0,100,100), rotation=ROTATION_BY_ORIENTATION[o], size=(1,1))` with the point given in percent.
- `tap(x, y) / long_press(x, y, ms) / swipe(x1, y1, x2, y2, ms) -> list[tuple[float, str, float, float]]` — `(delay_s_before, phase, fx, fy)` steps in **percent of the upright image** (callers map them).
- `typing_plan(text: str) -> tuple[str, list[tuple[int, int]]]` — `("keys", strokes)` or `("paste", [])`.
- `upright_png(png: bytes, orientation: int, cap: int = 1568) -> tuple[bytes, int, int]` and `frame_png(frame: Frame, cap: int = 1568) -> tuple[bytes, int, int]`.

- [ ] **Step 1: Tests** — `test_parse_rejects_out_of_range_and_garbage` (`"101,5"`, `"a,b"`, `"5"` → ValueError); `test_portrait_identity` (`to_portrait(25, 75, 1) == (0.25, 0.75)`); `test_landscape_maps_like_the_upright_screenshot` (orientation 3: top-left of the upright image `(0, 0)` → portrait `(1, 0)`; orientation 4: `(0, 0)` → `(0, 1)`); `test_tap_is_down_then_up_after_80ms`; `test_swipe_ends_at_target_and_lasts_ms` (sum of delays ≈ 0.3, last step `up` at end point); `test_typing_plan` (`"hi\n"` → keys with 3 strokes; `"è"` → paste); `test_upright_png_rotates_and_caps` (a 750×1334 PNG, orientation 3 → 1334×750 rotated counter-clockwise; a 1125×2436 PNG → long edge 1568).
- [ ] **Step 2:** Run `.venv/bin/pytest tests/test_actions.py -q` → FAIL (module missing).
- [ ] **Step 3:** Implement. Rotation as in `agent.Controller.screenshot` (`-ROTATION_BY_ORIENTATION`); scale with `pygame.transform.smoothscale`; encode with `pygame.image.save(surf, BytesIO, "x.png")`.
- [ ] **Step 4:** Run → PASS; full suite green.
- [ ] **Step 5:** Commit `feat: shared actions for AI control (percent coordinates, touch steps, typing, screenshots)`

### Task 2: `scrcrappy agent` CLI

**Files:** Create `scrcrappy/agent_cli.py`; Modify `scrcrappy/__main__.py` (dispatch `argv[0] == "agent"`; set `PYGAME_HIDE_SUPPORT_PROMPT=1` before any pygame import); Test `tests/test_agent_cli.py`

**Interfaces:** Consumes Task 1. Produces `agent_cli.main(argv: list[str], out=sys.stdout) -> int`; `agent.connect(host)` (existing) for an authenticated `Agent`; uses `Agent.request` / `Agent.send` synchronously.

- [ ] **Step 1: Tests** with a fake agent over a socketpair (monkeypatch `agent.connect` to return an `Agent` on it): `test_tap_sends_down_then_up_in_portrait_fractions` (screen orientation 1, `--tap 50,25` → touch down/up at 0.5,0.25; stdout `{"ok": true}`); `test_screenshot_writes_png_and_reports_size` (fake PNG 750×1334, orientation 4 → file 1334×750, JSON `orientation: "landscape-left"`); `test_touch_not_ready_is_an_error` (`touch_ready: false` → exit 1, error mentions touching the screen); `test_type_ascii_uses_keys_unicode_uses_text`; `test_clipboard_prints_text`; `test_bad_coordinates_exit_1_with_json`; `test_stdout_is_only_json` (`capsys` out parses with `json.loads`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement: argparse with a required mutually exclusive group `--screenshot PATH | --tap | --long-press | --swipe | --type TEXT | --clipboard`; touch actions: `screen` request first (orientation, `touch_ready`), then steps with `time.sleep`, finger 1; screenshot via `screenshot` request + `actions.upright_png`; every exception → JSON error, exit 1.
- [ ] **Step 4:** Run → PASS; suite green. **Verify on the phone** (agent mode, unlocked): `scrcrappy agent --screenshot /tmp/…/s.png` prints size/orientation and the file opens; `scrcrappy agent --tap 50,1` (status bar, harmless) prints `{"ok": true}`.
- [ ] **Step 5:** Commit `feat: scrcrappy agent — one AI action per call (agent mode)`

### Task 3: MCP server (`mcp.py`)

**Files:** Create `scrcrappy/mcp.py`; Test `tests/test_mcp.py`

**Interfaces — Produces:**
- `Tool(name: str, description: str, schema: dict, run: Callable[[dict], list[dict]])` — `run` returns MCP content blocks; raising `ToolError(msg)` → result with `isError: true`.
- `McpServer(token: str, tools: Callable[[], list[Tool]], port: int = 7331)` with `.start() -> None` (raises `OSError` if the port is busy), `.stop()`, `.last_request: float` (monotonic), `.busy: bool`.
- JSON-RPC over `POST /mcp`, JSON responses only: `initialize` (protocolVersion echoed from the client's, `capabilities: {"tools": {}}`, `serverInfo: {"name": "scrcrappy", "version": <pyproject version>}`), `notifications/*` → 202 no body, `ping`, `tools/list`, `tools/call`. `GET` → 405. Tool calls serialized with a lock.

- [ ] **Step 1: Tests** against a started server on a free port with `urllib.request`: `test_rejects_missing_or_wrong_token` (401, tool not run); `test_rejects_foreign_origin` (403); `test_initialize_and_list_tools`; `test_call_returns_content_and_marks_activity` (`last_request` updated, `busy` True during the call, False after); `test_tool_error_is_isError_result`; `test_busy_port_raises_oserror`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with `http.server.ThreadingHTTPServer` bound to `127.0.0.1`; token check with `hmac.compare_digest`; Origin allowed only if absent or `http(s)://127.0.0.1|localhost[:port]`.
- [ ] **Step 4:** Run → PASS; suite green. **Verify** with `curl` (initialize + tools/list with the token).
- [ ] **Step 5:** Commit `feat: minimal MCP server (Streamable HTTP, token, local only)`

### Task 4: AI control in the window

**Files:** Modify `scrcrappy/app.py`, `scrcrappy/agent.py` (`Session.request(..., failed=None)` called with the error text), `scrcrappy/mouse.py` (`Pointer.wait_idle(timeout: float) -> bool`: True once no pending actions and no move left), `scrcrappy/config.py` (`ai_control: bool = False`, `mcp_token: str = ""` created on first enable), `scrcrappy/dialog.py` (Settings: "Allow AI control (MCP)" switch; when on: address line + **Copy** button copying the `claude mcp add --transport http scrcrappy http://127.0.0.1:7331/mcp --header "Authorization: Bearer <token>"` command), `scrcrappy/toolbar.py` (LED item at the top of the pill when AI control is on: `Button("led", …)` drawn as a coloured dot, tooltip explains colours), `scrcrappy/__main__.py` (`--mcp`); Test `tests/test_ai_control.py`

**Interfaces:** Consumes Tasks 1 and 3. Produces `ai_tools(mode, …) -> list[Tool]` in `app.py` (or `scrcrappy/ai_tools.py` if `app.py` grows past ~400 lines).

- [ ] **Step 1: Tests:** `test_agent_tool_error_does_not_hang` (fake Session whose request calls `failed("clipboard timeout")` → tool raises `ToolError` within 1 s); `test_lock_released_when_tool_raises`; `test_ble_tap_moves_pointer_then_clicks` (FakePointer: `move_to` at the percent→frame px, `button(True)`, `button(False)`); `test_no_input_offers_only_screenshot`; `test_led_colour` (off / green / yellow within 30 s / red while busy); `test_settings_switch_saves_and_creates_token`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Tools run on the MCP request thread using thread-safe pieces (pointer queue, `Session.touch`, `Session.request` + `threading.Event`, `KeyQueue`), and set `locked` while running; the window loop drops mouse/keyboard events to the phone while `locked`, draws rings (0.6 s) and the LED colour each frame. Bluetooth/ESP32: percent → frame px; tap/long-press = `move_to`, `wait_idle`, `button(True)`, sleep, `button(False)`; swipe = press at start, interpolated `move_to` over the duration, release; `type_text` via `KeyQueue.type_text` (reports skipped). Screenshot: agent → `screenshot` request + `upright_png`; Bluetooth/ESP32/none → `frames.peek()` + `frame_png`.
- [ ] **Step 4:** Run → PASS; suite green. **Verify** on the phone in agent mode with `--mcp`: curl `tools/call screenshot` returns an image; `tap` on the status bar shows a ring and the LED goes red then yellow.
- [ ] **Step 5:** Commit `feat: AI control (MCP) in the window — tools, input lock, rings, LED, Settings`

### Task 5: Docs

**Files:** Modify `README.md`, `TODO.md`

- [ ] **Step 1:** README section "AI control": the CLI with examples and JSON output; MCP: enable in Settings (or `--mcp`), Copy the command, paste in a terminal; LED colours; percent coordinates; limits (clipboard prompt, paste fallback may prompt, Bluetooth mode types US ASCII). TODO: buttons/keys/pinch/settle-wait/open-app as later.
- [ ] **Step 2:** Commit `docs: AI control`
