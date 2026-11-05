# Reliable Pointer Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibration gives the same per-axis gain table every run, never saves a bad table, and leaves a frame behind when it can't see the cursor; the pointer and calibration pace themselves to the BLE interval the ESP32 reports.

**Architecture:** `links.Link` learns the granted interval and offers `pace()`. `mouse.Gains(x, y)` replaces the single `Gain` in `Pointer`, which takes the pace. `calibrate.calibrate` is rebuilt from small testable pieces (look with retry, report planning, median, monotonic check) and measured end-to-end against a simulated phone with an injected `sleep`.

**Tech Stack:** Python 3.13, numpy, pygame-ce (PNG only), pytest (`.venv/bin/pytest -q`, SDL dummy driver).

**Spec:** `docs/superpowers/specs/2026-11-06-reliable-calibration-design.md`

## Global Constraints

- `TRAVEL = 250` px, `EDGE = 40` px, 3 samples per length, spread warning above 5 %, monotonic tolerance 0.97, look retry up to 1 s after the 0.35 s settle, `LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16, 24)`.
- Gain file `~/.config/scrcrappy/gain-<serial>.json`: `{"x": {"1": …}, "y": {"1": …}}`; the old flat format still loads (both axes).
- Miss frame: `~/.config/scrcrappy/calibrate-miss.png`.
- Pace = `max(TICK, interval)`; `TICK` stays 0.015. Pointer and calibration always use the same pace.
- Copy: tooltip "… don't touch the mouse for about 2 minutes."; MCP tool "about two minutes"; `CALIBRATE_WAIT_S = 300`.
- Match the surrounding code: short docstrings, one-line comments that say why, no new dependencies.

## Review Focus

1. A gray decoy on screen (the Settings avatar, a gray icon) next to the cursor's path: calibration must still measure the cursor, not the decoy. → test in Task 3.
2. A landscape frame (1334 × 750): edge guard and travel use the frame's real size. → test in Task 3.
3. The video stops mid-run (`frames.peek()` returns `None`): a clean "can't see the cursor" error, no crash while saving the miss frame. → test in Task 3.
4. The link reports a slow interval (30 ms): the pointer's loop and calibration both sleep 30 ms per report. → test in Task 1 (`Link.pace`) and Task 2 (`Pointer.pace`).
5. An old flat gain file left from an earlier version: the pointer keeps working with it on both axes until recalibrated. → test in Task 2.

---

### Task 1: Link reports the BLE interval and a pace

**Files:**
- Modify: `scrcrappy/links.py` (`Link.__init__` reader, new `pace`; module docstring protocol line)
- Test: `tests/test_links.py`

**Interfaces:**
- Produces: `Link.interval: float | None` (seconds, last `interval <µs>` line wins, `None` until one arrives); `Link.pace() -> float` = `max(mouse.TICK, interval or 0)`.

