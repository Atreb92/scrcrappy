# scrcrappy jailbreak MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror a jailbroken iPhone's screen in a desktop window and control it with mouse and keyboard (design phases 0–4 + CLI/auto-detect for the jailbreak backend).

**Architecture:** One Python package. A video source (qvh subprocess → PyAV decode, or ZXTouch screenshots) runs in a thread and keeps the latest frame. The pygame main loop draws it and turns mouse/keyboard events into ZXTouch commands sent over a usbmux-forwarded TCP connection (device port 6000).

**Tech Stack:** Python ≥ 3.11, pygame-ce (window, clipboard), PyAV (H.264 decode), pymobiledevice3 (usbmux), qvh binary (external), pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-scrcrappy-design.md`

## Global Constraints

- Runs on Linux (Fedora) and macOS; no OS-specific code in the package.
- No network listener on the computer side; device reached only via usbmux.
- Target: iPhone X, iOS ≤ 16.6.1, Dopamine rootless, ZXTouch Rootless (gitssie fork) installed.
- ESP32 backend (design phase 5) is **out of this plan**; it gets its own plan.

## ZXTouch protocol (read from gitssie/zxtouchrootless source, pccontrol/ + python client)

- Request: `f"{task}{';;'.join(args)}\r\n"` (task id is glued to the first arg, no separator).
- Response line: `0;;field;;field\r\n` = ok, `-1;;message\r\n` = error.
- Touch (task 10): `"10" + str(n) + "".join(f"{type}{finger:02d}{int(x*10):05d}{int(y*10):05d}")`; type 0=up 1=down 2=move; **no response**.
- Touch x/y are in the units returned by screen size (task `25` arg `1` → `0;;width;;height`), portrait, width < height. Map through that size; never assume points vs pixels.
- Keyboard (task 24): `24` + `1;;<char>` insert text, `4;;1` delete one char; each returns a response line.
- Screenshot (task 30): response `0;;image/jpeg;;<len>\r\n` + `len` JPEG bytes.
- Orientation (task `25` arg `2`): `0;;<n>`.

## Review Focus

1. Window resized / non-matching aspect → clicks in the black letterbox bars must be ignored, not clamped to an edge tap. (Task 2 test)
2. Phone rotated to landscape → taps must land where clicked. (Task 2 test for rotation 90/270)
3. Mouse released outside the window during a drag → a touch-up must still be sent, or the phone keeps a stuck finger. (Task 4 test)
4. Non-ASCII typed text (`è`, emoji) and the `;;` / CRLF sequences in text → must not corrupt the protocol stream. (Task 1 test)
5. Phone unplugged / ZXTouch not installed → clear one-line error and exit code 1, not a traceback. (Task 6 test)

---

### Task 0: Spike on the real device (throwaway, manual, not reviewed)

Needs the iPhone plugged in. Results go into the "Spike results" section at the bottom of this file and may adjust later tasks.

- [ ] Install ZXTouch Rootless on the phone (Sileo repo `https://gitssie.github.io/zxtouchrootless`), respring.
- [ ] In a venv: `pip install pymobiledevice3`, then a ≤15-line script in scratchpad: `select_device()` → `connect(6000)` → send `b"25" + b"1\r\n"`, print reply; send a tap at the screen centre (down + up). Record: reply, whether the tap happened, the exact pymobiledevice3 call names that worked.
- [ ] Insert `a`, then `\n` via `241;;\n`… record whether Enter works as newline/submit.
- [ ] Build/run `qvh` on Fedora (`go install github.com/danielpaulus/quicktime_video_hack@latest` or its Docker deps), run `qvh gstreamer`. Record: does video appear, latency feel, and **how to get raw Annex-B H.264 on stdout** (`qvh gstreamer --examples` / custom pipeline with `fdsink`). If none works, record the screenshot fps instead and default `--video` to `screenshot`.
- [ ] Rotate to landscape: record orientation value and the qvh frame size, to fix the orientation→rotation table in Task 2.
- [ ] From another machine on the same Wi-Fi: `nc <phone-ip> 6000` — record whether it connects (see security note).

### Task 1: Project + ZXTouch client

**Files:**
- Create: `pyproject.toml`, `scrcrappy/__init__.py` (empty), `scrcrappy/zxtouch.py`
- Test: `tests/test_zxtouch.py`

**Interfaces:**
- Produces:
  - `UP, DOWN, MOVE = 0, 1, 2`
  - `encode(task: int, *args) -> bytes`
  - `encode_touch(events: list[tuple[int, int, float, float]]) -> bytes` — `(type, finger, x, y)`
  - `class ZXTouch(sock: socket.socket)` with `touch(events)`, `screen_size() -> tuple[float, float]`, `orientation() -> int`, `insert_text(text: str)`, `delete_backward(n: int = 1)`, `screenshot() -> bytes`, `close()`. Raises `ZXTouchError(str)` on `-1` replies.

