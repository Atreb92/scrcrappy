import base64
import io
import json
import socket
import threading

import pygame
import pytest

from scrcrappy import agent_cli
from scrcrappy.agent_client import Agent, encode_frame, read_frame


def png(w, h):
    buf = io.BytesIO()
    pygame.image.save(pygame.Surface((w, h)), buf, "x.png")
    return base64.b64encode(buf.getvalue()).decode()


class FakePhone:
    """Speaks the agent protocol on a socketpair; records every request."""

    def __init__(self, monkeypatch, orientation=1, touch_ready=True, clipboard=None):
        ours, phone = socket.socketpair()
        self.seen, self.orientation, self.touch_ready, self.clipboard = [], orientation, touch_ready, clipboard
        phone.sendall(encode_frame({"hello": 1, "nonce": "00" * 16, "addr": "127.0.0.1"}))
        threading.Thread(target=self.serve, args=(phone,), daemon=True).start()
        monkeypatch.setattr(agent_cli, "connect", lambda: Agent(ours))

    def serve(self, phone):
        while True:
            try:
                msg = read_frame(phone.recv)
            except (ConnectionError, OSError):
                return
            self.seen.append(msg)
            cmd = msg["cmd"]
            if cmd == "touch":
                continue
            reply = {"ok": True}
            if cmd == "screen":
                reply.update(width=375, height=667, scale=2, orientation=self.orientation,
                             touch_ready=self.touch_ready, fingers_down=0)
            elif cmd == "screenshot":
                reply["png"] = png(750, 1334)
            elif cmd == "clipboard_get":
                reply = {"ok": True, "text": self.clipboard} if self.clipboard is not None else {"error": "clipboard timeout"}
            phone.sendall(encode_frame(reply))

    def touches(self):
        return [e for m in self.seen if m["cmd"] == "touch" for e in m["events"]]


def run(argv, capsys):
    code = agent_cli.main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)  # stdout is exactly one JSON object


def test_tap_sends_down_then_up_in_portrait_fractions(monkeypatch, capsys):
    phone = FakePhone(monkeypatch)
    assert run(["--tap", "50,25"], capsys) == (0, {"ok": True})
    (down, up) = phone.touches()
    assert (down["phase"], down["x"], down["y"]) == ("down", 0.5, 0.25)
    assert (up["phase"], up["finger"]) == ("up", 1)


def test_landscape_tap_lands_where_the_upright_screenshot_shows_it(monkeypatch, capsys):
    phone = FakePhone(monkeypatch, orientation=3)
    run(["--tap", "0,0"], capsys)
    down = phone.touches()[0]
    assert (down["x"], down["y"]) == pytest.approx((1, 0))


def test_screenshot_writes_png_and_reports_size(monkeypatch, capsys, tmp_path):
    FakePhone(monkeypatch, orientation=4)
    code, out = run(["--screenshot", str(tmp_path / "s.png")], capsys)
    assert code == 0 and out == {"ok": True, "path": str(tmp_path / "s.png"), "width": 1334, "height": 750,
                                 "orientation": "landscape-left"}
    assert pygame.image.load(tmp_path / "s.png").get_size() == (1334, 750)


def test_touch_not_ready_is_an_error(monkeypatch, capsys):
    phone = FakePhone(monkeypatch, touch_ready=False)
    code, out = run(["--tap", "50,50"], capsys)
    assert code == 1 and "touch the phone's screen once" in out["error"]
    assert phone.touches() == []


def test_type_ascii_uses_keys_unicode_uses_text(monkeypatch, capsys):
    phone = FakePhone(monkeypatch)
    assert run(["--type", "Hi"], capsys) == (0, {"ok": True, "typed_with": "keys"})
    assert [m for m in phone.seen if m["cmd"] == "key"] == [
        {"cmd": "key", "usage": 0x0B, "modifiers": 0x02}, {"cmd": "key", "usage": 0x0C, "modifiers": 0}]
    phone = FakePhone(monkeypatch)
    assert run(["--type", "caffè"], capsys) == (0, {"ok": True, "typed_with": "paste"})
    assert {"cmd": "text", "text": "caffè"} in phone.seen


def test_clipboard_prints_text_or_explains_the_prompt(monkeypatch, capsys):
    FakePhone(monkeypatch, clipboard="hello")
    assert run(["--clipboard"], capsys) == (0, {"ok": True, "text": "hello"})
    FakePhone(monkeypatch)
    code, out = run(["--clipboard"], capsys)
    assert code == 1 and "Allow Paste" in out["error"]


def test_bad_coordinates_exit_1_with_json(monkeypatch, capsys):
    phone = FakePhone(monkeypatch)
    code, out = run(["--swipe", "10,120,10,20"], capsys)
    assert code == 1 and "0-100" in out["error"] and phone.touches() == []


def test_long_press_and_swipe_durations(monkeypatch, capsys):
    phone = FakePhone(monkeypatch)
    assert run(["--swipe", "50,80,50,20,50"], capsys)[0] == 0
    events = phone.touches()
    assert events[0]["phase"] == "down" and events[-1]["phase"] == "up"
    assert events[-1]["y"] == pytest.approx(0.2)


def test_empty_screenshot_path_is_an_error(monkeypatch, capsys):
    phone = FakePhone(monkeypatch, clipboard="secret")
    code, out = run(["--screenshot", ""], capsys)
    assert code == 1 and "path" in out["error"]
    assert not any(m["cmd"] == "clipboard_get" for m in phone.seen)


def keys(phone):
    return [(m["page"], m["usage"]) for m in phone.seen if m["cmd"] == "key"]


def test_home_switcher_and_lock_press_the_phones_buttons(monkeypatch, capsys):
    monkeypatch.setattr(agent_cli.agent_mod, "SWITCHER_GAP", 0)
    phone = FakePhone(monkeypatch)
    assert run(["--home"], capsys) == (0, {"ok": True})
    assert keys(phone) == [(0x0C, 0x40)]  # consumer page: Home
    phone = FakePhone(monkeypatch)
    assert run(["--switcher"], capsys) == (0, {"ok": True})
    assert keys(phone) == [(0x0C, 0x40), (0x0C, 0x40)]  # Home twice
    phone = FakePhone(monkeypatch)
    assert run(["--lock"], capsys) == (0, {"ok": True})
    assert keys(phone) == [(0x0C, 0x30)]


def test_one_action_per_call(monkeypatch):
    FakePhone(monkeypatch)
    with pytest.raises(SystemExit):
        agent_cli.main(["--home", "--lock"])
