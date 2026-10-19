"""AI control (MCP) for the running window: the tools for the active input mode, and what the window shows
while an AI works (status LED, touch rings). Tools run on the MCP request thread and only use thread-safe
pieces: the agent Session, the pointer's queue, the key queue and LatestFrame."""
import base64
import json
import secrets
import threading
import time
from typing import Callable

from . import actions
from .agent_cli import ERRORS
from .config import Config
from .mcp import PORT, McpServer, Tool, ToolError

GREEN, YELLOW, RED = (0x3C, 0xB3, 0x71), (0xF2, 0xB7, 0x05), (0xE0, 0x3E, 0x3E)
SESSION_S = 30  # "AI in a session" = any request this recent
RING_S = 0.6
FINGER = 4  # AI touches: the window's own drags use 1-3
REPLY_S = 35  # agent requests may wait 30 s for a prompt on the phone

POINT = {"x": {"type": "number", "minimum": 0, "maximum": 100, "description": "percent of the screenshot width, from the left"},
         "y": {"type": "number", "minimum": 0, "maximum": 100, "description": "percent of the screenshot height, from the top"}}
COORDS = ("Coordinates are percent (0-100, decimals ok) of the upright screenshot from the screenshot tool, "
          "x from the left, y from the top.")


class AiControl:
    """`session` (agent mode) or `pointer` (Bluetooth / ESP32: returns the current Pointer or None) plus `keys`;
    neither: screenshots only."""

    def __init__(self, frames, session=None, pointer: Callable | None = None, keys=None) -> None:
        self.frames, self.session, self.pointer, self.keys = frames, session, pointer, keys
        self.server: McpServer | None = None
        self.error: str | None = None
        self.rings: list[tuple[float, float, float]] = []  # x %, y %, monotonic time

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

    def command(self, cfg: Config) -> str:
        return (f"claude mcp add --transport http scrcrappy http://127.0.0.1:{PORT}/mcp "
                f"--header \"Authorization: Bearer {cfg.mcp_token}\"")

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
        if self.session:
            found.append(Tool("clipboard", "The phone's clipboard text. Fails if the phone asks Allow Paste.",
                              {"type": "object", "properties": {}}, self.clipboard))
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

    def long_press(self, args: dict) -> list[dict]:
        x, y = _point(args, "x", "y")
        return self._touch(actions.long_press(x, y, args.get("ms")))

    def swipe(self, args: dict) -> list[dict]:
        (x1, y1), (x2, y2) = _point(args, "x1", "y1"), _point(args, "x2", "y2")
        return self._touch(actions.swipe(x1, y1, x2, y2, args.get("ms")))

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
        return [{"type": "text", "text": f"typed {len(text) - skipped} characters"
                                         + (f", skipped {skipped} (US layout, ASCII only)" if skipped else "")}]

    def clipboard(self, args: dict) -> list[dict]:
        return [{"type": "text", "text": self._call({"cmd": "clipboard_get"})["text"]}]

    # --- helpers
    def _touch(self, steps: list[actions.Step]) -> list[dict]:
        self.rings.append((steps[0][2], steps[0][3], time.monotonic()))
        if steps[-1][2:] != steps[0][2:]:
            self.rings.append((steps[-1][2], steps[-1][3], time.monotonic() + steps[-1][0]))
        if self.session:
            screen = self._call({"cmd": "screen"})
            if not screen.get("touch_ready", True):
                raise ToolError("touch the phone's screen once (needed after each reboot), then retry")
            for delay, phase, x, y in steps:
                time.sleep(delay)
                self.session.touch((FINGER, phase, *actions.to_portrait(x, y, screen["orientation"])))
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
                    p.wait_idle()  # press / release exactly at the point
                    p.button(phase == "down")
            p.wait_idle()
        return [{"type": "text", "text": "done"}]

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


def _point(args: dict, kx: str, ky: str) -> tuple[float, float]:
    try:
        x, y = float(args[kx]), float(args[ky])
    except (KeyError, TypeError, ValueError):
        raise ToolError(f"{kx} and {ky} are required numbers") from None
    if not (0 <= x <= 100 and 0 <= y <= 100):
        raise ToolError(f"coordinates are percent of the screenshot, 0-100: {x}, {y}")
    return x, y
