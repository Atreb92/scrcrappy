import numpy as np
import pygame
import pytest

from scrcrappy.app import Controller
from scrcrappy.calibrate import find_cursor
from scrcrappy.geometry import to_frame
from scrcrappy.keyqueue import KeyQueue

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
    return Controller(FakePointer(), keys=KeyQueue(lambda mods, keys: sent.append((mods, list(keys))))), sent


def drain(c):
    while c.keys.drain():
        pass


def key(c, usage, down=True):
    c.handle(ev(pygame.KEYDOWN if down else pygame.KEYUP, scancode=usage), RECT, FRAME)
    drain(c)


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
    drain(c)
    assert sent[-1] == (0, [])


def test_unknown_scancode_ignored():
    c, sent = keyboard()
    key(c, 0)
    assert sent == []


def test_ctrl_shift_v_pastes_clipboard(monkeypatch):
    monkeypatch.setattr(pygame.scrap, "get_text", lambda: "hi")
    c, sent = keyboard()
    for usage in (0xE0, 0xE1, 0x19):  # ctrl, shift, v
        key(c, usage)
    assert not any(0x19 in keys for _, keys in sent)  # V itself never reaches the phone
    assert sent[-5:] == [(0, []), (0, [0x0B]), (0, []), (0, [0x0C]), (0, [])]  # modifiers released, then "hi"


def test_paste_returns_skipped_count(monkeypatch):
    monkeypatch.setattr(pygame.scrap, "get_text", lambda: "aè")
    c, sent = keyboard()
    assert c.paste() == 1


def test_first_click_on_unfocused_pill_is_delivered(monkeypatch):
    # SDL drops the click that focuses a window unless this hint is set: the pill needed 2 clicks
    import importlib
    import os
    import scrcrappy.app
    monkeypatch.delenv("SDL_MOUSE_FOCUS_CLICKTHROUGH", raising=False)
    importlib.reload(scrcrappy.app)
    assert os.environ["SDL_MOUSE_FOCUS_CLICKTHROUGH"] == "1"


def test_failed_config_save_warns_instead_of_crashing(capsys):
    from scrcrappy.app import save_or_warn
    from scrcrappy.config import Config

    def broken(cfg):
        raise OSError("read-only file system")

    save_or_warn(broken, Config())
    assert "could not save settings" in capsys.readouterr().err


def test_run_survives_failing_settings_save(capsys):
    # toggling a toolbar setting saves at once; a broken save must not end the session
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module
    from scrcrappy.toolbar import Pill
    from scrcrappy.video import LatestFrame

    def broken(cfg):
        raise OSError("read-only file system")

    orig_init = Pill.__init__

    def init(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.actions["pinned"](False)  # as if the user clicked the chevron right away

    Pill.__init__ = init
    try:
        t0 = time.time()
        app_module.run(LatestFrame(), alive=lambda: time.time() - t0 < 0.3, save=broken)
    finally:
        Pill.__init__ = orig_init
    assert "could not save settings" in capsys.readouterr().err
