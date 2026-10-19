"""Jailbreak backend: scrcrappy-agent, a SpringBoard tweak reached over USB (protocol: its PROTOCOL.md).

Window clicks become touches at exact positions (no cursor to steer), keys become HID usages, and the
toolbar gets paste of any text, copy from the phone, screenshots and the phone's buttons.
"""
import base64
import io
import queue
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import pygame

from . import usbmux
from .agent_client import Agent, AgentError, encode_frame, load_secret, pairing_code, read_frame
from .geometry import ROTATION_BY_ORIENTATION, inside, rotation, to_device

POLL = 1.0  # s of idle worker between `screen` requests (orientation)
MOVE_GAP = 0.016  # s between touch moves: about the phone's screen rate
SWIPE = 0.1  # wheel notch = swipe of this fraction of the shown frame's height
CTRL, SHIFT, KEY_V = 0x11, 0x22, 0x19  # either side's modifier bits; V usage
MODIFIERS = range(0xE0, 0xE8)
BUTTONS, HOME, LOCK = 0x0C, 0x40, 0x30  # HID consumer page: the phone's buttons

HINTS = {
    "denied": "pairing was denied on the phone (or not answered within 30 s)",
    "locked": "unlock the phone, then start scrcrappy again to pair",
    "busy": "another pairing prompt is already on the phone; answer it and start scrcrappy again",
}


def connect(host: str, wait: float = 10) -> Agent:
    """An authenticated connection; the first time, pairs (the user taps Allow on the phone)."""
    deadline, error = time.monotonic() + wait, None
    while True:  # the phone may still be re-enumerating after video.reset_if_stuck
        try:
            udid = next(iter(usbmux.devices()), None)
        except OSError as e:
            udid, error = None, e
        if udid or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    if not udid:
        raise error or ConnectionError("usbmuxd lists no iPhone: unlock it, or unplug and replug it")
    secret = load_secret(udid)
    try:
        a = _open(udid)
        a.auth(host, secret)
        return a
    except AgentError as e:
        if str(e) != "unknown host":
            raise
    print(f"Pairing: tap Allow on the phone if it shows the code {pairing_code(secret)}", file=sys.stderr)
    try:
        _open(udid).pair(host, secret)
    except AgentError as e:
        raise AgentError(HINTS.get(str(e), str(e))) from None
    a = _open(udid)
    a.auth(host, secret)
    return a


def _open(udid: str) -> Agent:
    try:
        return Agent.connect(udid)
    except ConnectionRefusedError as e:
        raise ConnectionRefusedError(f"{e}: is scrcrappy-agent installed (and the phone booted to SpringBoard)?") from None


def _post(fn: Callable[[], None]) -> None:
    pygame.event.post(pygame.event.Event(pygame.USEREVENT, run=fn))  # thread-safe; app.run calls it


