import io

import pygame
import pytest

from scrcrappy import actions


def png(w, h):
    surf = pygame.Surface((w, h))
    surf.fill((10, 20, 30))
    surf.fill((255, 0, 0), pygame.Rect(0, 0, 10, 10))  # red mark in the top-left corner
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "x.png")
    return buf.getvalue()


@pytest.mark.parametrize("text", ["101,5", "-1,5", "a,b", "5", "5,5,5,5"])
def test_parse_rejects_out_of_range_and_garbage(text):
    with pytest.raises(ValueError):
        actions.parse_point(text)


def test_parse_point_with_optional_duration():
    assert actions.parse_point("12.5,40") == (12.5, 40.0, None)
    assert actions.parse_point("12.5,40,1500") == (12.5, 40.0, 1500.0)
    assert actions.parse_points("10,90,10,20") == (10.0, 90.0, 10.0, 20.0, None)
    with pytest.raises(ValueError):
        actions.parse_points("10,90,10")


def test_portrait_identity():
    assert actions.to_portrait(25, 75, 1) == pytest.approx((0.25, 0.75))


def test_landscape_maps_like_the_upright_screenshot():
    # 3 = Home button on the right: the upright image's top-left is the panel's top-right
    assert actions.to_portrait(0, 0, 3) == pytest.approx((1, 0))
    assert actions.to_portrait(0, 0, 4) == pytest.approx((0, 1))
    assert actions.to_portrait(100, 100, 2) == pytest.approx((0, 0))


def test_tap_is_down_then_up_after_80ms():
    assert actions.tap(10, 20) == [(0, "down", 10, 20), (0.08, "up", 10, 20)]


def test_long_press_default_and_custom():
    assert actions.long_press(10, 20)[-1] == (1.0, "up", 10, 20)
    assert actions.long_press(10, 20, 2500)[-1][0] == 2.5


def test_swipe_ends_at_target_and_lasts_ms():
    steps = actions.swipe(50, 80, 50, 20)
    assert steps[0] == (0, "down", 50, 80)
    assert steps[-1][1:] == ("up", 50, 20)
    assert sum(d for d, *_ in steps) == pytest.approx(0.3, abs=0.02)
    assert sum(d for d, *_ in actions.swipe(0, 0, 0, 50, 1000)) == pytest.approx(1.0, abs=0.02)


def test_typing_plan():
    kind, strokes = actions.typing_plan("hi\n")
    assert kind == "keys" and len(strokes) == 3
    assert actions.typing_plan("caffè") == ("paste", [])


def test_upright_png_rotates_and_caps():
    data, w, h = actions.upright_png(png(750, 1334), 3)
    img = pygame.image.load(io.BytesIO(data), "x.png")
    assert (w, h) == img.get_size() == (1334, 750)
    assert img.get_at((5, 744))[:3] == (255, 0, 0)  # 90° counter-clockwise: top-left goes to bottom-left
    _, w, h = actions.upright_png(png(1125, 2436), 1)
    assert max(w, h) == 1568 and w == round(1125 * 1568 / 2436)


def test_frame_png_from_video_frame():
    frame = (bytes(4 * 2 * 3), (4, 2), 12)
    data, w, h = actions.frame_png(frame)
    assert (w, h) == (4, 2) and data.startswith(b"\x89PNG")
