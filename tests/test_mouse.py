import pytest

from scrcrappy.mouse import DEFAULT_GAIN, HOME_REPORTS, Gain, Pointer


class Phone:
    """Fake phone: applies the same gain model to received reports, clamps at screen edges."""

    def __init__(self, gain, size=(750, 1334)):
        self.gain, self.size, self.pos, self.sent = gain, size, [0.0, 0.0], []

    def __call__(self, dx, dy, buttons, wheel):
        self.sent.append((dx, dy, buttons, wheel))
        g = self.gain((dx * dx + dy * dy) ** 0.5)
        self.pos = [min(max(self.pos[0] + g * dx, 0), self.size[0] - 1), min(max(self.pos[1] + g * dy, 0), self.size[1] - 1)]


def run(p, limit=2000):
    for _ in range(limit):
        if not p.step():
            return
    raise AssertionError("pointer never settled")


def setup():
    gain = Gain(DEFAULT_GAIN)
    phone = Phone(gain)
    return Pointer(phone, gain, (750, 1334)), phone


def test_gain_interpolates_and_clamps():
    g = Gain({1: 0.4, 3: 0.6, 16: 1.7})
    assert g(2) == pytest.approx(0.5)
    assert g(0.5) == 0.4 and g(40) == 1.7


def test_reaches_target_within_a_pixel():
    p, phone = setup()
    p.move_to(512.3, 801.7)
    run(p)
    assert phone.pos == pytest.approx([512.3, 801.7], abs=1)
    assert all(abs(dx) <= 24 and abs(dy) <= 24 for dx, dy, *_ in phone.sent)


def test_only_latest_target_is_followed():
    p, phone = setup()
    for x in range(0, 300, 10):
        p.move_to(x, x)
    run(p)
    assert phone.pos == pytest.approx([290, 290], abs=1)


def test_click_waits_for_arrival_and_drag_holds_button():
    p, phone = setup()
    p.move_to(200, 0)
    p.button(True)
    p.move_to(400, 0)
    p.button(False)
    run(p)
    kinds = [(b, dx != 0 or dy != 0) for dx, dy, b, _ in phone.sent]
    first_press = kinds.index((1, False))
    assert all(b == 0 and moving for b, moving in kinds[:first_press])  # moved there first, unpressed
    assert any(b == 1 and moving for b, moving in kinds[first_press:])  # dragged with button held
    assert kinds[-1] == (0, False)  # released at the end
    assert phone.pos == pytest.approx([400, 0], abs=1)


def test_home_parks_in_corner_and_resets_estimate():
    p, phone = setup()
    phone.pos = [300.0, 300.0]  # real cursor somewhere unknown
    p.home()
    p.move_to(100, 100)
    run(p)
    assert phone.sent[:HOME_REPORTS] == [(-127, -127, 0, 0)] * HOME_REPORTS
    assert phone.pos == pytest.approx([100, 100], abs=1)


def test_target_clamped_to_screen():
    p, phone = setup()
    p.move_to(-50, 5000)
    run(p)
    assert phone.pos == pytest.approx([0, 1333], abs=1)


def test_wheel_sent_in_order():
    p, phone = setup()
    p.wheel(-2)
    run(p)
    assert phone.sent == [(0, 0, 0, -2)]


def test_pointer_click_sends_mask_then_release():
    p, phone = setup()
    p.click(2)
    run(p)
    assert phone.sent == [(0, 0, 2, 0), (0, 0, 0, 0)]


def test_report_pace_fits_the_bluetooth_link():
    # measured 2026-10-19 (iPhone 8, BLE helper): ~1 report per 15 ms gets through; at 8-12 ms reports
    # queued up and the cursor trailed behind the mouse, catching up when it stopped
    from scrcrappy.mouse import TICK
    assert TICK >= 0.015