class Session:
    """Authenticated agent connection. Touches go out at once from the UI thread; requests run in order on
    a worker thread (some wait for an answer on the phone) and `done(reply)` is handed to `post`, which runs
    it on the UI thread. While idle the worker asks for the screen's orientation. A lost connection (qvh
    switching the phone's USB configuration, a respring) is reopened with `reopen`."""

    def __init__(self, sock, post: Callable[[Callable[[], None]], None] = _post,
                 reopen: Callable[[], socket.socket] | None = None) -> None:
        self.sock, self.post, self.reopen = sock, post, reopen
        self.orientation, self.warned = 1, False
        self.lock = threading.Lock()
        self.jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()

    def _send(self, obj: dict) -> None:
        with self.lock:  # whole frames: the UI thread and the worker both send
            self.sock.sendall(encode_frame(obj))

    def touch(self, *events: tuple[int, str, float, float]) -> None:
        """(finger, phase, x, y) events as one multi-finger update; no reply."""
        try:
            self._send({"cmd": "touch", "events": [{"finger": f, "phase": p, "x": x, "y": y} for f, p, x, y in events]})
        except OSError:
            pass  # phone gone; the window loop ends when the video does

    def request(self, obj: dict, done: Callable[[dict], None] | None = None,
                failed: Callable[[str], None] | None = None) -> None:
        """`failed(error)` (else a printed warning) when the agent replies with an error."""
        def job() -> None:
            try:
                self._send(obj)
                reply = read_frame(self.sock.recv)
            except (OSError, ValueError):
                if failed:  # tell a waiting AI tool now, not after its timeout
                    self.post(lambda: failed("agent connection lost; reconnecting"))
                raise
            if "error" in reply and failed:
                self.post(lambda: failed(reply["error"]))
            elif "error" in reply:
                print(f"agent: {obj['cmd']}: {reply['error']}", file=sys.stderr)
            elif done:
                self.post(lambda: done(reply))

        self.jobs.put(job)

    def pause(self, seconds: float) -> None:
        self.jobs.put(lambda: time.sleep(seconds))

    def swipe(self, a: tuple[float, float], b: tuple[float, float], steps: int = 6) -> None:
        """Finger 3 from a to b, then held still before lifting so iOS doesn't fling."""
        def job() -> None:
            self.touch((3, "down", *a))
            for i in range(1, steps + 1):
                time.sleep(MOVE_GAP)
                self.touch((3, "move", a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps))
            time.sleep(0.1)  # ponytail: fixed hold, tune if short swipes still coast or feel sluggish
            self.touch((3, "up", *b))

        self.jobs.put(job)

    def _screen(self, reply: dict) -> None:
        self.orientation = reply.get("orientation", 1)
        if not reply.get("touch_ready", True) and not self.warned:
            self.warned = True
            print("agent: touch the phone's screen once (needed after each reboot) before clicks work", file=sys.stderr)

    def _work(self) -> None:
        while True:
            try:
                job = self.jobs.get(timeout=POLL)
            except queue.Empty:
                self.request({"cmd": "screen"}, self._screen)
                continue
            try:
                job()
            except (OSError, ValueError) as e:
                print(f"agent: connection lost ({e}), reconnecting", file=sys.stderr)
                if not self.reopen:
                    return
                while not self._reconnect():
                    time.sleep(1)

    def _reconnect(self) -> bool:
        try:
            sock = self.reopen()
        except (OSError, AgentError):
            return False
        with self.lock:
            self.sock.close()
            self.sock = sock
        print("agent: reconnected", file=sys.stderr)
        return True

    def close(self) -> None:
        self.sock.close()


def screenshot_dir(folder: str = "") -> Path:
    """The Settings folder (created if needed), else ~/Pictures, else home."""
    if folder:
        path = Path(folder).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path
    pictures = Path.home() / "Pictures"
    return pictures if pictures.is_dir() else Path.home()


