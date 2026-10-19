import base64
import io
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy import ai
from scrcrappy.mcp import ToolError
from scrcrappy.video import LatestFrame


def png(w, h):
    buf = io.BytesIO()
    pygame.image.save(pygame.Surface((w, h)), buf, "x.png")
    return base64.b64encode(buf.getvalue()).decode()


class FakeSession:
    orientation = 1

    def __init__(self, replies):
        self.replies, self.sent, self.touches = replies, [], []

    def request(self, obj, done=None, failed=None):
        self.sent.append(obj)
        reply = self.replies.get(obj["cmd"], {"ok": True})
        if "error" in reply:
            failed and failed(reply["error"])
        elif done:
            done(reply)

    def touch(self, *events):
        self.touches.extend(events)


class FakePointer:
    def __init__(self):
        self.calls = []

    def wait_idle(self, timeout=5.0):
        return True

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


def frames(w=750, h=1334):
    f = LatestFrame()
    f.put((bytes(w * h * 3), (w, h), w * 3))
    return f


def tool(control, name):
    return next(t for t in control.tools() if t.name == name)


SCREEN = {"ok": True, "orientation": 1, "touch_ready": True}


def test_agent_tool_error_does_not_hang():
    control = ai.AiControl(frames(), session=FakeSession({"clipboard_get": {"error": "clipboard timeout"}}))
    t0 = time.monotonic()
    with pytest.raises(ToolError, match="Allow Paste"):
        tool(control, "clipboard").run({})
    assert time.monotonic() - t0 < 1


def test_agent_tap_maps_percent_and_marks_a_ring():
    s = FakeSession({"screen": SCREEN})
    control = ai.AiControl(frames(), session=s)
    tool(control, "tap").run({"x": 50, "y": 25})
    assert [e[:2] for e in s.touches] == [(ai.FINGER, "down"), (ai.FINGER, "up")]
    assert s.touches[0][2:] == pytest.approx((0.5, 0.25))
    assert control.rings and control.rings[-1][:2] == (50, 25)


def test_agent_screenshot_returns_image_and_metadata():
    control = ai.AiControl(frames(), session=FakeSession({"screen": {**SCREEN, "orientation": 3},
                                                         "screenshot": {"ok": True, "png": png(750, 1334)}}))
    image, meta = tool(control, "screenshot").run({})
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    assert '"width": 1334' in meta["text"] and "landscape-right" in meta["text"]


def test_agent_typing_keys_or_paste():
    s = FakeSession({})
    control = ai.AiControl(frames(), session=s)
    assert "keys" in tool(control, "type_text").run({"text": "ok"})[0]["text"]
    assert [m["cmd"] for m in s.sent] == ["key", "key"]
    assert "paste" in tool(control, "type_text").run({"text": "più"})[0]["text"]
    assert s.sent[-1] == {"cmd": "text", "text": "più"}


def test_out_of_range_coordinates_are_a_tool_error():
    control = ai.AiControl(frames(), session=FakeSession({"screen": SCREEN}))
    with pytest.raises(ToolError, match="0-100"):
        tool(control, "tap").run({"x": 120, "y": 5})


def test_ble_tap_moves_pointer_then_clicks():
    p = FakePointer()
    control = ai.AiControl(frames(), pointer=lambda: p)
    tool(control, "tap").run({"x": 50, "y": 25})
    assert p.calls[0] == ("move_to", 375.0, 333.5)
    assert ("button", True) in p.calls and p.calls[-1] == ("button", False)


def test_ble_screenshot_is_the_video_frame():
    control = ai.AiControl(frames(1334, 750), pointer=lambda: FakePointer())
    _, meta = tool(control, "screenshot").run({})
    assert '"width": 1334' in meta["text"] and '"orientation": "landscape"' in meta["text"]
    assert "clipboard" not in [t.name for t in control.tools()]  # agent only


def test_no_input_offers_only_screenshot():
    assert [t.name for t in ai.AiControl(frames()).tools()] == ["screenshot"]


def test_led_colour():
    control = ai.AiControl(frames())
    assert control.led(now=100) is None  # AI control off
    control.server = type("S", (), {"busy": False, "last_request": 0.0})()
    assert control.led(now=100) == ai.GREEN
    control.server.last_request = 80
    assert control.led(now=100) == ai.YELLOW  # a request within the last 30 s
    control.server.busy = True
    assert control.led(now=100) == ai.RED


def test_lock_released_when_tool_raises():
    from scrcrappy.mcp import McpServer
    control = ai.AiControl(frames(), session=FakeSession({"screen": SCREEN}))
    server = McpServer("t", control.tools, port=0)
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "tap", "arguments": {"x": 500, "y": 5}}})
    assert reply["result"]["isError"] and not server.busy


def test_enable_creates_token_and_reports_busy_port(monkeypatch):
    import socket
    from scrcrappy.config import Config
    cfg = Config()
    control = ai.AiControl(frames())
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    monkeypatch.setattr(ai, "PORT", taken.getsockname()[1])
    control.enable(cfg)
    assert len(cfg.mcp_token) >= 20 and control.server is None and "in use" in control.error
    taken.close()
    control.enable(cfg)
    assert control.server and control.error is None
    assert cfg.mcp_token in control.command(cfg)
    control.disable()
    assert control.server is None
