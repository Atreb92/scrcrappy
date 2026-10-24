import pytest

from scrcrappy.config import Custom
from scrcrappy.toolbar import BAR_H, buttons, hlayout, layout, next_free

HOME, APPS = Custom(2, "\ue9b2", "Home"), Custom(3, "\ue8eb", "")



def test_buttons_order_and_copy_disabled():
    items = buttons(has_input=True, customs=[HOME, APPS])
    assert [b.id if b else None for b in items] == ["paste", "screenshot", None, "custom:2", "custom:3", "add", None, "settings"]
    assert items[1].id == "screenshot"  # no phone clipboard to copy from in Bluetooth mode: a screenshot of the video instead
    assert all(b.enabled for b in items if b)
    assert items[7].toggled is False and items[0].toggled is None  # settings: highlighted while open


def test_natural_scrolling_lives_in_settings_not_the_bar():
    assert "natural" not in [b.id for b in buttons(has_input=True, customs=[]) if b]


def test_no_input_disables_actions():
    by_id = {b.id: b for b in buttons(has_input=False, customs=[HOME]) if b}
    for i in ("paste", "custom:2", "add"):
        assert not by_id[i].enabled and by_id[i].tip == "Needs --mouse ble, esp32 or agent"
    assert by_id["settings"].enabled


@pytest.mark.parametrize("height", range(60, 901, 7))
def test_layout_fits_height_without_overlap(height):
    width, rects = layout(buttons(True, [HOME, APPS]), height)
    spans = sorted((r.top, r.bottom) for _, r in rects)
    assert all(0 <= top and bottom <= height for top, bottom in spans)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert all(0 <= r.left and r.right <= width for _, r in rects)
    sizes = [r.height for b, r in rects if not b.small]
    assert max(sizes) <= 40
    if height >= 170:  # a phone window ~210 px tall or more
        assert min(sizes) >= 16


def test_bar_buttons_fit_the_window_width_and_the_strip():
    for width in (300, 375, 500, 900):
        rects = hlayout(buttons(True, [HOME, APPS]), width)
        spans = sorted((r.left, r.right) for _, r in rects)
        assert all(0 <= left and right <= width for left, right in spans)
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
        assert all(0 <= r.top and r.bottom <= BAR_H for _, r in rects)


def test_custom_tips_use_name_or_icon_label():
    by_id = {b.id: b for b in buttons(True, [HOME, APPS]) if b}
    assert by_id["custom:2"].tip.startswith("Home (button 2)")
    assert by_id["custom:3"].tip.startswith("App switcher (button 3)")  # no name: the icon's label


def test_add_hidden_when_full():
    full = [Custom(n, "\ue9b2", "") for n in (2, 3, 4, 5)]
    assert not any(b and b.id == "add" for b in buttons(True, full))


def test_next_free_reuses_lowest():
    assert next_free([]) == 2
    assert next_free([Custom(2, "\ue9b2", ""), Custom(4, "\ue9b2", "")]) == 3
    assert next_free([Custom(n, "\ue9b2", "") for n in (2, 3, 4, 5)]) is None


def test_agent_buttons_replace_custom_ones():
    items = buttons(has_input=True, customs=[HOME], agent=True)
    assert [b.id if b else None for b in items] == ["paste", "copy", "screenshot", None, "home", "switcher", "lock",
                                                   None, "settings"]
    assert all(b.enabled for b in items if b)


def test_every_icon_is_in_the_subset_font():
    # scripts/make-icons.sh keeps only listed glyphs: a new icon must be added there too
    import pygame
    from scrcrappy.config import ICON_CHOICES
    from scrcrappy.toolbar import ICONS
    pygame.font.init()
    font = pygame.font.Font(ICONS / "MaterialSymbolsRounded-outline.ttf", 20)
    used = {b.icon for agent in (False, True) for b in buttons(True, [], agent=agent) if b}
    used |= {c for c, _ in ICON_CHOICES} | {""}  # folder_open: Settings' browse button
    def look(c):
        return pygame.image.tobytes(font.render(c, True, (0, 0, 0), (255, 255, 255)), "RGB")

    missing = look("\U0010fffd")  # a codepoint no icon font has: renders the "missing" box
    assert [hex(ord(c)) for c in used if look(c) == missing] == []


def test_led_on_top_only_while_ai_control_is_on():
    assert buttons(True, [], agent=True, led=True)[0].id == "led"
    assert "led" not in [b.id for b in buttons(True, [], agent=True) if b]


def test_led_is_a_small_dot_in_the_strip():
    rects = {b.id: r for b, r in hlayout(buttons(True, [HOME], led=True), 375)}
    assert rects["led"].width <= rects["paste"].width * 0.4


def test_ui_font_has_every_character_we_draw():
    import pygame
    from scrcrappy.toolbar import ui_font
    pygame.font.init()
    for bold in (False, True):
        font = ui_font(14, bold)
        missing = font.render("\U0010fffd", True, (0, 0, 0))  # the "missing glyph" box
        for ch in "Aa0 ›…·é—":
            assert pygame.image.tobytes(font.render(ch, True, (0, 0, 0)), "RGBA") != pygame.image.tobytes(missing, "RGBA") or ch == " "


def test_screenshot_works_without_an_input_mode():
    by_id = {b.id: b for b in buttons(has_input=False, customs=[]) if b}
    assert by_id["screenshot"].enabled and by_id["screenshot"].tip == "Save a screenshot"  # it only needs the video


def test_shade_pressed_darker_hover_lighter():
    from scrcrappy.toolbar import shade
    base = (68, 68, 74)
    assert sum(shade(base, False, True)) < sum(base) < sum(shade(base, True, False))
    assert shade(base, False, False) == base
    assert max(shade((250, 250, 250), True, False)) <= 255
