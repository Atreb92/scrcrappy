import pytest

from scrcrappy.geometry import ROTATION_BY_ORIENTATION, to_device

TALL = (269, 0, 462, 1000)  # portrait frame letterboxed in a 1000x1000 window
WIDE = (0, 0, 1000, 461)  # landscape frame filling a 1000-wide window
SIZE = (375, 812)  # ZXTouch portrait screen size


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
