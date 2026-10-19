import pytest

from scrcrappy.toolbar import TAB, Button, buttons, layout, pill_rect

COPY_TIP = "Needs jailbreak"


def test_buttons_order_and_copy_disabled():
    items = buttons(has_input=True, natural=False)
    assert [b.id if b else None for b in items] == ["paste", "copy", None, "home", "apps", None, "natural", None, "collapse"]
    copy = items[1]
    assert not copy.enabled and copy.tip == COPY_TIP
    assert all(b.enabled for b in items if b and b.id != "copy")
    assert items[6].toggled is False and items[0].toggled is None
    assert items[-1].small


def test_natural_toggle_reflects_setting():
    assert buttons(has_input=True, natural=True)[6].toggled is True


def test_no_input_disables_actions():
    by_id = {b.id: b for b in buttons(has_input=False, natural=False) if b}
    for i in ("paste", "home", "apps"):
        assert not by_id[i].enabled and by_id[i].tip == "Needs --mouse ble or esp32"
    assert by_id["natural"].enabled and by_id["collapse"].enabled


def test_pill_is_80_percent_and_centred():
    items = buttons(True, False)
    x, y, w, h = pill_rect((100, 100), (300, 500), (1920, 1080), items)
    assert (x, y, h) == (411, 150, 400)  # 11 px gap
    assert w == layout(items, 400)[0]


def test_pill_flips_left_at_screen_edge():
    items = buttons(True, False)
    x, y, w, h = pill_rect((1600, 100), (300, 500), (1920, 1080), items)
    assert x == 1600 - 11 - w


@pytest.mark.parametrize("height", range(60, 901, 7))
def test_layout_fits_height_without_overlap(height):
    width, rects = layout(buttons(True, False), height)
    spans = sorted((r.top, r.bottom) for _, r in rects)
    assert all(0 <= top and bottom <= height for top, bottom in spans)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert all(0 <= r.left and r.right <= width for _, r in rects)
    sizes = [r.height for b, r in rects if not b.small]
    assert max(sizes) <= 40
    if height >= 150:
        assert min(sizes) >= 16


def test_collapse_button_is_smaller():
    _, rects = layout(buttons(True, False), 400)
    normal = rects[0][1].height
    small = [r for b, r in rects if b.small][0].height
    assert small == pytest.approx(normal * 0.6, abs=1)


def test_tab_is_thin():
    assert TAB[0] < TAB[1]
