"""AI control (MCP) for the running window: the tools for the active input mode, and what the window shows
while an AI works (status LED, touch rings). Tools run on the MCP request thread and only use thread-safe
pieces: the agent Session, the pointer's queue, the key queue and LatestFrame."""
import base64
import json
import math
import secrets
import threading
import time
from typing import Callable

from . import actions
from .calibrate import find_cursor, to_array
from .agent import BUTTONS, HOME, LOCK, SWITCHER_GAP
from .agent_cli import ERRORS, find_app, listed
from .config import Config
from .mcp import PORT, McpServer, Tool, ToolError

GREEN, YELLOW, RED = (0x3C, 0xB3, 0x71), (0xF2, 0xB7, 0x05), (0xE0, 0x3E, 0x3E)
SESSION_S = 30  # "AI in a session" = any request this recent
RING_S = 0.6
FINGER = 4  # AI touches: the window's own drags use 1-3
REPLY_S = 35  # agent requests may wait 30 s for a prompt on the phone
APP_SETTLE_S = 1.0  # after open_app: the agent replies before the app has drawn
SETTLE_S = 0.35  # after the pointer stops: let the last video frames arrive (as calibrate does)
POINTER_WAIT_S = 5  # after a calibration: the app rebuilds the pointer on the next frame
MAX_MS = 10_000  # longest long-press / swipe: the user's input is paused meanwhile

POINT = {"x": {"type": "number", "minimum": 0, "maximum": 100, "description": "percent of the screenshot width, from the left"},
         "y": {"type": "number", "minimum": 0, "maximum": 100, "description": "percent of the screenshot height, from the top"}}
COORDS = ("Coordinates are percent (0-100, decimals ok) of the upright screenshot from the screenshot tool, "
          "x from the left, y from the top.")


