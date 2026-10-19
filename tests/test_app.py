import numpy as np
import pygame
import pytest

from scrcrappy.app import Controller
from scrcrappy.calibrate import find_cursor
from scrcrappy.geometry import to_frame

RECT, FRAME = (100, 0, 375, 667), (750, 1334)  # frame drawn at half size, letterbox left of x=100


class FakePointer:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


def ev(kind, **kw):
    return pygame.event.Event(kind, **kw)


def test_to_frame_scales_and_offsets():
    assert to_frame((100 + 187, 333), RECT, FRAME) == pytest.approx((374, 666), abs=1)


def test_motion_moves_pointer():
    p = FakePointer()
    Controller(p).handle(ev(pygame.MOUSEMOTION, pos=(200, 100)), RECT, FRAME)
    assert p.calls == [("move_to", 200.0, pytest.approx(200, abs=1))]


def test_click_goes_to_point_then_presses_and_releases():
    p, c = FakePointer(), None
    c = Controller(p)
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(200, 100), button=1), RECT, FRAME)
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(200, 100), button=1), RECT, FRAME)
    assert [k for k, *_ in p.calls] == ["move_to", "button", "button"]
    assert p.calls[1] == ("button", True) and p.calls[2] == ("button", False)


def test_click_in_letterbox_does_nothing():
    p = FakePointer()
    c = Controller(p)
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(50, 100), button=1), RECT, FRAME)
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(50, 100), button=1), RECT, FRAME)
    assert p.calls == []


def test_leaving_window_mid_drag_releases():
    p = FakePointer()
    c = Controller(p)
    c.handle(ev(pygame.MOUSEBUTTONDOWN, pos=(200, 100), button=1), RECT, FRAME)
    c.handle(ev(pygame.WINDOWLEAVE), RECT, FRAME)
    assert p.calls[-1] == ("button", False)
    c.handle(ev(pygame.MOUSEBUTTONUP, pos=(200, 100), button=1), RECT, FRAME)
    assert p.calls.count(("button", False)) == 1


def test_entering_window_rehomes_unless_dragging():
    p = FakePointer()
    c = Controller(p)
    c.handle(ev(pygame.WINDOWENTER), RECT, FRAME)
    assert p.calls == [("home",)]


def test_find_cursor_on_plain_screen():
    img = np.full((1334, 750, 3), 242, np.uint8)
    yy, xx = np.mgrid[:1334, :750]
    img[(xx - 300) ** 2 + (yy - 500) ** 2 <= 18 ** 2] = (150, 149, 154)
    assert find_cursor(img) == pytest.approx((300, 500), abs=3)
    assert find_cursor(np.full((1334, 750, 3), 242, np.uint8)) is None


@pytest.mark.parametrize("natural, flipped, expected", [
    (False, False, 1), (True, False, -1),  # wheel up, OS not flipping
    (False, True, 1), (True, True, -1),    # OS already flipped (macOS natural scrolling): same result
])
def test_scroll_direction(natural, flipped, expected):
    p = FakePointer()
    Controller(p, natural_scroll=natural).handle(
        ev(pygame.MOUSEWHEEL, y=-1 if flipped else 1, flipped=flipped), RECT, FRAME)
    assert p.calls == [("wheel", expected)]


def keyboard():
    sent = []
    return Controller(FakePointer(), keys=lambda mods, keys: sent.append((mods, list(keys)))), sent


def key(c, usage, down=True):
    c.handle(ev(pygame.KEYDOWN if down else pygame.KEYUP, scancode=usage), RECT, FRAME)


def test_key_press_and_release():
    c, sent = keyboard()
    key(c, 0x04)  # A
    key(c, 0x04, down=False)
    assert sent == [(0, [0x04]), (0, [])]


def test_shift_is_a_modifier_bit_not_a_key():
    c, sent = keyboard()
    key(c, 0xE1)  # left shift
    key(c, 0x04)
    key(c, 0x04, down=False)
    key(c, 0xE1, down=False)
    assert sent == [(0x02, []), (0x02, [0x04]), (0x02, []), (0, [])]


def test_at_most_six_keys_reported():
    c, sent = keyboard()
    for usage in range(0x04, 0x0B):  # 7 keys
        key(c, usage)
    assert sent[-1] == (0, [0x04, 0x05, 0x06, 0x07, 0x08, 0x09])
    key(c, 0x04, down=False)
    assert sent[-1] == (0, [0x05, 0x06, 0x07, 0x08, 0x09, 0x0A])  # the 7th takes the freed slot


def test_focus_lost_releases_held_keys():
    c, sent = keyboard()
    key(c, 0xE0)  # ctrl
    key(c, 0x06)  # c
    c.handle(ev(pygame.WINDOWFOCUSLOST), RECT, FRAME)
    assert sent[-1] == (0, [])


def test_unknown_scancode_ignored():
    c, sent = keyboard()
    key(c, 0)
    assert sent == []
