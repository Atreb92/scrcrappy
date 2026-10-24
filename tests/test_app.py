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


def test_first_click_on_unfocused_window_is_delivered(monkeypatch):
    # SDL drops the click that focuses a window unless this hint is set: the toolbar needed 2 clicks
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
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame

    def broken(cfg):
        raise OSError("read-only file system")

    bars, orig_bar, orig_settings = [], Bar.__init__, app_module.Settings.__init__

    def bar_init(self, *a, **kw):
        orig_bar(self, *a, **kw)
        bars.append(self)

    def settings_init(self, *a, **kw):
        orig_settings(self, *a, **kw)
        self._click("natural")  # as if the switch was clicked right away: saves

    app_module.Bar.__init__, app_module.Settings.__init__ = bar_init, settings_init
    try:
        t0, opened = time.time(), []

        def alive():
            if bars and not opened:
                opened.append(1)
                bars[0].actions["settings"]()
            return time.time() - t0 < 0.3

        app_module.run(LatestFrame(), alive=alive, save=broken)
    finally:
        app_module.Bar.__init__, app_module.Settings.__init__ = orig_bar, orig_settings
    assert "could not save settings" in capsys.readouterr().err


def test_calibrator_reports_current_value_and_saves_a_new_table(monkeypatch, tmp_path):
    from scrcrappy import calibrate
    monkeypatch.setenv("HOME", str(tmp_path))
    c = calibrate.Calibrator("abc", send=lambda *a: None, frames=None)
    assert c.value() == pytest.approx(1.66, abs=0.01)  # default table, medium move (12 counts)
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, cancel=None: {1: 1.0, 12: 2.5, 24: 3.0})
    c.run()
    assert c.value() == pytest.approx(2.5)
    assert calibrate.load("abc")[12.0] == 2.5


@pytest.mark.parametrize("failure", [None, OSError("disk full"), "cancelled"])
def test_calibrate_from_settings_stops_the_pointer_and_rebuilds_it(monkeypatch, capsys, failure):  # also when it blows up
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module, calibrate
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame

    pointers, runs, bars = [], [], []

    def make_pointer(size):
        pointers.append(FakePointer())
        return pointers[-1]

    class FakeCalibrator:
        def value(self):
            return 1.86

        def run(self):
            runs.append(len(pointers))  # pointers built so far when the measurement runs
            if failure == "cancelled":
                raise calibrate.Cancelled()
            if failure:
                raise failure

    orig_bar, orig_settings = Bar.__init__, app_module.Settings.__init__

    def bar_init(self, *a, **kw):
        orig_bar(self, *a, **kw)
        bars.append(self)

    def settings_init(self, *a, **kw):
        orig_settings(self, *a, **kw)
        self._click("calibrate")

    monkeypatch.setattr(Bar, "__init__", bar_init)
    monkeypatch.setattr(app_module.Settings, "__init__", settings_init)
    frames, t0, loops = LatestFrame(), time.time(), []

    def alive():
        loops.append(1)
        if len(loops) == 3:
            bars[0].actions["settings"]()  # gear clicked once the pointer exists
        if len(loops) <= 3:  # a still screen: no new frame after this, the pointer must come back anyway
            frames.put((bytes(30 * 60 * 3), (30, 60), 90))
        return time.time() - t0 < 1.0

    app_module.run(frames, alive, make_pointer=make_pointer, calibrator=FakeCalibrator(), save=lambda c: None)
    assert runs == [1]  # measured once, with the old pointer stopped and no new one yet
    assert ("stop",) in pointers[0].calls
    assert len(pointers) == 2  # rebuilt afterwards, with the new table
    assert ("calibration failed" in capsys.readouterr().err) == isinstance(failure, OSError)  # a cancel is no failure


def test_bar_actions_do_nothing_while_calibrating(monkeypatch):
    import os
    import threading
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame

    bars, gate, pressed = [], threading.Event(), []

    class SlowCalibrator:
        def value(self):
            return 1.86

        def run(self):
            gate.wait(2)

    orig_bar, orig_settings = Bar.__init__, app_module.Settings.__init__

    def bar_init(self, *a, **kw):
        orig_bar(self, *a, **kw)
        bars.append(self)

    def settings_init(self, *a, **kw):
        orig_settings(self, *a, **kw)
        self._click("calibrate")

    monkeypatch.setattr(Bar, "__init__", bar_init)
    monkeypatch.setattr(app_module.Settings, "__init__", settings_init)
    frames, t0, loops = LatestFrame(), time.time(), []

    def alive():
        loops.append(1)
        if len(loops) == 3:
            bars[0].actions["settings"]()
        if len(loops) == 6:  # calibrating: the pointer controller is gone
            for name in ("copy", "paste", "home", "switcher", "lock"):
                bars[0].actions[name]()
                pressed.append(name)
            gate.set()
        if len(loops) <= 3:
            frames.put((bytes(30 * 60 * 3), (30, 60), 90))
        return time.time() - t0 < 1.0

    app_module.run(frames, alive, make_pointer=lambda size: FakePointer(), calibrator=SlowCalibrator(), save=lambda c: None)
    assert pressed == ["copy", "paste", "home", "switcher", "lock"]