class Controller:
    """Window events -> agent: left drag = one finger, Ctrl+drag = pinch (second finger mirrored through
    the screen centre), wheel = short swipe, keys = HID usages by physical position."""

    def __init__(self, session: Session, natural_scroll: bool = False) -> None:
        self.s, self.natural_scroll = session, natural_scroll
        self.screenshots = ""  # folder from Settings
        self.fingers, self.at, self.moved = 0, (0.0, 0.0), 0.0
        self.modifiers = 0

    def _point(self, pos, rect, frame) -> tuple[float, float]:
        x, y, w, h = rect  # clamp: a drag that leaves the frame stays on its edge
        pos = (min(max(pos[0], x), x + w - 1), min(max(pos[1], y), y + h - 1))
        return to_device(pos, rect, rotation(self.s.orientation, frame), (1, 1))

    def _fingers(self, phase: str, at: tuple[float, float]) -> None:
        self.at = at
        events = [(1, phase, *at)]
        if self.fingers == 2:
            events.append((2, phase, 1 - at[0], 1 - at[1]))
        self.s.touch(*events)

    def lift(self) -> None:
        if self.fingers:
            self._fingers("up", self.at)
            self.fingers = 0

    def release(self) -> None:
        self.release_all()

    def release_all(self) -> None:
        self.lift()
        self.modifiers = 0  # keys released elsewhere never reach us

    def handle(self, event: pygame.event.Event, rect: tuple[int, int, int, int], frame: tuple[int, int]) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and inside(event.pos, rect) and not self.fingers:
            self.fingers = 2 if self.modifiers & CTRL else 1
            self._fingers("down", self._point(event.pos, rect, frame))
        elif event.type == pygame.MOUSEMOTION and self.fingers and time.monotonic() - self.moved >= MOVE_GAP:
            self.moved = time.monotonic()
            self._fingers("move", self._point(event.pos, rect, frame))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.fingers:
            self._fingers("up", self._point(event.pos, rect, frame))
            self.fingers = 0
        elif event.type == pygame.MOUSEWHEEL and event.y and not self.fingers:
            pos = pygame.mouse.get_pos()
            if inside(pos, rect):
                notches = -event.y if event.flipped else event.y  # undo the OS's own natural-scroll flip
                notches = -notches if self.natural_scroll else notches
                end = (pos[0], pos[1] + notches * SWIPE * rect[3])  # wheel up: finger down, content follows
                self.s.swipe(self._point(pos, rect, frame), self._point(end, rect, frame))
        elif event.type == pygame.WINDOWLEAVE:
            self.lift()  # never leave a finger down on the phone
        elif event.type == pygame.WINDOWFOCUSLOST:
            self.release_all()
        elif event.type in (pygame.KEYDOWN, pygame.KEYUP) and 0 < event.scancode <= 0xE7:
            down = event.type == pygame.KEYDOWN
            if event.scancode in MODIFIERS:
                bit = 1 << (event.scancode - 0xE0)
                self.modifiers = self.modifiers | bit if down else self.modifiers & ~bit
            elif down and event.scancode == KEY_V and self.modifiers & CTRL and self.modifiers & SHIFT:
                self.paste()
            elif down:
                self.s.request({"cmd": "key", "usage": event.scancode, "modifiers": self.modifiers})

    # --- toolbar
    def paste(self) -> int:
        """Types the computer's clipboard (any Unicode, via the phone's clipboard); nothing is skipped."""
        if text := pygame.scrap.get_text():
            self.s.request({"cmd": "text", "text": text})
        return 0

    def copy(self) -> None:
        def done(reply: dict) -> None:
            pygame.scrap.put_text(reply["text"])
            print(f"copied {len(reply['text'])} characters from the phone", file=sys.stderr)

        self.s.request({"cmd": "clipboard_get"}, done)  # may wait for the phone's Allow Paste prompt

    def screenshot(self) -> None:
        def done(reply: dict) -> None:
            img = pygame.image.load(io.BytesIO(base64.b64decode(reply["png"])), "screen.png")
            img = pygame.transform.rotate(img, -ROTATION_BY_ORIENTATION.get(self.s.orientation, 0))  # upright
            try:
                path = screenshot_dir(self.screenshots) / time.strftime("scrcrappy-%Y%m%d-%H%M%S.png")
                pygame.image.save(img, path)
            except (OSError, pygame.error) as e:
                print(f"screenshot not saved: {e}", file=sys.stderr)
                return
            print(f"screenshot saved: {path}", file=sys.stderr)

        self.s.request({"cmd": "screenshot"}, done)

    def button(self, usage: int) -> None:
        self.s.request({"cmd": "key", "page": BUTTONS, "usage": usage})

    def home(self) -> None:
        self.button(HOME)

    def switcher(self) -> None:
        self.button(HOME)
        self.s.pause(0.15)
        self.button(HOME)

    def lock(self) -> None:
        self.button(LOCK)

    def stop(self) -> None:
        self.release_all()
        self.s.close()  # the agent lifts anything still held when the connection closes
