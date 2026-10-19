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
