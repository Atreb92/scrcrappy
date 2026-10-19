"""Measure the pointer gain table from the video: move by known counts, find the cursor, divide."""
import json
import time
from pathlib import Path

import numpy as np

from .mouse import DEFAULT_GAIN, HOME_REPORTS, TICK, Gain, Send
from .video import Frame, LatestFrame

LENGTHS = (1, 2, 3, 4, 6, 8, 12, 16, 24)
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


def calibrate(send: Send, frames: LatestFrame) -> dict[int, float]:
    last: list[Frame | None] = [None]

    def paced(reports: list[tuple[int, int]]) -> tuple[float, float] | None:
        for dx, dy in reports:
            send(dx, dy, 0, 0)
            time.sleep(TICK)
        time.sleep(0.35)  # let the last frames arrive
        last[0] = frames.get() or last[0]
        return find_cursor(to_array(last[0])) if last[0] else None

    guess, table = Gain(DEFAULT_GAIN), {}
    for length in LENGTHS:
        paced([(-127, -127)] * HOME_REPORTS)
        a = paced([(4, 4)] * 15)  # out of the corner, so the whole cursor is visible
        n = max(3, round(250 / (length * guess(length))))  # ~250 px travel
        b = paced([(length, 0)] * n)
        if not (a and b):
            raise RuntimeError("can't see the cursor: open a plain light screen (e.g. Settings) and retry")
        table[length] = round((b[0] - a[0]) / (n * length), 3)
        print(f"  length {length:2}: {table[length]} px/count", flush=True)
    return table


def gain_path(serial: str) -> Path:
    return Path.home() / ".config" / "scrcrappy" / f"gain-{serial}.json"


def load(serial: str) -> dict[float, float]:
    try:
        return {float(k): v for k, v in json.loads(gain_path(serial).read_text()).items()}
    except (OSError, ValueError):
        return DEFAULT_GAIN


def save(serial: str, table: dict[int, float]) -> Path:
    path = gain_path(serial)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table))
    return path
