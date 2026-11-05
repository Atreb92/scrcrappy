# Reliable pointer calibration (both axes)

## Problem

Calibration (`calibrate.py`) measured the pointer gain table (screen px per count, by report length) once per
length, horizontally only, with the travel planned from `DEFAULT_GAIN`. On the user's iPhone 8 (macOS host,
ESP32 link) it failed or varied between runs. Measured on 2026-11-06:

1. **Dropped and queued reports.** The ESP32 firmware never asked for a connection interval and iOS granted a slow
   one (~30–45 ms) while the host sends a report every 15 ms. At that pace 100 reports of length 2 moved the cursor
   166 px instead of 352, and the cursor kept moving up to 1.6 s after the last report. How many reports got lost
   decided the result (lengths 3, 4, 6 came out halved in one run). **Fixed** on branch `ble-pacing`
   (commit 870aa96): the firmware requests 11.25–15 ms, iOS grants 15 ms, nothing is lost, the cursor stops
   30–90 ms after the last report, and the firmware tells the host `interval <µs>`.
2. **Short lengths hit the screen edge.** The report count `n = 250 / (length · guess)` uses `DEFAULT_GAIN`, which is
   about half this phone's real gain. Lengths 1–3 then end at x ≈ 740 (the right edge) every run, so their values
   are "edge distance / counts sent": length 2 is saved as 1.0 px/count, a slow burst measures 1.76.
3. **One sample per length, no sanity check.** A saved table had length 6 (1.208) below length 4 (1.701).
4. **Intermittent "can't see the cursor"** (about 1 in 4 runs, on the first look after start-up). Cause unknown: the
   cursor does not fade (after 20 s idle it is fully visible within ~100 ms of moving; calibrate looks after 350 ms),
   and on a plain screen its pixels (median RGB 150,148,152) pass the gray rule 93 %. Needs evidence.
5. **Vertical moves land 5–10 % short** (TODO.md): only the x axis is measured, and its table is used for both.

## Goal

The same phone, tracking speed and link give the same table (each length within a few percent) every run; a bad run
never replaces a good table; a failure leaves evidence; x and y each get their own table.

## Design

### Measurement (`calibrate.py`)

- **Probe:** home, nudge out (`(4, 4) × 15`, as today), look, send `(8, 0) × 5`, look. `ratio = measured / DEFAULT_GAIN(8)`
  scales the first guess. A probe that ends near an edge or does not move right fails the run.
- **Lengths:** `LENGTHS` as today (1 … 24), measured in increasing order, first on x (reports `(L, 0)`), then on y
  (`(0, L)`). The guess for a length is `DEFAULT_GAIN(L) · (measured(prev) / DEFAULT_GAIN(prev))` from the previous
  length on the same axis (the probe's ratio for the first). `n = max(3, round(TRAVEL / (L · guess)))`, `TRAVEL = 250`.
- **Samples:** 3 per length. A sample: home, nudge out, look (`a`), send `n` reports, look (`b`);
  gain = `(b − a) on that axis / (n · L)`.
- **Edge guard:** a sample whose `b` lies within `EDGE = 40` px of the frame edge on the moving axis, or that moved
  ≤ 0, is redone once with `n // 2` (at least 3). If the redo also fails, the run fails ("the cursor hit the screen
  edge / didn't move").
- **Result per length:** the median of the 3 samples, rounded to 3 decimals. A spread (max − min) above 5 % of the
  median prints a warning line naming the length and axis; it does not fail the run.
- **Sanity check:** on each axis, every gain must be ≥ 0.97 × the gain of the next shorter length. Otherwise the run
  fails ("gains went down from length A to B on y: …") and nothing is saved.
- **Looking for the cursor:** after the 0.35 s settle, if `find_cursor` misses, keep trying each new frame
  (`LatestFrame.peek`) for up to 1 s. A final miss saves that frame as PNG to `~/.config/scrcrappy/calibrate-miss.png`
  and the error names it. The look right after homing (cursor half off-screen) is not done any more: nothing uses it.
- **Duration:** about 2 minutes (9 lengths × 2 axes × 3 samples + probe), up from ~40 s.

### Gain table (`mouse.py`, gain file)

- `Gain` stays "px per count as a function of report length". A new `Gains(x: Gain, y: Gain)` (a NamedTuple)
  is what `load` returns and `Pointer` takes; the pointer's move list becomes `((dx, dy), (gx(L) · dx, gy(L) · dy))` with `L = hypot(dx, dy)`.
- `DEFAULT_GAIN` is used for both axes when nothing is saved.
- File `gain-<serial>.json`: `{"x": {"1": …, …}, "y": {"1": …, …}}`. `load` also accepts the old flat format
  (`{"1": …}`), used for both axes, so the pointer works the same until the user recalibrates. Invalid content
  falls back to `DEFAULT_GAIN` as today.
- `Calibrator.value()` (the number Settings shows) is the x gain at length 12.

### Pace follows the link (`links.py`, `mouse.py`, `__main__.py`, `calibrate.py`)

- `Link` parses `interval <µs>` lines (any number of them; the last wins) into `link.interval` (seconds, `None`
  until reported). `Link.pace()` = `max(TICK, interval or 0)`.
- `Pointer` and `calibrate` take the pace from the link (a `pace: float = TICK` argument) instead of the `TICK`
  constant, so both always run at the same pace (iOS acceleration may depend on speed, and the gain is only valid at
  the pace it was measured at). The pace is read when the pointer / calibration starts.
- `blemouse.py` (Linux adapter) prints no interval: pace stays 15 ms there. The firmware fix itself is ESP32-only.

### Texts

- `CALIBRATE_TIP` (Settings): "… don't touch the mouse for about 2 minutes."
- MCP `calibrate` tool description: "about two minutes".
- `app.CALIBRATE_WAIT_S` 120 → 300, and its comment.
- README calibration section: duration, both axes, the miss PNG.
- TODO.md: remove the vertical-moves item; note Linux BT-adapter interval as unverified.

## Testing

- **Simulated phone** for `calibrate`: a fake `send` that moves a virtual cursor by `gx(L)·dx, gy(L)·dy` (clamped to
  750 × 1334), and a `LatestFrame` that serves a light frame with the gray disk drawn there. Tests:
  - gains of 2 × `DEFAULT_GAIN` (the real phone): no sample reaches the edge guard, the table matches the simulated
    gains on both axes;
  - one sample of three is off (a dropped report): the median is still right, a spread warning is printed;
  - a simulated gain that drops with length: the run fails and `save` is never called;
  - the cursor missing for 0.5 s then visible: found; missing for good: error naming the PNG, which exists;
  - the edge guard: a sample ending near the edge is redone with half the reports.
- `load`: the new format, the old flat format (both axes), garbage (defaults).
- `Pointer`: a report's predicted displacement uses `gx` for x and `gy` for y.
- `Link`: `interval 15000` → `interval == 0.015`, `pace() == TICK`; `interval 30000` → `pace() == 0.03`; none → `TICK`.
- **Real phone** (iPhone 8, ESP32): 3 calibrations in a row, spread per length and axis ≤ 5 %; the burst test
  (100 reports at the pace) still loses nothing; a long vertical move lands on its target.

## Not covered

- Closed-loop correction from the video (approach B).
- The Linux BT adapter's connection interval (`blemouse.py`): to check on the Linux machine.
- Why the first look sometimes misses: this design makes the next miss leave a frame to look at.
