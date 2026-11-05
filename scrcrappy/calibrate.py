"""Measure the pointer gain table from the video: move by known counts, find the cursor, divide."""
import json
import statistics
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pygame

from .mouse import DEFAULT_GAIN, HOME_REPORTS, TICK, Gain, Gains, Send
from .video import Frame, LatestFrame

LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16, 24)
TRAVEL, EDGE = 250, 40  # px a sample aims to move; ending closer than EDGE to the screen's edge means it hit it
SAMPLES, SPREAD, DROP = 3, 0.05, 0.97  # samples per length; warn above this spread; a longer report may not be slower
SETTLE, RETRY, TRIES = 0.35, 0.05, 20  # s for the last frames to arrive; then up to TRIES newer frames, RETRY apart
NUDGE = [(4, 4)] * 15  # from the top-left corner to about (140, 140)
PROBE_LENGTH, PROBE_REPORTS = 8, 5  # first guess of this phone's speed
CHECK_LENGTH = 12  # the one vertical move that checks the horizontal table holds vertically too
Table = dict[str, dict[int, float]]  # {"x": {length: px per count}, "y": {...}}
K = 21  # detection box side, smaller than the ~36 px cursor disk
BLEND = (0.495, 27.5)  # the cursor over a screen pixel p reads 0.495 p + 27.5 (fitted, 0..255, within 4.4)
SHOWS = 20  # where the screen is within this of 54.5 (= 27.5 / (1 - 0.495)) the cursor doesn't change it


def find_cursor(img: np.ndarray) -> tuple[float, float] | None:
    """Centre of the AssistiveTouch cursor: a solid ~150-grey disk. Needs a plain, light screen
    (grey icons look the same)."""
    a = img.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return _disk_centre(((g >= 140) & (g <= 160) & (abs(r - g) <= 6) & (abs(b - g) <= 8)).astype(np.int32))


def find_cursor_on(img: np.ndarray, ref: np.ndarray) -> tuple[float, float] | None:
    """Centre of the cursor against `ref`, the same screen without it: where `img` is `ref` blended as BLEND says.
    Works on any screen (white, grey fields, black text, an avatar); what is part of the screen never matches."""
    a, r = img.astype(np.float32), ref.astype(np.float32)
    gain, offset = BLEND
    shows = (np.abs(r - offset / (1 - gain)) >= SHOWS).all(-1)  # pixels where the cursor would be visible
    match = shows & (np.abs(a - (gain * r + offset)) <= 8).all(-1)
    return _disk_centre(match.astype(np.int32), shows.astype(np.int32))


