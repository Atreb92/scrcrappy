import pytest

from scrcrappy.config import Custom
from scrcrappy.toolbar import TAB, Button, buttons, layout, next_free, pill_rect

HOME, APPS = Custom(2, "\ue9b2", "Home"), Custom(3, "\ue8eb", "")

COPY_TIP = "Needs --mouse agent (jailbreak)"


def test_buttons_order_and_copy_disabled():
    items = buttons(has_input=True, natural=False, customs=[HOME, APPS])
    assert [b.id if b else None for b in items] == ["paste", "copy", None, "custom:2", "custom:3", "add", None, "natural", "settings", None, "collapse"]
    copy = items[1]
    assert not copy.enabled and copy.tip == COPY_TIP
    assert all(b.enabled for b in items if b and b.id != "copy")
    assert items[7].toggled is False and items[0].toggled is None
    assert items[-1].small


def test_natural_toggle_reflects_setting():
    assert buttons(has_input=True, natural=True, customs=[])[5].toggled is True


def test_no_input_disables_actions():
    by_id = {b.id: b for b in buttons(has_input=False, natural=False, customs=[HOME]) if b}
    for i in ("paste", "custom:2", "add"):
        assert not by_id[i].enabled and by_id[i].tip == "Needs --mouse ble, esp32 or agent"
    assert by_id["natural"].enabled and by_id["collapse"].enabled


def test_pill_is_80_percent_and_centred():
    items = buttons(True, False, [HOME, APPS])
    x, y, w, h = pill_rect((100, 100), (300, 500), (1920, 1080), items)
    assert (x, y, h) == (411, 150, 400)  # 11 px gap
    assert w == layout(items, 400)[0]


def test_pill_flips_left_at_screen_edge():
    items = buttons(True, False, [HOME, APPS])
    x, y, w, h = pill_rect((1600, 100), (300, 500), (1920, 1080), items)
    assert x == 1600 - 11 - w


@pytest.mark.parametrize("height", range(60, 901, 7))
def test_layout_fits_height_without_overlap(height):
    width, rects = layout(buttons(True, False, [HOME, APPS]), height)
    spans = sorted((r.top, r.bottom) for _, r in rects)
    assert all(0 <= top and bottom <= height for top, bottom in spans)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert all(0 <= r.left and r.right <= width for _, r in rects)
    sizes = [r.height for b, r in rects if not b.small]
    assert max(sizes) <= 40
    if height >= 170:  # a phone window ~210 px tall or more
        assert min(sizes) >= 16


def test_collapse_button_is_smaller():
    _, rects = layout(buttons(True, False, [HOME, APPS]), 400)
    normal = rects[0][1].height
    small = [r for b, r in rects if b.small][0].height
    assert small == pytest.approx(normal * 0.6, abs=1)


def test_tab_is_thin():
    assert TAB[0] < TAB[1]


def test_custom_tips_use_name_or_icon_label():
    by_id = {b.id: b for b in buttons(True, False, [HOME, APPS]) if b}
    assert by_id["custom:2"].tip.startswith("Home (button 2)")
    assert by_id["custom:3"].tip.startswith("App switcher (button 3)")  # no name: the icon's label


def test_add_hidden_when_full():
    full = [Custom(n, "\ue9b2", "") for n in (2, 3, 4, 5)]
    assert not any(b and b.id == "add" for b in buttons(True, False, full))


def test_next_free_reuses_lowest():
    assert next_free([]) == 2
    assert next_free([Custom(2, "\ue9b2", ""), Custom(4, "\ue9b2", "")]) == 3
    assert next_free([Custom(n, "\ue9b2", "") for n in (2, 3, 4, 5)]) is None


def test_agent_buttons_replace_custom_ones():
    items = buttons(has_input=True, natural=False, customs=[HOME], agent=True)
    assert [b.id if b else None for b in items] == ["paste", "copy", "screenshot", None, "home", "switcher", "lock",
                                                   None, "natural", "settings", None, "collapse"]
    assert all(b.enabled for b in items if b)


def test_every_icon_is_in_the_subset_font():
    # scripts/make-icons.sh keeps only listed glyphs: a new icon must be added there too
    import pygame
    from scrcrappy.config import ICON_CHOICES
    from scrcrappy.toolbar import CHEVRON_KEEP, ICONS
    pygame.font.init()
    font = pygame.font.Font(ICONS / "MaterialSymbolsRounded-outline.ttf", 20)
    used = {b.icon for agent in (False, True) for b in buttons(True, False, [], agent=agent) if b}
    used |= {c for c, _ in ICON_CHOICES} | {CHEVRON_KEEP, ""}  # folder_open: Settings' browse button
    def look(c):
        return pygame.image.tobytes(font.render(c, True, (0, 0, 0), (255, 255, 255)), "RGB")

    missing = look("\U0010fffd")  # a codepoint no icon font has: renders the "missing" box
    assert [hex(ord(c)) for c in used if look(c) == missing] == []