def test_mcp_flag_is_never_saved(monkeypatch):
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import ai
    from scrcrappy import app as app_module
    from scrcrappy.config import Config
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame
    monkeypatch.setattr(ai, "PORT", 0)
    saved, bars, clicked = [], [], []
    orig, orig_settings = Bar.__init__, app_module.Settings.__init__

    def bar_init(self, *a, **kw):
        orig(self, *a, **kw)
        bars.append(self)

    def settings_init(self, *a, **kw):
        orig_settings(self, *a, **kw)
        self._click("natural")  # any other setting change saves the config

    monkeypatch.setattr(Bar, "__init__", bar_init)
    monkeypatch.setattr(app_module.Settings, "__init__", settings_init)
    t0 = time.time()

    def alive():
        if bars and time.time() - t0 > 0.2 and not clicked:
            clicked.append(1)
            bars[0].actions["settings"]()
        return time.time() - t0 < 0.5

    app_module.run(LatestFrame(), alive, cfg=Config(), mcp=True, save=lambda c: saved.append(c.ai_control))
    assert clicked and len(saved) >= 2 and not any(saved)


def test_screenshot_button_without_the_agent_saves_the_video_frame(tmp_path):
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module
    from scrcrappy.config import Config
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame
    bars, orig = [], Bar.__init__

    def bar_init(self, *a, **kw):
        orig(self, *a, **kw)
        bars.append(self)

    Bar.__init__ = bar_init
    try:
        frames, t0, loops = LatestFrame(), time.time(), []

        def alive():
            loops.append(1)
            frames.put((bytes(30 * 60 * 3), (30, 60), 90))
            if len(loops) == 3:
                bars[0].actions["screenshot"]()
            return time.time() - t0 < 0.5

        shown = []
        app_module.run(frames, alive, cfg=Config(screenshots=str(tmp_path)), save=lambda c: None)
        shown.append(bars[0].toast_text)
    finally:
        Bar.__init__ = orig
    [saved] = list(tmp_path.glob("scrcrappy-*.png"))
    assert pygame.image.load(str(saved)).get_size() == (30, 60)  # the frame as mirrored
    assert shown[0].startswith("Screenshot saved: ") and shown[0].endswith(saved.name)


def test_screenshot_button_before_any_video_says_so(tmp_path):
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module
    from scrcrappy.config import Config
    from scrcrappy.toolbar import Bar
    from scrcrappy.video import LatestFrame
    bars, orig, shown = [], Bar.__init__, []

    def bar_init(self, *a, **kw):
        orig(self, *a, **kw)
        bars.append(self)

    Bar.__init__ = bar_init
    try:
        t0, clicked = time.time(), []

        def alive():
            if bars and not clicked:
                clicked.append(1)
                bars[0].actions["screenshot"]()
                shown.append(bars[0].toast_text)
            return time.time() - t0 < 0.3

        app_module.run(LatestFrame(), alive, cfg=Config(screenshots=str(tmp_path)), save=lambda c: None)
    finally:
        Bar.__init__ = orig
    assert shown == ["No video yet: no screenshot"] and not list(tmp_path.iterdir())


def test_window_takes_the_phones_aspect_when_the_first_frame_arrives():
    import os
    import time
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    from scrcrappy import app as app_module
    from scrcrappy.toolbar import BAR_H, Bar
    from scrcrappy.video import LatestFrame
    bars, orig = [], Bar.__init__

    def bar_init(self, *a, **kw):
        orig(self, *a, **kw)
        bars.append(self)

    Bar.__init__ = bar_init
    try:
        frames, t0, loops = LatestFrame(), time.time(), []

        def alive():
            loops.append(1)
            if len(loops) == 2:
                frames.put((bytes(40 * 20 * 3), (40, 20), 120))  # a landscape frame
            if len(loops) == 6:
                loops.append(bars[0].main.size)
            return time.time() - t0 < 0.4

        app_module.run(frames, alive, save=lambda c: None)
    finally:
        Bar.__init__ = orig
    size = next(x for x in loops if isinstance(x, tuple))
    assert size == (667, round(667 * 20 / 40) + BAR_H)  # long side kept (667), landscape 2:1 image area above the bar


def test_window_enter_is_paused_while_the_ai_acts():
    from scrcrappy.app import paused
    assert paused(pygame.event.Event(pygame.WINDOWENTER), True)  # else the pointer homes mid-press
    assert not paused(pygame.event.Event(pygame.WINDOWENTER), False)
