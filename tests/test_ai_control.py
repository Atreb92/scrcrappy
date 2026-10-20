import base64
import io
import json
import os
import time

os.environ["SDL_VIDEODRIVER"] = "dummy"

import numpy as np
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
    assert [r[:2] for r in control.current_rings(time.monotonic())] == [(50, 25)]


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


@pytest.mark.parametrize("ms", [-5, 0, 1e7, "soon"])
def test_bad_durations_are_tool_errors_and_touch_nothing(ms):
    s = FakeSession({"screen": SCREEN})
    control = ai.AiControl(frames(), session=s)
    with pytest.raises(ToolError, match="ms"):
        tool(control, "long_press").run({"x": 50, "y": 50, "ms": ms})
    assert s.touches == []


def test_finger_lifted_when_a_touch_is_interrupted():
    s = FakeSession({"screen": SCREEN})
    calls = []
    s.touch = lambda *e: calls.append(e) if len(calls) == 0 else (_ for _ in ()).throw(OSError("gone"))
    control = ai.AiControl(frames(), session=s)
    with pytest.raises(OSError):
        tool(control, "tap").run({"x": 50, "y": 50})
    s.touch = lambda *e: calls.append(e)  # connection back: the cleanup "up" goes out
    control.cleanup()
    assert calls[-1][0][:2] == (ai.FINGER, "up")


def test_unexpected_tool_exception_is_an_error_result_and_unlocks():
    from scrcrappy.mcp import McpServer, Tool

    def boom(args):
        raise KeyError("png")

    server = McpServer("t", lambda: [Tool("boom", "", {"type": "object"}, boom)], port=0)
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "boom"}})
    assert reply["result"]["isError"] and "png" in reply["result"]["content"][0]["text"] and not server.busy
    reply = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": "nonsense"})
    assert "error" in reply or reply["result"]["isError"]


def test_ble_type_text_waits_until_typed():
    class Keys:
        def __init__(self):
            self.pending = ["k"] * 3

        def type_text(self, text):
            return 0

        def wait_idle(self, timeout=10.0):
            self.pending.clear()
            return True

    keys = Keys()
    control = ai.AiControl(frames(), pointer=lambda: FakePointer(), keys=keys)
    tool(control, "type_text").run({"text": "abc"})
    assert keys.pending == []


def test_stalled_pointer_is_a_tool_error():
    p = FakePointer()
    p.wait_idle = lambda timeout=5.0: False  # e.g. calibration stopped the pointer
    control = ai.AiControl(frames(), pointer=lambda: p)
    with pytest.raises(ToolError, match="pointer"):
        tool(control, "tap").run({"x": 50, "y": 50})


def test_rings_keep_recent_and_future_ones():
    control = ai.AiControl(frames())
    control.add_ring(10, 10, at=0.0)
    control.add_ring(20, 20, at=9.9)
    control.add_ring(30, 30, at=12.0)  # a swipe's end ring, shown later
    assert [r[:2] for r in control.current_rings(now=10.0)] == [(20, 20)]
    assert [r[:2] for r in control.current_rings(now=12.1)] == [(30, 30)]


def test_input_paused_per_event_while_locked():
    from scrcrappy.app import paused
    assert paused(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)), True)  # pill clicks too
    assert paused(pygame.event.Event(pygame.KEYDOWN, scancode=4), True)
    assert not paused(pygame.event.Event(pygame.WINDOWFOCUSLOST), True)
    assert not paused(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)), False)


def frames_with_cursor(cx, cy, w=750, h=1334):
    """A white screen with the AssistiveTouch disk (solid ~150 grey) centred at (cx, cy)."""
    img = np.full((h, w, 3), 255, np.uint8)
    yy, xx = np.ogrid[:h, :w]
    img[(xx - cx) ** 2 + (yy - cy) ** 2 <= 18 ** 2] = 150
    f = LatestFrame()
    f.put((img.tobytes(), (w, h), w * 3))
    return f


@pytest.fixture
def no_settle(monkeypatch):
    monkeypatch.setattr(ai, "SETTLE_S", 0)


def test_check_pointer_reports_the_error_in_pixels(no_settle):
    p = FakePointer()
    control = ai.AiControl(frames_with_cursor(375, 700), pointer=lambda: p)  # target is (375, 667)
    [block] = tool(control, "check_pointer").run({"x": 50, "y": 50})
    assert p.calls[0] == ("move_to", 375.0, 667.0) and not any(c[0] == "button" for c in p.calls)
    out = json.loads(block["text"])
    assert out["error_px"] == pytest.approx(33, abs=1)
    assert out["cursor_px"] == pytest.approx([375, 700], abs=1) and out["target_px"] == [375, 667]


def test_check_pointer_without_a_visible_cursor_says_how_to_fix_it(no_settle):
    control = ai.AiControl(frames(), pointer=lambda: FakePointer())  # all black
    with pytest.raises(ToolError, match="plain, light screen"):
        tool(control, "check_pointer").run({"x": 50, "y": 50})


def test_pointer_tools_only_with_a_pointer():
    assert "check_pointer" not in [t.name for t in ai.AiControl(frames(), session=FakeSession({})).tools()]
    assert "calibrate" not in [t.name for t in ai.AiControl(frames(), pointer=lambda: FakePointer()).tools()]


def test_calibrate_runs_the_app_routine_and_waits_for_the_pointer(no_settle):
    ready = iter([None, None, FakePointer()])  # the app rebuilds the pointer on the next frame
    control = ai.AiControl(frames(), pointer=lambda: next(ready, FakePointer()), calibrate=lambda: "px per count: 1.66")
    [block] = tool(control, "calibrate").run({})
    assert "1.66" in block["text"] and next(ready, None) is None


def test_calibrate_failure_is_a_tool_error():
    def fail():
        raise RuntimeError("can't see the cursor: open a plain light screen")

    control = ai.AiControl(frames(), pointer=lambda: FakePointer(), calibrate=fail)
    with pytest.raises(ToolError, match="plain light screen"):
        tool(control, "calibrate").run({})
