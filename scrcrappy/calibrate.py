"""Measure the pointer gain table from the video: move by known counts, find the cursor, divide."""
import json
import threading
import time
from pathlib import Path

import numpy as np

from .mouse import DEFAULT_GAIN, HOME_REPORTS, TICK, Gain, Gains, Send
from .video import Frame, LatestFrame

LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16, 24)
Table = dict[str, dict[int, float]]  # {"x": {length: px per count}, "y": {...}}
K = 21  # detection box side, smaller than the ~36 px cursor disk


def find_cursor(img: np.ndarray) -> tuple[float, float] | None:
    """Centre of the AssistiveTouch cursor: a solid ~150-grey disk. Needs a plain, light screen
    (grey icons look the same)."""
    a = img.astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = ((g >= 140) & (g <= 160) & (abs(r - g) <= 6) & (abs(b - g) <= 8)).astype(np.int32)
    s = np.pad(m, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    box = s[K:, K:] - s[:-K, K:] - s[K:, :-K] + s[:-K, :-K]
    y, x = np.unravel_index(box.argmax(), box.shape)
    if box[y, x] <= 0.9 * K * K:
        return None
    y0, x0 = max(0, y - K), max(0, x - K)  # first full box sits off-centre: centroid of the disk around it
    ys, xs = np.nonzero(m[y0 : y + 2 * K, x0 : x + 2 * K])
    return float(xs.mean() + x0), float(ys.mean() + y0)


def to_array(frame: Frame) -> np.ndarray:
    pixels, (w, h), pitch = frame
    return np.frombuffer(pixels, np.uint8).reshape(h, pitch)[:, : w * 3].reshape(h, w, 3)


class Cancelled(Exception):
    """The user cancelled a running calibration; nothing was saved."""


def calibrate(send: Send, frames: LatestFrame, cancel: threading.Event | None = None, pace: float = TICK) -> dict[int, float]:
    """Measure the gain table. `cancel`, once set, stops it within a report (raises Cancelled)."""
    def paced(reports: list[tuple[int, int]]) -> tuple[float, float] | None:
        for dx, dy in reports:
            if cancel and cancel.is_set():
                raise Cancelled()
            send(dx, dy, 0, 0)
            time.sleep(TICK)
        if cancel and cancel.is_set():
            raise Cancelled()
        time.sleep(0.35)  # let the last frames arrive
        frame = frames.peek()
        return find_cursor(to_array(frame)) if frame else None

    guess, table = Gain(DEFAULT_GAIN), {}
    for length in LENGTHS:
        paced([(-127, -127)] * HOME_REPORTS)
        a = paced([(4, 4)] * 15)  # out of the corner, so the whole cursor is visible
        n = max(3, round(250 / (length * guess(length))))  # ~250 px travel
        b = paced([(length, 0)] * n)
        if not (a and b):
            raise RuntimeError("can't see the cursor: open a plain light screen (e.g. Settings scrolled to the top) and retry")
        table[length] = round((b[0] - a[0]) / (n * length), 3)
        if table[length] <= 0:
            raise RuntimeError("the cursor didn't move right: retry (Settings > Calibrate)")
        print(f"  length {length:2}: {table[length]} px/count", flush=True)
    return table


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
        table = calibrate(self.send, self.frames, self._cancel, self.pace)
        if self._cancel.is_set():
            raise Cancelled()
        save(self.serial, table)

    def cancel(self) -> None:
        self._cancel.set()
