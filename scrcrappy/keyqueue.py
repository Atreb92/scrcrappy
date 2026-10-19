"""One ordered, paced stream of keyboard reports: live typing and pasted text never interleave."""
import collections
import threading
import time
from typing import Callable

from .typing_us import keystrokes

SendKeys = Callable[[int, list[int]], None]  # modifier bits, held key usages


class KeyQueue:
    def __init__(self, send_keys: SendKeys, gap: float = 0.01) -> None:
        self.send_keys, self.gap = send_keys, gap
        self.pending: collections.deque = collections.deque()
        self.lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def report(self, modifiers: int, keys: list[int]) -> None:
        with self.lock:
            self.pending.append((modifiers, list(keys)))

    def type_text(self, text: str) -> int:
        """Queue each character as key down + up; returns how many characters can't be typed."""
        strokes, skipped = keystrokes(text)
        with self.lock:
            for modifiers, usage in strokes:
                self.pending += [(modifiers, [usage]), (0, [])]
        return skipped

    def drain(self) -> bool:
        """Send the next queued report, if any."""
        with self.lock:
            if not self.pending:
                return False
            modifiers, keys = self.pending.popleft()
        self.send_keys(modifiers, keys)
        return True

    def start(self) -> None:
        def loop() -> None:
            while self._thread:
                time.sleep(self.gap if self.drain() else 0.002)

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._thread = None
