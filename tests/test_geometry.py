import pytest

from scrcrappy.geometry import ROTATION_BY_ORIENTATION, aspect_size, reshaped_size, to_device

TALL = (269, 0, 462, 1000)  # portrait frame letterboxed in a 1000x1000 window
WIDE = (0, 0, 1000, 461)  # landscape frame filling a 1000-wide window
SIZE = (375, 812)  # a portrait screen in points (iPhone X)


def test_centre_maps_to_centre():
    assert to_device((500, 500), TALL, 0, SIZE) == pytest.approx((187.5, 406), abs=1)


def test_corners_portrait():
    assert to_device((269, 0), TALL, 0, SIZE) == pytest.approx((0, 0), abs=1)
    assert to_device((730, 999), TALL, 0, SIZE) == pytest.approx((375, 812), abs=1)


def test_click_in_letterbox_is_ignored():
    assert to_device((10, 500), TALL, 0, SIZE) is None


def test_rotation_90_top_left_of_frame():
    # frame shown rotated 90° clockwise: its top-left is the portrait screen's bottom-left
    assert to_device((0, 0), WIDE, 90, SIZE) == pytest.approx((0, 812), abs=1)


def test_rotation_270_top_left_of_frame():
    assert to_device((0, 0), WIDE, 270, SIZE) == pytest.approx((375, 0), abs=1)


def test_rotation_180_top_left_is_bottom_right():
    assert to_device((269, 0), TALL, 180, SIZE) == pytest.approx((375, 812), abs=1)


def test_orientation_table_covers_uikit_values():
    assert set(ROTATION_BY_ORIENTATION) == {1, 2, 3, 4}


PHONE = (750, 1334)


def test_dragging_the_width_makes_the_height_follow_the_aspect():
    w, h = aspect_size(PHONE, (500, 715), last=(375, 715), bar_h=48)  # width dragged from 375 to 500
    assert w == 500 and h == round(500 * 1334 / 750) + 48


def test_dragging_the_height_makes_the_width_follow():
    w, h = aspect_size(PHONE, (375, 900), last=(375, 715), bar_h=48)
    assert h == 900 and w == round((900 - 48) * 750 / 1334)


def test_aspect_is_already_right_is_a_fixed_point():
    size = (375, 667 + 48)
    assert aspect_size(PHONE, size, last=(300, 500), bar_h=48) == size


def test_rotating_the_phone_keeps_the_long_side():
    assert reshaped_size((1334, 750), (375, 715), bar_h=48) == (667, round(667 * 750 / 1334) + 48)  # landscape
    w, h = reshaped_size(PHONE, (667, 423), bar_h=48)  # and back to portrait: the image area is 375 x 667 again
    assert (h - 48) == 667 and abs(w - 375) <= 1
