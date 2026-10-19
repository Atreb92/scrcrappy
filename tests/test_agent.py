import socket

import pygame
import pytest

from scrcrappy import agent
from scrcrappy.agent_client import encode_frame, read_frame
from scrcrappy.geometry import rotation

RECT, PORTRAIT, LANDSCAPE = (100, 0, 375, 667), (750, 1334), (1334, 750)


class FakeSession:
    orientation = 1

    def __init__(self):
        self.calls = []

    def touch(self, *events):
        self.calls.append(("touch", *events))

    def request(self, obj, done=None):
        self.calls.append(("request", obj))

    def swipe(self, a, b):
        self.calls.append(("swipe", a, b))

    def pause(self, s):
        self.calls.append(("pause", s))


def ev(kind, **kw):
    return pygame.event.Event(kind, **kw)


def ctl(**kw):
    s = FakeSession()
    return agent.Controller(s, **kw), s.calls


def test_click_is_down_then_up_at_the_fraction():
    c, calls = ctl()
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(100 + 375 // 4, 667 // 2), button=1), RECT, PORTRAIT)
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(100 + 375 // 4, 667 // 2), button=1), RECT, PORTRAIT)
    (_, (f, phase, x, y)), (_, up) = calls
    assert (f, phase) == (1, "down") and (x, y) == pytest.approx((0.25, 0.5), abs=0.01)
    assert up[:2] == (1, "up")


def test_click_in_letterbox_does_nothing():
    c, calls = ctl()
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(50, 100), button=1), RECT, PORTRAIT)
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(50, 100), button=1), RECT, PORTRAIT)
    assert calls == []


def test_drag_out_of_frame_clamps_and_leaving_lifts():
    c, calls = ctl()
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(200, 100), button=1), RECT, PORTRAIT)
    c.moved = 0
    c.handle(ev(pygame.MOUSEMOTION, pos=(0, -50)), RECT, PORTRAIT)
    assert calls[-1][1][:2] == (1, "move") and calls[-1][1][2:] == pytest.approx((0, 0), abs=0.01)
    c.handle(ev(pygame.WINDOWLEAVE), RECT, PORTRAIT)
    assert calls[-1][1][:2] == (1, "up")
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(200, 100), button=1), RECT, PORTRAIT)
    assert len(calls) == 3  # no second up


def test_ctrl_drag_is_a_pinch_mirrored_through_the_centre():
    c, calls = ctl()
    c.handle(ev(pygame.KEYDOWN, scancode=0xE0), RECT, PORTRAIT)
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(100 + 375 // 4, 667 // 4), button=1), RECT, PORTRAIT)
    _, one, two = calls[-1]
    assert one[:2] == (1, "down") and two[:2] == (2, "down")
    assert two[2:] == pytest.approx((1 - one[2], 1 - one[3]))


def test_key_carries_held_modifiers():
    c, calls = ctl()
    for usage in (0xE3, 0x19):  # left cmd, v
        c.handle(ev(pygame.KEYDOWN, scancode=usage), RECT, PORTRAIT)
    assert calls == [("request", {"cmd": "key", "usage": 0x19, "modifiers": 0x08})]
    c.handle(ev(pygame.WINDOWFOCUSLOST), RECT, PORTRAIT)
    c.handle(ev(pygame.KEYDOWN, scancode=0x19), RECT, PORTRAIT)
    assert calls[-1][1]["modifiers"] == 0


def test_ctrl_shift_v_pastes_as_text(monkeypatch):
    monkeypatch.setattr(pygame.scrap, "get_text", lambda: "àè 😀")
    c, calls = ctl()
    for usage in (0xE0, 0xE1, 0x19):
        c.handle(ev(pygame.KEYDOWN, scancode=usage), RECT, PORTRAIT)
    assert calls == [("request", {"cmd": "text", "text": "àè 😀"})]


@pytest.mark.parametrize("natural, finger_dy", [(False, 1), (True, -1)])
def test_wheel_up_swipes_finger_down(monkeypatch, natural, finger_dy):
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (287, 333))
    c, calls = ctl(natural_scroll=natural)
    c.handle(ev(pygame.MOUSEWHEEL, x=0, y=1, flipped=False), RECT, PORTRAIT)
    _, a, b = calls[0]
    assert a[0] == pytest.approx(b[0]) and (b[1] - a[1]) * finger_dy == pytest.approx(agent.SWIPE, abs=0.01)


def test_app_switcher_is_two_home_presses():
    c, calls = ctl()
    c.switcher()
    home = ("request", {"cmd": "key", "page": 0x0C, "usage": 0x40})
    assert calls == [home, ("pause", 0.15), home]


def test_landscape_frame_uses_orientation():
    assert rotation(3, LANDSCAPE) == 270 and rotation(4, LANDSCAPE) == 90
    assert rotation(3, PORTRAIT) == 0  # stream hasn't turned yet
    assert rotation(1, PORTRAIT) == 0 and rotation(2, PORTRAIT) == 180


def test_session_requests_in_order_and_touches_need_no_reply():
    ours, phone = socket.socketpair()
    replies = []
    s = agent.Session(ours, post=lambda fn: fn())
    s.touch((1, "down", 0.5, 0.5))
    s.request({"cmd": "clipboard_get"}, replies.append)
    assert read_frame(phone.recv) == {"cmd": "touch", "events": [{"finger": 1, "phase": "down", "x": 0.5, "y": 0.5}]}
    assert read_frame(phone.recv) == {"cmd": "clipboard_get"}
    phone.sendall(encode_frame({"ok": True, "text": "hi"}))
    s.request({"cmd": "screen"}, s._screen)
    assert read_frame(phone.recv) == {"cmd": "screen"}
    phone.sendall(encode_frame({"ok": True, "orientation": 3, "touch_ready": True}))
    s.request({"cmd": "key", "usage": 4})  # replies are read in order: by now both callbacks have run
    read_frame(phone.recv)
    assert replies == [{"ok": True, "text": "hi"}] and s.orientation == 3


def test_session_reconnects_after_the_connection_drops():
    ours, phone = socket.socketpair()
    new_ours, new_phone = socket.socketpair()
    s = agent.Session(ours, post=lambda fn: fn(), reopen=lambda: new_ours)
    phone.close()  # e.g. qvh switched the phone's USB configuration
    s.request({"cmd": "key", "usage": 4})
    s.request({"cmd": "key", "usage": 5})
    assert read_frame(new_phone.recv) == {"cmd": "key", "usage": 5}
