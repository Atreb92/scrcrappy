"""Drive the AssistiveTouch cursor with a relative mouse so it follows an absolute target.

iOS accelerates the pointer by the length of each HID report (not its direction), so we keep a
gain table (screen px per count, by report length), track where the cursor should be, and every
TICK send the integer report that lands closest to the target. Pacing is fixed because the gain
was measured at that rate.
"""
import collections
import math
import threading
import time
from typing import Callable

TICK = 0.008  # seconds between reports
MAX_LEN = 24  # longest report used; acceleration gets steep above this
HOME_REPORTS = 12  # (-127, -127) reports: far beyond any screen, cursor ends in the top-left corner

# iPhone 8, iOS 16.7.1, default AssistiveTouch tracking speed, frame px (750x1334). `--calibrate` replaces it.
DEFAULT_GAIN = {1: 0.40, 2: 0.415, 3: 0.60, 4: 0.95, 6: 1.30, 8: 1.48, 12: 1.66, 16: 1.74, 24: 1.83}

Send = Callable[[int, int, int, int], None]  # dx, dy, buttons, wheel


class Gain:
    """px per count as a function of report length, linearly interpolated from a measured table."""

    def __init__(self, table: dict[float, float]) -> None:
        self.points = sorted((float(k), v) for k, v in table.items())

    def __call__(self, length: float) -> float:
        pts = self.points
        if length <= pts[0][0]:
            return pts[0][1]
        for (l0, g0), (l1, g1) in zip(pts, pts[1:]):
            if length <= l1:
                return g0 + (g1 - g0) * (length - l0) / (l1 - l0)
        return pts[-1][1]


class Pointer:
    def __init__(self, send: Send, gain: Gain, size: tuple[int, int]) -> None:
        self.send, self.size = send, size
        self.pos = (0.0, 0.0)  # where the phone cursor should be, frame px
        self.target: tuple[float, float] | None = None
        self.buttons = 0
        self.homing = 0
        self.pending: collections.deque = collections.deque()
        self.lock = threading.Lock()
        # every report we may send, with the displacement it should cause
        self.moves = [((dx, dy), (g * dx, g * dy))
                      for dx in range(-MAX_LEN, MAX_LEN + 1) for dy in range(-MAX_LEN, MAX_LEN + 1)
                      if 0 < math.hypot(dx, dy) <= MAX_LEN for g in [gain(math.hypot(dx, dy))]]
        self._thread: threading.Thread | None = None

    # --- called from the UI thread; actions run in order
    def move_to(self, x: float, y: float) -> None:
        with self.lock:
            self.pending.append(("to", (x, y)))

    def button(self, down: bool) -> None:
        with self.lock:
            self.pending.append(("button", down))

    def wheel(self, notches: int) -> None:
        with self.lock:
            self.pending.append(("wheel", notches))

    def home(self) -> None:
        """Re-sync: park the cursor in the corner, where its position is known for sure."""
        with self.lock:
            self.pending.append(("home", None))

    # --- one tick of work; returns whether a report was sent
    def step(self) -> bool:
        with self.lock:
            if self.homing:
                self.homing -= 1
                self.send(-127, -127, self.buttons, 0)
                return True
            while self.pending and self.pending[0][0] == "to":
                x, y = self.pending.popleft()[1]
                self.target = (min(max(x, 0), self.size[0] - 1), min(max(y, 0), self.size[1] - 1))
            if move := self._next_move():
                (dx, dy), (px, py) = move
                self.send(dx, dy, self.buttons, 0)
                self.pos = (min(max(self.pos[0] + px, 0), self.size[0] - 1),
                            min(max(self.pos[1] + py, 0), self.size[1] - 1))
                return True
            if not self.pending:
                return False
            kind, arg = self.pending.popleft()
            if kind == "button":
                self.buttons = 1 if arg else 0
                self.send(0, 0, self.buttons, 0)
            elif kind == "wheel":
                self.send(0, 0, self.buttons, arg)
            else:  # home
                self.homing, self.pos = HOME_REPORTS - 1, (0.0, 0.0)
                self.send(-127, -127, self.buttons, 0)
            return True

    def _next_move(self):
        """The report that brings the cursor closest to the target, or None if none gets closer."""
        if self.target is None:
            return None
        rx, ry = self.target[0] - self.pos[0], self.target[1] - self.pos[1]
        best, best_err = None, math.hypot(rx, ry)
        for move in self.moves:
            px, py = move[1]
            err = math.hypot(rx - px, ry - py)
            if err < best_err:
                best, best_err = move, err
        return best

    def start(self) -> None:
        def loop() -> None:
            next_t = time.monotonic()
            while self._thread:
                self.step()
                next_t += TICK
                time.sleep(max(0.0, next_t - time.monotonic()))

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._thread = None