def _box_sums(m: np.ndarray) -> np.ndarray:
    s = np.pad(m, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return s[K:, K:] - s[:-K, K:] - s[K:, :-K] + s[:-K, :-K]


def _disk_centre(m: np.ndarray, judged: np.ndarray | None = None) -> tuple[float, float] | None:
    """Centre of the fullest K x K box that `m` fills (90 % of its `judged` pixels, at least half of the box being
    judged), refined to the centroid of the disk around it."""
    box = _box_sums(m)
    if judged is not None:
        known = _box_sums(judged)
        box = np.where((known >= K * K // 2) & (box >= 0.9 * known), box, -1)
    else:
        box = np.where(box > 0.9 * K * K, box, -1)
    y, x = np.unravel_index(box.argmax(), box.shape)
    if box[y, x] < 0:
        return None
    y0, x0 = max(0, y - K), max(0, x - K)  # first full box sits off-centre: centroid of the disk around it
    ys, xs = np.nonzero(m[y0 : y + 2 * K, x0 : x + 2 * K])
    return float(xs.mean() + x0), float(ys.mean() + y0)


def to_array(frame: Frame) -> np.ndarray:
    pixels, (w, h), pitch = frame
    return np.frombuffer(pixels, np.uint8).reshape(h, pitch)[:, : w * 3].reshape(h, w, 3)


class Cancelled(Exception):
    """The user cancelled a running calibration; nothing was saved."""


def miss_path() -> Path:
    """Where the frame goes when calibration can't find the cursor in it."""
    return Path.home() / ".config" / "scrcrappy" / "calibrate-miss.png"


def reference(frames: LatestFrame, sleep: Callable[[float], None]) -> np.ndarray:
    """The screen once the last frames are in (the cursor parked in the corner): what find_cursor_on compares to."""
    sleep(SETTLE)
    if not (frame := frames.peek()):
        raise RuntimeError("can't see the cursor: no video from the phone")
    return to_array(frame)


def look(frames: LatestFrame, sleep: Callable[[float], None], miss: Path, ref: np.ndarray) -> tuple[float, float]:
    """The cursor's centre once the last frames are in, trying newer frames for up to a second. A miss saves the
    frame it saw to `miss`."""
    sleep(SETTLE)
    frame = None
    for i in range(TRIES + 1):
        if i:
            sleep(RETRY)
        frame = frames.peek() or frame
        if frame and (pos := find_cursor_on(to_array(frame), ref)):
            return pos
    if frame is None:
        raise RuntimeError("can't see the cursor: no video from the phone")
    miss.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(pygame.surfarray.make_surface(to_array(frame).swapaxes(0, 1)), str(miss))
    raise RuntimeError("can't see the cursor: open a plain light screen (e.g. Settings scrolled to the top) and "
                       f"retry (the frame it looked at: {miss})")


def plan_reports(length: int, guess: float) -> int:
    """How many reports of `length` move the cursor about TRAVEL px at `guess` px per count."""
    return max(3, round(TRAVEL / (length * guess)))


def median_gain(samples: list[float]) -> tuple[float, float]:
    """The median, and how far the samples spread around it (fraction of it)."""
    median = statistics.median(samples)
    return round(median, 3), (max(samples) - min(samples)) / median


def check_monotonic(table: Table) -> None:
    """iOS accelerates longer reports more: a gain that goes down means a sample went wrong."""
    for axis, gains in table.items():
        pairs = sorted(gains.items())
        for (a, ga), (b, gb) in zip(pairs, pairs[1:]):
            if gb < DROP * ga:
                raise RuntimeError(f"gains went down from length {a} to {b} on {axis}: {ga} -> {gb}; "
                                   "retry on a plain light screen without touching the mouse")


def calibrate(send: Send, frames: LatestFrame, pace: float = TICK, sleep: Callable[[float], None] = time.sleep,
              miss: Path | None = None, log: Callable[[str], None] = print,
              cancel: threading.Event | None = None) -> Table:
    """A probe for the phone's speed, then SAMPLES horizontal moves per report length, each sized for about TRAVEL px;
    the median of each length is kept and used for both axes (iOS moves them alike: within 0.1 % on an iPhone 8),
    with one vertical move as a check. Reports go out every `pace` (the link's).
    `cancel`, once set, stops it within a report (raises Cancelled)."""
    miss = miss or miss_path()

    def paced(reports: list[tuple[int, int]]) -> None:
        for dx, dy in reports:
            if cancel and cancel.is_set():
                raise Cancelled()
            send(dx, dy, 0, 0)
            sleep(pace)
        if cancel and cancel.is_set():
            raise Cancelled()

    def sample(axis: str, length: int, n: int) -> float:
        """px per count from one move; one that hit the edge (or went nowhere) is redone with half the reports."""
        i, report = (0, (length, 0)) if axis == "x" else (1, (0, length))
        for count in (n, max(3, n // 2)):
            paced([(-127, -127)] * HOME_REPORTS)
            ref = reference(frames, sleep)  # the screen with the cursor out of the way
            paced(NUDGE)  # out of the corner, so the whole cursor is visible
            a = look(frames, sleep, miss, ref)
            paced([report] * count)
            try:
                b = look(frames, sleep, miss, ref)
            except RuntimeError:
                if count != n:
                    raise
                continue  # lost right after a move: most likely half off the screen's edge
            frame = frames.peek()
            limit = frame[1][i] if frame else float("inf")
            if b[i] > a[i] and b[i] < limit - EDGE:
                return (b[i] - a[i]) / (count * length)
        raise RuntimeError(f"the cursor hit the screen edge or didn't move ({axis}, length {length}): retry on a "
                           "plain light screen without touching the mouse")

    ratio = sample("x", PROBE_LENGTH, PROBE_REPORTS) / DEFAULT_GAIN[PROBE_LENGTH]  # this phone vs the defaults
    gains: dict[int, float] = {}
    for length in LENGTHS:
        n = plan_reports(length, DEFAULT_GAIN[length] * ratio)
        samples = [sample("x", length, n) for _ in range(SAMPLES)]
        gains[length], spread = median_gain(samples)
        log(f"  length {length:2}: {gains[length]} px/count")
        if spread > SPREAD:
            log(f"  length {length:2}: samples spread {spread:.0%} ({', '.join(f'{g:.3f}' for g in samples)})")
        ratio = gains[length] / DEFAULT_GAIN[length]
    check_monotonic({"x": gains})
    vertical = sample("y", CHECK_LENGTH, plan_reports(CHECK_LENGTH, gains[CHECK_LENGTH]))
    if abs(vertical / gains[CHECK_LENGTH] - 1) > SPREAD:
        log(f"  vertical moves differ: {vertical:.3f} px/count at length {CHECK_LENGTH}, horizontal "
            f"{gains[CHECK_LENGTH]}; the horizontal table is used for both")
    return {"x": gains, "y": dict(gains)}


def gain_path(serial: str) -> Path:
    return Path.home() / ".config" / "scrcrappy" / f"gain-{serial}.json"


def load(serial: str) -> Gains:
    """The saved tables; an older file holds one table, used for both axes. Anything unusable: the defaults."""
    default = Gains(Gain(DEFAULT_GAIN), Gain(DEFAULT_GAIN))
    try:
        raw = json.loads(gain_path(serial).read_text())
        axes = [raw["x"], raw["y"]] if "x" in raw else [raw, raw]
        tables = [{float(k): float(v) for k, v in axis.items()} for axis in axes]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return default
    if not all(t and all(v > 0 for v in t.values()) for t in tables):
        return default
    return Gains(Gain(tables[0]), Gain(tables[1]))


def save(serial: str, table: Table) -> Path:
    path = gain_path(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table))
    return path


class Calibrator:
    """Recalibration from the running app (Settings › Calibrate): measures with `send` and the video, saves for
    `serial`. The app rebuilds its pointer afterwards; make_pointer loads the saved table each time."""

    def __init__(self, serial: str, send: Send, frames: LatestFrame, pace: float = TICK) -> None:
        self.serial, self.send, self.frames, self.pace = serial, send, frames, pace
        self._cancel = threading.Event()

    def value(self) -> float:
        """Screen px per count for a medium horizontal report (12 counts): the one number Settings shows."""
        return load(self.serial).x(12)

    def begin(self) -> None:
        """Forget an earlier cancel; the app calls this on its own thread just before starting the worker, so a
        Cancel clicked right after the start can't be erased by the worker."""
        self._cancel.clear()

    def run(self) -> None:
        """Measure and save; raises Cancelled (saving nothing) after `cancel()`, even one during the last measurement."""
        table = calibrate(self.send, self.frames, pace=self.pace, cancel=self._cancel)
        if self._cancel.is_set():
            raise Cancelled()
        save(self.serial, table)

    def cancel(self) -> None:
        self._cancel.set()