class AiControl:
    """`session` (agent mode) or `pointer` (Bluetooth / ESP32: returns the current Pointer or None) plus `keys`;
    neither: screenshots only."""

    def __init__(self, frames, session=None, pointer: Callable | None = None, keys=None,
                 calibrate: Callable[[], str] | None = None) -> None:
        """`calibrate` runs the app's pointer calibration, blocks, and returns a summary (RuntimeError: failed)."""
        self.frames, self.session, self.pointer, self.keys = frames, session, pointer, keys
        self.calibrate_pointer = calibrate
        self.server: McpServer | None = None
        self.error: str | None = None
        self._rings: list[tuple[float, float, float]] = []  # x %, y %, monotonic time to show it
        self._rings_lock = threading.Lock()  # added on the MCP thread, drawn on the window's
        self._down: tuple | None = None  # a press that hasn't been released yet (for cleanup)

    # --- server
    def enable(self, cfg: Config) -> None:
        cfg.mcp_token = cfg.mcp_token or secrets.token_urlsafe(24)
        if self.server:
            return
        server = McpServer(cfg.mcp_token, self.tools, PORT)
        try:
            server.start()
        except OSError as e:
            self.error = f"port {PORT} is in use ({e.strerror or e}); AI control is off"
            return
        self.server, self.error = server, None

    def disable(self) -> None:
        if self.server:
            self.server.stop()
        self.server = None

    def client_config(self, cfg: Config) -> str:
        """The server entry in the JSON most MCP clients take (`mcpServers`), with the token in it."""
        return json.dumps({"mcpServers": {"scrcrappy": {"type": "http", "url": f"http://127.0.0.1:{PORT}/mcp",
                                                        "headers": {"Authorization": f"Bearer {cfg.mcp_token}"}}}}, indent=2)

    def led(self, now: float | None = None) -> tuple[int, int, int] | None:
        if not self.server:
            return None
        now = time.monotonic() if now is None else now
        return RED if self.server.busy else YELLOW if now - self.server.last_request < SESSION_S else GREEN

    def locked(self) -> bool:
        return bool(self.server and self.server.busy)

    # --- tools
    def tools(self) -> list[Tool]:
        found = [Tool("screenshot", "The phone's screen as a PNG, upright, plus its width, height and orientation.",
                      {"type": "object", "properties": {}}, self.screenshot)]
        if not (self.session or self.pointer):
            return found
        found += [
            Tool("tap", f"Tap a point. {COORDS}", _schema(POINT), self.tap),
            Tool("long_press", f"Press and hold a point. {COORDS}",
                 _schema(POINT, ms={"type": "number", "description": f"hold time, default {actions.LONG_PRESS_MS}"}),
                 self.long_press),
            Tool("swipe", f"Drag from (x1, y1) to (x2, y2). {COORDS}",
                 _schema({f"{k}{n}": {**POINT[k]} for n in (1, 2) for k in ("x", "y")},
                         ms={"type": "number", "description": f"duration, default {actions.SWIPE_MS}"}), self.swipe),
            Tool("type_text", "Type text into the focused field." + (
                " Uses key presses when a US keyboard can type all of it, else pastes (the phone may ask "
                "Allow Paste)." if self.session else " US layout, printable ASCII; other characters are skipped."),
                 _schema({"text": {"type": "string"}}), self.type_text),
        ]
        if self.pointer:
            found.append(Tool("check_pointer", "Move the phone's pointer to a point without clicking and report how far "
                              "the cursor landed from it, in pixels. Needs a plain, light screen "
                              f"(e.g. Settings scrolled to the top) where the grey cursor disk is visible. {COORDS}", _schema(POINT), self.check_pointer))
            if self.calibrate_pointer:
                found.append(Tool("calibrate", "Recalibrate the pointer (about half a minute; the cursor moves by "
                                  "itself). Use when check_pointer shows taps landing off target. Needs a plain, "
                                  "light screen (e.g. Settings scrolled to the top) open on the phone.",
                                  {"type": "object", "properties": {}}, self.calibrate))
        if self.session:
            nothing = {"type": "object", "properties": {}}
            found += [
                Tool("clipboard", "The phone's clipboard text. Fails if the phone asks Allow Paste.", nothing, self.clipboard),
                Tool("list_apps", "The apps the phone can open: name, bundle id and whether each is running.", nothing,
                     self.list_apps),
                Tool("open_app", "Open an app, like tapping its icon: by name (any case) or bundle id, see list_apps. "
                     "Fails if the phone is locked.", _schema({"app": {"type": "string"}}), self.open_app),
                Tool("open_url", "Open a URL or deeplink like tapping a link (https:, tel:, maps:, app schemes…) in "
                     "whatever app handles it. Needs a scheme. Fails if the phone is locked.",
                     _schema({"url": {"type": "string"}}), self.open_url),
                Tool("home", "Press the Home button: go to the home screen.", nothing, self.home),
                Tool("switcher", "Open the app switcher (Home pressed twice).", nothing, self.switcher),
                Tool("lock", "Press the Lock button. The phone stays locked, and taps do nothing, until it is unlocked "
                     "on the phone.", nothing, self.lock),
            ]
        return found

    def screenshot(self, args: dict) -> list[dict]:
        if self.session:
            orientation = self._call({"cmd": "screen"})["orientation"]
            png = base64.b64decode(self._call({"cmd": "screenshot"})["png"])
            data, w, h = actions.upright_png(png, orientation)
            name = actions.ORIENTATIONS.get(orientation, "portrait")
        else:
            frame = self.frames.peek()
            if not frame:
                raise ToolError("no video yet")
            data, w, h = actions.frame_png(frame)
            name = "landscape" if w > h else "portrait"
        meta = {"width": w, "height": h, "orientation": name}
        return [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/png"},
                {"type": "text", "text": json.dumps(meta)}]

    def tap(self, args: dict) -> list[dict]:
        x, y = _point(args, "x", "y")
        return self._touch(actions.tap(x, y))

    def check_pointer(self, args: dict) -> list[dict]:
        x, y = _point(args, "x", "y")
        p, frame = self.pointer(), self.frames.peek()
        if not p or not frame:
            raise ToolError("the pointer isn't ready yet (no video, or calibrating)")
        target = (x / 100 * frame[1][0], y / 100 * frame[1][1])
        p.move_to(*target)
        _idle(p)
        time.sleep(SETTLE_S)
        found = find_cursor(to_array(self.frames.peek()))
        if not found:
            raise ToolError("can't see the cursor: open a plain, light screen (e.g. Settings scrolled to the top) and retry")
        err = math.hypot(found[0] - target[0], found[1] - target[1])
        report = {"target_px": [round(target[0]), round(target[1])], "cursor_px": [round(found[0]), round(found[1])],
                  "error_px": round(err, 1), "error_percent_of_width": round(100 * err / frame[1][0], 1)}
        return [{"type": "text", "text": json.dumps(report)}]

    def calibrate(self, args: dict) -> list[dict]:
        try:
            summary = self.calibrate_pointer()
        except RuntimeError as e:
            raise ToolError(str(e))
        end = time.monotonic() + POINTER_WAIT_S
        while not self.pointer() and time.monotonic() < end:
            time.sleep(0.05)
        return [{"type": "text", "text": summary}]

    def long_press(self, args: dict) -> list[dict]:
        x, y = _point(args, "x", "y")
        return self._touch(actions.long_press(x, y, _ms(args)))

    def swipe(self, args: dict) -> list[dict]:
        (x1, y1), (x2, y2) = _point(args, "x1", "y1"), _point(args, "x2", "y2")
        return self._touch(actions.swipe(x1, y1, x2, y2, _ms(args)))

    def type_text(self, args: dict) -> list[dict]:
        text = str(args.get("text", ""))
        if self.session:
            kind, strokes = actions.typing_plan(text)
            if kind == "keys":
                for modifiers, usage in strokes:
                    self._call({"cmd": "key", "usage": usage, "modifiers": modifiers})
            else:
                self._call({"cmd": "text", "text": text})
            return [{"type": "text", "text": f"typed with {kind}"}]
        if not self.keys:
            raise ToolError("no keyboard in this mode")
        skipped = self.keys.type_text(text)
        self.keys.wait_idle()  # typed on the phone before the AI's next screenshot
        return [{"type": "text", "text": f"typed {len(text) - skipped} characters"
                                         + (f", skipped {skipped} (US layout, ASCII only)" if skipped else "")}]

    def clipboard(self, args: dict) -> list[dict]:
        return [{"type": "text", "text": self._call({"cmd": "clipboard_get"})["text"]}]

    def list_apps(self, args: dict) -> list[dict]:
        return [{"type": "text", "text": json.dumps(listed(self._call({"cmd": "apps"})["apps"]), ensure_ascii=False)}]

    def open_app(self, args: dict) -> list[dict]:
        try:
            app = find_app(self._call({"cmd": "apps"})["apps"], str(args.get("app", "")))
        except ValueError as e:
            raise ToolError(str(e))
        self._call({"cmd": "open", "id": app["id"]})
        time.sleep(APP_SETTLE_S)
        return [{"type": "text", "text": f"opened {app['name']}"}]

    def open_url(self, args: dict) -> list[dict]:
        url = str(args.get("url", ""))
        self._call({"cmd": "open_url", "url": url})
        time.sleep(APP_SETTLE_S)
        return [{"type": "text", "text": f"opened {url}"}]

    def home(self, args: dict) -> list[dict]:
        return self._buttons(HOME)

    def switcher(self, args: dict) -> list[dict]:
        return self._buttons(HOME, HOME)

    def lock(self, args: dict) -> list[dict]:
        return self._buttons(LOCK)

    # --- helpers
    def _buttons(self, *usages: int) -> list[dict]:
        """The phone's buttons (HID consumer page), one request each, a short gap between presses."""
        for i, usage in enumerate(usages):
            if i:
                time.sleep(SWITCHER_GAP)
            self._call({"cmd": "key", "page": BUTTONS, "usage": usage})
        return [{"type": "text", "text": "done"}]

    def _touch(self, steps: list[actions.Step]) -> list[dict]:
        self.add_ring(steps[0][2], steps[0][3])
        if steps[-1][2:] != steps[0][2:]:
            self.add_ring(steps[-1][2], steps[-1][3], time.monotonic() + sum(s[0] for s in steps))
        try:
            if self.session:
                screen = self._call({"cmd": "screen"})
                if not screen.get("touch_ready", True):
                    raise ToolError("touch the phone's screen once (needed after each reboot), then retry")
                for delay, phase, x, y in steps:
                    time.sleep(delay)
                    point = actions.to_portrait(x, y, screen.get("orientation", 1))
                    self.session.touch((FINGER, phase, *point))
                    self._down = ("touch", point) if phase != "up" else None  # after it went out
                self._call({"cmd": "screen"})  # in order: every touch has been handled
            else:
                p = self.pointer()
                frame = self.frames.peek()
                if not p or not frame:
                    raise ToolError("the pointer isn't ready yet (no video, or calibrating)")
                w, h = frame[1]
                for delay, phase, x, y in steps:
                    time.sleep(delay)
                    p.move_to(x / 100 * w, y / 100 * h)
                    if phase != "move":
                        _idle(p)  # press / release exactly at the point
                        p.button(phase == "down")
                        self._down = ("button", p) if phase == "down" else None
                _idle(p)
        finally:
            self.cleanup()
        return [{"type": "text", "text": "done"}]

    def add_ring(self, x: float, y: float, at: float | None = None) -> None:
        with self._rings_lock:
            self._rings.append((x, y, time.monotonic() if at is None else at))

    def current_rings(self, now: float) -> list[tuple[float, float, float]]:
        """Rings to draw now; drops the expired ones, keeps the ones due later."""
        with self._rings_lock:
            self._rings = [r for r in self._rings if now - r[2] < RING_S]
            return [r for r in self._rings if now >= r[2]]

    def cleanup(self) -> None:
        """Release a press an interrupted touch left behind (a finger stuck down on the phone)."""
        if not self._down:
            return
        kind, what = self._down
        try:
            if kind == "touch":
                self.session.touch((FINGER, "up", *what))
            else:
                what.button(False)
        except OSError:
            return  # connection gone: the agent lifts a dropped connection's fingers itself
        self._down = None

    def _call(self, obj: dict) -> dict:
        """One agent request, waited for (the Session answers on the window's thread)."""
        done, result = threading.Event(), {}

        def ok(reply: dict) -> None:
            result["reply"] = reply
            done.set()

        def failed(error: str) -> None:
            result["error"] = error
            done.set()

        self.session.request(obj, ok, failed)
        if not done.wait(REPLY_S):
            raise ToolError("the phone didn't answer (agent disconnected?)")
        if "error" in result:
            raise ToolError(ERRORS.get(result["error"], result["error"]))
        return result["reply"]


def _schema(props: dict, **optional) -> dict:
    return {"type": "object", "properties": {**props, **optional}, "required": list(props)}


def _idle(pointer) -> None:
    if not pointer.wait_idle():
        raise ToolError("the pointer stopped moving (calibrating, or the Bluetooth link is gone)")


def _ms(args: dict) -> float | None:
    if args.get("ms") is None:
        return None
    try:
        ms = float(args["ms"])
    except (TypeError, ValueError):
        raise ToolError(f"ms must be a number of milliseconds, got {args['ms']!r}") from None
    if not 0 < ms <= MAX_MS:
        raise ToolError(f"ms must be between 1 and {MAX_MS}, got {ms:g}")
    return ms


def _point(args: dict, kx: str, ky: str) -> tuple[float, float]:
    try:
        x, y = float(args[kx]), float(args[ky])
    except (KeyError, TypeError, ValueError):
        raise ToolError(f"{kx} and {ky} are required numbers") from None
    if not (0 <= x <= 100 and 0 <= y <= 100):
        raise ToolError(f"coordinates are percent of the screenshot, 0-100: {x}, {y}")
    return x, y
