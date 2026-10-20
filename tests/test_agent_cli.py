import base64
import io
import json
import socket
import threading

import pygame
import pytest

from scrcrappy import agent_cli
from scrcrappy.agent_client import Agent, encode_frame, read_frame


APPS = [{"id": "com.apple.Preferences", "name": "Settings", "pid": 412}, {"id": "com.apple.mobilenotes", "name": "Notes"},
        {"id": "com.apple.mobilesafari", "name": "Safari"}, {"id": "com.apple.mobileslideshow", "name": "Photos"},
        {"id": "com.apple.Passbook", "name": "Wallet"}, {"id": "com.apple.mobilephone", "name": "Phone"},
        {"id": "com.apple.MobileSMS", "name": "Messages"}, {"id": "com.apple.mobilemail", "name": "Mail"},
        {"id": "com.apple.reminders", "name": "Reminders"}, {"id": "com.apple.mobiletimer", "name": "Clock"}]


def png(w, h):
    buf = io.BytesIO()
    pygame.image.save(pygame.Surface((w, h)), buf, "x.png")
    return base64.b64encode(buf.getvalue()).decode()


class FakePhone:
    """Speaks the agent protocol on a socketpair; records every request."""

    def __init__(self, monkeypatch, orientation=1, touch_ready=True, clipboard=None, open_error=None, old_agent=False):
        ours, phone = socket.socketpair()
        self.seen, self.orientation, self.touch_ready, self.clipboard = [], orientation, touch_ready, clipboard
        self.open_error, self.old_agent = open_error, old_agent
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
            elif cmd in ("apps", "open") and self.old_agent:
                reply = {"error": "unknown command"}
            elif cmd == "apps":
                reply["apps"] = APPS
            elif cmd == "open" and self.open_error:
                reply = {"error": self.open_error}
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


def test_apps_lists_name_id_and_whether_it_runs(monkeypatch, capsys):
    FakePhone(monkeypatch)
    code, out = run(["--apps"], capsys)
    assert code == 0 and out["apps"][0] == {"id": "com.apple.Preferences", "name": "Settings", "running": True}
    assert out["apps"][1] == {"id": "com.apple.mobilenotes", "name": "Notes", "running": False}


def test_open_takes_a_name_or_a_bundle_id(monkeypatch, capsys):
    phone = FakePhone(monkeypatch)
    assert run(["--open", "notes"], capsys) == (0, {"ok": True, "id": "com.apple.mobilenotes", "name": "Notes"})
    phone = FakePhone(monkeypatch)
    assert run(["--open", "com.apple.Preferences"], capsys)[1]["name"] == "Settings"
    assert [m for m in phone.seen if m["cmd"] == "open"] == [{"cmd": "open", "id": "com.apple.Preferences"}]


def test_open_unknown_or_ambiguous_app_fails_before_opening_anything(monkeypatch, capsys):
    for query, words in (("Calendar", "no app"), ("m", "more than one")):  # "m": Messages, Mail, Safari...
        phone = FakePhone(monkeypatch)
        code, out = run(["--open", query], capsys)
        assert code == 1 and words in out["error"]
        assert not [m for m in phone.seen if m["cmd"] == "open"]


def test_locked_phone_and_old_agent_have_readable_errors(monkeypatch, capsys):
    FakePhone(monkeypatch, open_error="locked")
    code, out = run(["--open", "Settings"], capsys)
    assert code == 1 and "unlock" in out["error"]
    FakePhone(monkeypatch, old_agent=True)
    code, out = run(["--apps"], capsys)
    assert code == 1 and "update" in out["error"] and "0.3.0" in out["error"]


def test_find_app_prefers_exact_matches():
    apps = [{"id": "a.mail", "name": "Mail"}, {"id": "a.mailbox", "name": "Mailbox"}]
    assert agent_cli.find_app(apps, "mail")["id"] == "a.mail"  # exact name beats the substring match
    assert agent_cli.find_app(apps, "a.mailbox")["name"] == "Mailbox"