- [ ] **Step 1: Write the failing tests** (reuse `fake_board`'s pty pattern; make the board also write `interval 15000\n` / `interval 30000\n` after `connected`)

```python
def test_link_reads_the_granted_interval_and_paces_to_it():
    link = links.Link(lambda b: None, iter([b"ready\nconnected\ninterval 30000\n", b""]).__next__)
    assert link.connected.wait(1)
    for _ in range(100):
        if link.interval is not None:
            break
        threading.Event().wait(0.01)
    assert link.interval == pytest.approx(0.03)
    assert link.pace() == pytest.approx(0.03)


def test_link_pace_never_below_tick():
    from scrcrappy.mouse import TICK
    fast = links.Link(lambda b: None, iter([b"interval 7500\n", b""]).__next__)
    silent = links.Link(lambda b: None, iter([b""]).__next__)  # Linux helper: never reports one
    threading.Event().wait(0.05)
    assert fast.pace() == TICK and silent.interval is None and silent.pace() == TICK
```

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_links.py` — expected: the two new tests FAIL (`AttributeError: interval`).
- [ ] **Step 3: Implement.** In the reader, a line starting with `b"interval "` sets `self.interval = int(value) / 1e6` (ignore a malformed number); `pace()` as above (import `TICK` from `.mouse`). Add `"interval N"` to the docstring's device → host line.
- [ ] **Step 4: Run** `.venv/bin/pytest -q tests/test_links.py` — expected: all PASS.
- [ ] **Step 5: Commit** `git commit -am "Link: read the BLE interval the ESP32 reports, pace() never faster"`

### Task 2: Per-axis gains, pointer pace, gain file format

**Files:**
- Modify: `scrcrappy/mouse.py` (new `Gains`, `Pointer.__init__`, `start`, `wait_idle`)
- Modify: `scrcrappy/calibrate.py` (`load`, `save`, `Calibrator`)
- Modify: `scrcrappy/__main__.py:117-124` (pace from the link, `Pointer`/`Calibrator` wiring)
- Test: `tests/test_mouse.py`, `tests/test_app.py::test_calibrator_reports_current_value_and_saves_a_new_table`, new `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `Link.pace()` (Task 1).
- Produces:
  - `mouse.Gains(NamedTuple)`: fields `x: Gain`, `y: Gain`.
  - `Pointer(send: Send, gains: Gains, size: tuple[int, int], pace: float = TICK)`; attribute `pace`; move displacement `(gains.x(L) * dx, gains.y(L) * dy)`, `L = hypot(dx, dy)`.
  - `calibrate.Table = dict[str, dict[int, float]]` (keys `"x"`, `"y"`).
  - `calibrate.load(serial: str) -> Gains`; `calibrate.save(serial: str, table: Table) -> Path`.
  - `Calibrator(serial, send, frames, pace: float = TICK)`; `value() -> float` = `load(serial).x(12)`; `run()` calls `calibrate(self.send, self.frames, pace=self.pace)` then `save`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mouse.py — Phone takes Gains now: g = gains.x(L) * dx, gains.y(L) * dy
def test_each_axis_moves_by_its_own_gain():
    gains = Gains(Gain(DEFAULT_GAIN), Gain({k: v / 2 for k, v in DEFAULT_GAIN.items()}))
    phone = Phone(gains)
    p = Pointer(phone, gains, (750, 1334))
    p.move_to(300, 600)
    run(p)
    assert abs(phone.pos[0] - 300) <= 1 and abs(phone.pos[1] - 600) <= 1


def test_pointer_takes_the_links_pace():
    gains = Gains(Gain(DEFAULT_GAIN), Gain(DEFAULT_GAIN))
    assert Pointer(lambda *a: None, gains, (750, 1334)).pace == TICK
    assert Pointer(lambda *a: None, gains, (750, 1334), pace=0.03).pace == 0.03


# tests/test_calibrate.py
def test_load_reads_both_axes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.save("abc", {"x": {1: 1.0, 24: 3.0}, "y": {1: 0.5, 24: 2.0}})
    g = calibrate.load("abc")
    assert g.x(24) == 3.0 and g.y(24) == 2.0


def test_load_old_flat_file_is_used_for_both_axes(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.gain_path("abc").parent.mkdir(parents=True)
    calibrate.gain_path("abc").write_text('{"1": 0.9, "24": 2.8}')
    g = calibrate.load("abc")
    assert g.x(24) == g.y(24) == 2.8


@pytest.mark.parametrize("text", ["garbage", '{"x": {"1": -1}, "y": {"1": 1}}', '{"x": {}}'])
def test_load_falls_back_to_defaults(monkeypatch, tmp_path, text):
    monkeypatch.setenv("HOME", str(tmp_path))
    calibrate.gain_path("abc").parent.mkdir(parents=True)
    calibrate.gain_path("abc").write_text(text)
    g = calibrate.load("abc")
    assert g.x(12) == g.y(12) == DEFAULT_GAIN[12]
```

Update `test_calibrator_reports_current_value_and_saves_a_new_table`: the stub becomes `lambda send, frames, pace: {"x": {1: 1.0, 12: 2.5, 24: 3.0}, "y": {1: 1.0, 12: 2.0, 24: 3.0}}`, and the last assert `calibrate.load("abc").y(12) == 2.0`. Existing `tests/test_mouse.py` callers pass `Gains(gain, gain)` (update `setup()` and `Phone`).

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_mouse.py tests/test_calibrate.py tests/test_app.py` — expected: new tests FAIL (`ImportError: Gains`).
- [ ] **Step 3: Implement.** `Gains` NamedTuple in `mouse.py`; `Pointer` stores `pace` and uses it in `start()` and `wait_idle()` instead of `TICK`. `load`: dict with `"x"` and `"y"` → both; otherwise a flat dict → same `Gain` for both; any invalid / empty / non-positive table → `Gains(Gain(DEFAULT_GAIN), Gain(DEFAULT_GAIN))`. `save` writes `{"x": {...}, "y": {...}}`. In `__main__`, after `connected.wait()`: `pace = link.pace()`; `make_pointer = lambda size: mouse.Pointer(send, calibrate.load(serial), size, pace)`; `Calibrator(serial, send, frames, pace)`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — expected: all PASS.
- [ ] **Step 5: Commit** `git commit -am "Pointer: a gain per axis and the link's pace; gain file keeps x and y (old files still load)"`

### Task 3: Calibration that repeats, guards the edges and checks itself

**Files:**
- Modify: `scrcrappy/calibrate.py` (`calibrate` rebuilt; new `look`, `plan_reports`, `median_gain`, `check_monotonic`, `miss_path`)
- Modify: `scrcrappy/__main__.py` (`--calibrate` passes `pace`), `scrcrappy/app.py:21` (`CALIBRATE_WAIT_S = 300`, comment), `scrcrappy/dialog.py` (`CALIBRATE_TIP`), `scrcrappy/ai.py:105` (tool text), `README.md` (calibration paragraph, troubleshooting line), `TODO.md`
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `Gains`, `Table`, `save`, `Calibrator` (Task 2).
- Produces:
  - `calibrate(send: Send, frames: LatestFrame, pace: float = TICK, sleep: Callable[[float], None] = time.sleep, miss: Path | None = None, log: Callable[[str], None] = print) -> Table` (`miss` defaults to `miss_path()`).
  - `look(frames: LatestFrame, sleep, miss: Path) -> tuple[float, float]`: sleep 0.35, then up to 20 tries 0.05 s apart; final miss saves the last frame (if any) as PNG to `miss` and raises `RuntimeError` whose message names `miss` (or, with no frame at all, says the video stopped).
  - `plan_reports(length: int, guess: float) -> int` = `max(3, round(TRAVEL / (length * guess)))`.
  - `median_gain(samples: list[float]) -> tuple[float, float]`: (median rounded to 3 decimals, (max − min) / median).
  - `check_monotonic(table: Table) -> None`: raises `RuntimeError("gains went down from length A to B on <axis>: …")` when a gain < 0.97 × the previous length's.
  - `miss_path() -> Path` = `~/.config/scrcrappy/calibrate-miss.png`.

- [ ] **Step 1: Write the failing tests.** A `SimPhone` in `tests/test_calibrate.py`: `send(dx, dy, b, w)` moves a virtual cursor by `gains.x(L)·dx, gains.y(L)·dy` (clamped to `size`, default 750 × 1334), records each report; `sleep(s)` advances `self.clock`; `peek()` returns a `Frame` of a light (240) screen with a 36 px disk of (150, 148, 152) at the cursor unless `self.clock < self.hidden_until`, optional `decoy=(x, y)` draws a second disk, `video=False` returns `None`. Tests:

```python
def sim_gains(fx=2.0, fy=1.9):
    return Gains(Gain({k: v * fx for k, v in DEFAULT_GAIN.items()}), Gain({k: v * fy for k, v in DEFAULT_GAIN.items()}))

def run_cal(phone, tmp_path, **kw):
    return calibrate.calibrate(phone.send, phone, sleep=phone.sleep, miss=tmp_path / "miss.png", log=phone.log.append, **kw)

def test_measures_both_axes_of_a_fast_phone_without_hitting_the_edge(tmp_path):
    phone = SimPhone(sim_gains())
    table = run_cal(phone, tmp_path)
    for axis, gain in (("x", phone.gains.x), ("y", phone.gains.y)):
        for length in calibrate.LENGTHS:
            assert table[axis][length] == pytest.approx(gain(length), rel=0.03)
    assert phone.max_x < 750 - calibrate.EDGE and phone.max_y < 1334 - calibrate.EDGE

def test_sample_that_reaches_the_edge_is_redone_with_half_the_reports(tmp_path):
    jump = {**{k: v * 2 for k, v in DEFAULT_GAIN.items()}, 3: 2.6}  # length 3 far faster than 2 predicts
    phone = SimPhone(Gains(Gain(jump), Gain(jump)))
    table = run_cal(phone, tmp_path)
    assert table["x"][3] == pytest.approx(2.6, rel=0.03)
    assert phone.halved  # SimPhone notes a move of n // 2 reports right after one of n of the same length

def test_median_and_spread():
    assert calibrate.median_gain([1.0, 1.02, 0.5]) == (1.0, pytest.approx(0.52))

def test_spread_above_five_percent_is_warned(tmp_path):
    phone = SimPhone(sim_gains(), drop_every=7, drop_in_sample=2)  # loses reports in the 2nd sample of each length
    run_cal(phone, tmp_path)
    assert any("spread" in line for line in phone.log)

def test_gains_that_go_down_fail_and_save_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    down = {**DEFAULT_GAIN, 8: DEFAULT_GAIN[6] * 0.8}
    phone = SimPhone(Gains(Gain(down), Gain(DEFAULT_GAIN)))
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, pace: run_cal(phone, tmp_path))
    with pytest.raises(RuntimeError, match="went down from length 6 to 8 on x"):
        calibrate.Calibrator("abc", phone.send, phone).run()
    assert not calibrate.gain_path("abc").exists()

def test_cursor_that_shows_up_late_is_still_found(tmp_path):
    # the first look comes at ~0.76 s simulated (home + nudge + 0.35 s settle): 1.2 s needs the retries
    phone = SimPhone(sim_gains(), hidden_until=1.2)
    run_cal(phone, tmp_path)
    assert phone.looks_before_found > 1  # SimPhone counts peeks until the first visible frame

def test_cursor_never_seen_saves_the_frame_and_names_it(tmp_path):
    phone = SimPhone(sim_gains(), hidden_until=1e9)
    with pytest.raises(RuntimeError, match="miss.png"):
        run_cal(phone, tmp_path)
    assert (tmp_path / "miss.png").exists()

# Review Focus
def test_gray_decoy_off_the_path_is_ignored(tmp_path):          # 1
    phone = SimPhone(sim_gains(), decoy=(600, 900))
    assert run_cal(phone, tmp_path)["x"][12] == pytest.approx(phone.gains.x(12), rel=0.03)

def test_landscape_frame(tmp_path):                                # 2
    phone = SimPhone(sim_gains(), size=(1334, 750))
    table = run_cal(phone, tmp_path)
    assert phone.max_y < 750 - calibrate.EDGE and table["y"][24] == pytest.approx(phone.gains.y(24), rel=0.03)

def test_video_gone_is_a_clean_error(tmp_path):                    # 3
    phone = SimPhone(sim_gains(), video=False)
    with pytest.raises(RuntimeError, match="can't see the cursor"):
        run_cal(phone, tmp_path)

def test_reports_are_sent_at_the_given_pace(tmp_path):            # 4
    phone = SimPhone(sim_gains())
    run_cal(phone, tmp_path, pace=0.03)
    assert phone.report_sleeps == {0.03}  # SimPhone records each sleep that follows a send
```

- [ ] **Step 2: Run** `.venv/bin/pytest -q tests/test_calibrate.py` — expected: new tests FAIL (`TypeError: unexpected keyword 'sleep'` / missing names).
- [ ] **Step 3: Implement** in `calibrate.py`, following the spec's Measurement section. The sample loop:

```
probe: home; nudge (4,4)×15; a = look; send (8,0)×5; b = look      → ratio = gain / DEFAULT_GAIN(8)
for axis in ("x", "y"):
    prev_ratio = ratio
    for L in LENGTHS:
        n = plan_reports(L, DEFAULT_GAIN(L) * prev_ratio)
        samples = [sample(axis, L, n) for _ in range(3)]       # sample: home, nudge, a=look, send n, b=look
                                                               #   b within EDGE of frame edge or moved ≤ 0
                                                               #   → once more with max(3, n // 2), else raise
        table[axis][L], spread = median_gain(samples)
        if spread > 0.05: log(f"  {axis} length {L}: spread {spread:.0%}, samples {samples}")
        prev_ratio = table[axis][L] / DEFAULT_GAIN(L)
check_monotonic(table)
```

Every report is followed by `sleep(pace)`. The frame size for the edge guard comes from the looked-at frame. Drop the old post-homing look. Then the texts: `CALIBRATE_TIP` "… don't touch the mouse for about 2 minutes.", MCP tool "about two minutes", `CALIBRATE_WAIT_S = 300` ("a run takes about two minutes"), README (step 4 and the troubleshooting line: both axes, ~2 min, the miss PNG), TODO.md (drop the vertical item; add "Linux BT adapter: does BlueZ grant a 15 ms interval? (`blemouse.py` reports none, pace stays 15 ms)"). `__main__` `--calibrate`: `calibrate.calibrate(send, frames, pace)`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — expected: all PASS, suite still well under a minute.
- [ ] **Step 5: Commit** `git commit -am "Calibration: both axes, 3 samples per length, edge guard, monotonic check, miss frame saved"`

### Task 4: Real-phone verification (iPhone 8, ESP32 with the new firmware)

**Files:** none (scratch scripts only, in the session scratchpad)

- [ ] **Step 1:** Phone on Settings (`.venv/bin/scrcrappy agent --open Settings`); run calibration 3 times on one connection with `calibrate.calibrate(link.send, frames, pace=link.pace())`; print each table. Expected: every length on each axis within 5 % across the runs; x[2] ≈ 1.76 (the burst measurement).
- [ ] **Step 2:** Burst test (100 reports of length 2 at `link.pace()`): moved 352 px both times, cursor stops < 150 ms after the last report.
- [ ] **Step 3:** In the app (`.venv/bin/scrcrappy --mouse esp32`), after Settings › Calibrate: a long vertical move (top to bottom of Settings) lands on its target (user check).
- [ ] **Step 4:** Report the numbers to the user; nothing to commit unless a check fails (then back to the failing task).