- [ ] **Step 1: pyproject** — deps `pygame-ce`, `av`, `pymobiledevice3`; dev dep `pytest`; console script `scrcrappy = scrcrappy.__main__:main`. `pip install -e .[dev]`.
- [ ] **Step 2: Write failing tests**

```python
def test_encode_touch_single_down():
    assert encode_touch([(DOWN, 1, 187.5, 406.0)]) == b"1011010187504060\r\n"

def test_encode_touch_two_fingers():
    assert encode_touch([(MOVE, 1, 10, 20), (MOVE, 2, 30, 40)]) == b"10220100100002002020030000400\r\n"

def test_screen_size_parses_reply():   # socket.socketpair(); peer writes b"0;;375;;812\r\n"
    assert ZXTouch(a).screen_size() == (375.0, 812.0)

def test_error_reply_raises():         # peer writes b"-1;;nope\r\n"
    with pytest.raises(ZXTouchError, match="nope"): ZXTouch(a).orientation()

def test_screenshot_reads_exact_bytes():  # peer writes b"0;;image/jpeg;;3\r\nabc" + b"0;;1\r\n"
    z = ZXTouch(a); assert z.screenshot() == b"abc"; assert z.orientation() == 1

def test_insert_text_unsafe_chars_sent_one_char_per_command():
    # "è;;\r\n" -> each char its own 24-command; ';;' never appears inside an arg,
    # '\r' is dropped, '\n' kept. Assert the exact bytes the peer receives.
```

- [ ] **Step 3: Run** `pytest tests/test_zxtouch.py -v` → FAIL (import error).
- [ ] **Step 4: Implement** `scrcrappy/zxtouch.py`. Buffered line reader (keep leftover bytes, as the upstream client does). `insert_text` sends one char per command and reads each reply; a `;` char is sent alone so `;;` can never form inside one arg; `\r` is dropped.
- [ ] **Step 5: Run** → PASS.
- [ ] **Step 6: Commit** `feat: ZXTouch protocol client`.

### Task 2: Coordinate mapping

**Files:**
- Create: `scrcrappy/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Produces:
  - `fit(frame: tuple[int,int], window: tuple[int,int]) -> pygame.Rect`-compatible `tuple[int,int,int,int]` (x, y, w, h of the letterboxed frame)
  - `to_device(pos: tuple[int,int], rect: tuple[int,int,int,int], rotation: int, size: tuple[float,float]) -> tuple[float,float] | None` — `None` if outside `rect`; `rotation` ∈ {0, 90, 180, 270} = clockwise rotation of the displayed frame relative to portrait; `size` = ZXTouch portrait screen size.
  - `ROTATION_BY_ORIENTATION: dict[int, int]` — `{1: 0, 2: 180, 3: 90, 4: 270}`, ponytail: unverified until Task 0 landscape check.

- [ ] **Step 1: Failing tests**

```python
def test_fit_letterboxes_tall_frame():
    assert fit((1125, 2436), (1000, 1000)) == (269, 0, 462, 1000)

def test_centre_maps_to_centre():
    assert to_device((500, 500), (269, 0, 462, 1000), 0, (375, 812)) == pytest.approx((187.5, 406), abs=1)

def test_click_in_letterbox_is_ignored():
    assert to_device((10, 500), (269, 0, 462, 1000), 0, (375, 812)) is None

def test_rotation_90_top_left_of_frame():
    # landscape frame shown 1000x461; its top-left = portrait bottom-left for 90° cw
    assert to_device((0, 0), (0, 0, 1000, 461), 90, (375, 812)) == pytest.approx((0, 812), abs=1)

def test_rotation_270_top_left_of_frame():
    assert to_device((0, 0), (0, 0, 1000, 461), 270, (375, 812)) == pytest.approx((375, 0), abs=1)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (`fit`: w/h = round(scale × side), offset = (window − size) // 2; `to_device`: normalize to 0..1 inside rect, rotate the unit point, scale by `size`). **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: window to device coordinate mapping`.

### Task 3: Video sources

**Files:**
- Create: `scrcrappy/video.py`
- Test: `tests/test_video.py`

**Interfaces:**
- Consumes: `ZXTouch.screenshot()` (Task 1).
- Produces: `class LatestFrame` — `put(surface_bytes: bytes, size: tuple[int,int])`, `get() -> tuple[bytes, tuple[int,int]] | None` (returns newest, `None` if nothing new since last get), thread-safe.
  `start_screenshot(client: ZXTouch, out: LatestFrame) -> threading.Thread` (daemon; decodes JPEG via `pygame.image.load(BytesIO)` → `pygame.image.tobytes(s, "RGB")`).
  `start_qvh(cmd: list[str], out: LatestFrame) -> subprocess.Popen` — runs `cmd`, `av.open(proc.stdout, format="h264")`, each frame `to_ndarray(format="rgb24").tobytes()` into `out`, in a daemon thread. Exact `cmd` comes from Task 0.

- [ ] **Step 1: Failing tests** — `test_latest_frame_drops_old` (put A, put B, get → B, get → None); `test_screenshot_source_puts_decoded_frame` (fake client returning a 2×3 JPEG made with pygame; frame size == (2, 3)).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: qvh and screenshot video sources`. (qvh path verified manually in Task 4.)

### Task 4: Window + mouse

**Files:**
- Create: `scrcrappy/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: `class Controller(client: ZXTouch, size: tuple[float,float])` with `handle(event: pygame.event.Event, rect, rotation) -> None` (pure w.r.t. pygame display; testable with synthetic events) and `run(client, frames: LatestFrame, title: str) -> None` (the window loop).

Behaviour (design "Mouse"):
- LMB down inside frame → `DOWN` finger 1; motion with LMB held → `MOVE` (positions outside the frame are clamped **only while a touch is active**); LMB up anywhere, or `WINDOWFOCUSLOST`/`WINDOWLEAVE` while active → `UP` at last position.
- Wheel → swipe of 10% of screen height per notch at the cursor: DOWN, 5 MOVEs, UP, ~8 ms apart.
- Window resizable; frame redrawn with `fit`; rotation from `ROTATION_BY_ORIENTATION[client.orientation()]` polled on a **second** ZXTouch connection when frame aspect flips (not every frame).

- [ ] **Step 1: Failing tests** with a fake client recording `touch` calls:
  `test_click_sends_down_up`, `test_drag_sends_moves`, `test_release_outside_window_sends_up`, `test_focus_lost_mid_drag_sends_up`, `test_click_in_letterbox_sends_nothing`, `test_wheel_sends_swipe`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual** — with phone: open Settings by clicking it, scroll a list with the wheel, drag a slider.
- [ ] **Step 6: Commit** `feat: window with mouse control`.

### Task 5: Keyboard, clipboard, gestures

**Files:**
- Modify: `scrcrappy/app.py`
- Test: `tests/test_app.py`

Behaviour:
- `TEXTINPUT` → `insert_text(event.text)`; `K_BACKSPACE` → `delete_backward()`; `K_RETURN` → `insert_text("\n")` (or what Task 0 found).
- `Ctrl+V` (`Cmd+V` on macOS: check `KMOD_CTRL | KMOD_META`) → `pygame.scrap.get_text()` → `insert_text`.
- `Alt+H` → Home: swipe finger 1 from (0.5, 0.995) to (0.5, 0.6) of portrait size in ~150 ms.
- `Alt+S` → App switcher: same swipe to (0.5, 0.7), hold 400 ms, then UP.
- Ctrl + LMB drag → pinch: finger 1 at point p, finger 2 at `(w - x, h - y)`, sent together via one `touch` call per step.

- [ ] **Step 1: Failing tests** — `test_typing_inserts_text`, `test_backspace_deletes`, `test_ctrl_v_pastes_clipboard` (monkeypatch `pygame.scrap.get_text`), `test_alt_h_swipes_from_bottom`, `test_ctrl_drag_sends_mirrored_second_finger`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual** — type into Notes, Backspace, Enter, paste from computer, Home, app switcher, pinch a photo.
- [ ] **Step 6: Commit** `feat: keyboard, clipboard paste, gestures`.

### Task 6: CLI + auto-detect

**Files:**
- Create: `scrcrappy/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int`.
- Flags: `--input {auto,jailbreak}` (default auto; `esp32` added by its own plan), `--video {qvh,screenshot}` (default from Task 0), `--qvh PATH` (default `qvh` on PATH).

Flow: `select_device()` (none → `error: no iPhone connected over USB`, return 1) → connect device port 6000 (refused → `error: ZXTouch not reachable on the device (installed? respring?)`, return 1) → `screen_size()` → start video → `run()`. `--video qvh` with qvh missing → `error: qvh not found, use --video screenshot`, return 1.

- [ ] **Step 1: Failing tests** — monkeypatch the device lookup/connect: `test_no_device_exits_1_with_message`, `test_zxtouch_unreachable_exits_1`, `test_missing_qvh_exits_1` (all assert stderr text and return value, no traceback).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual** — `scrcrappy` end to end on Fedora; on macOS if available.
- [ ] **Step 6: Commit** `feat: CLI and device detection`.

## Spike results

_(filled in during Task 0)_
