import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy.config import Custom
from scrcrappy.toolbar import BAR_H, TIP_DELAY, Bar, buttons

HOME = Custom(2, "", "Home")


@pytest.fixture(autouse=True)
def video():
    pygame.init()
    yield
    pygame.quit()


@pytest.fixture
def bar():
    seen = []
    actions = {n: (lambda n=n: seen.append(n)) for n in ("paste", "add", "settings")}
    actions["custom"] = lambda n: seen.append(("custom", n))
    actions["menu"] = lambda n: seen.append(("menu", n))
    b = Bar(pygame.Window("phone", (375, 715)), buttons(True, [HOME]), actions)
    b.seen = seen
    return b


def at(bar, id_):
    r = next(r for b, r in bar.rects if b.id == id_)
    return r.center


def ev(bar, kind, pos, button=1):
    return pygame.event.Event(kind, window=bar.main, pos=pos, button=button)


def click(bar, id_, button=1):
    bar.handle(ev(bar, pygame.MOUSEBUTTONDOWN, at(bar, id_), button))
    return bar.handle(ev(bar, pygame.MOUSEBUTTONUP, at(bar, id_), button))


def test_strip_sits_at_the_bottom_of_the_window(bar):
    assert bar.top == 715 - BAR_H
    assert all(bar.top <= r.top and r.bottom <= 715 for _, r in bar.rects)


def test_click_runs_the_action_and_is_consumed(bar):
    assert click(bar, "paste") is True
    click(bar, "custom:2")
    click(bar, "add")
    assert bar.seen == ["paste", ("custom", 2), "add"]


def test_right_click_on_a_custom_button_opens_its_menu(bar):
    click(bar, "custom:2", button=3)
    assert bar.seen == [("menu", 2)]


def test_disabled_button_does_nothing():
    seen = []
    b = Bar(pygame.Window("phone", (375, 715)), buttons(False, []), {"settings": lambda: seen.append(1), "paste": seen.append})
    click(b, "paste")
    assert seen == []


def test_events_above_the_strip_go_on_to_the_phone(bar):
    assert bar.handle(ev(bar, pygame.MOUSEBUTTONUP, (100, 100))) is False
    assert bar.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, window=None, pos=at(bar, "paste"), button=1)) is False
    assert bar.seen == []


def test_tooltip_after_a_delay_and_gone_when_the_mouse_leaves(bar):
    bar.handle(ev(bar, pygame.MOUSEMOTION, at(bar, "settings")))
    bar.update(now=bar.hover_since + TIP_DELAY - 0.1)
    assert bar.tip_text is None
    bar.update(now=bar.hover_since + TIP_DELAY + 0.1)
    assert bar.tip_text == "Settings"
    screen = pygame.Surface((375, 715))
    screen.fill((255, 255, 255))
    bar.draw(screen)
    assert any(screen.get_at((x, bar.top - 12))[:3] != (255, 255, 255) for x in range(375))  # drawn above the strip
    bar.handle(ev(bar, pygame.MOUSEMOTION, (100, 100)))
    assert bar.tip_text is None and bar.hover is None


def test_follow_after_a_resize(bar):
    bar.main.size = (500, 800)
    bar.follow()
    assert bar.top == 800 - BAR_H and max(r.right for _, r in bar.rects) <= 500


def test_pressing_a_button_hides_its_tooltip_until_the_mouse_moves_on(bar):
    bar.handle(ev(bar, pygame.MOUSEMOTION, at(bar, "custom:2")))
    bar.update(now=bar.hover_since + TIP_DELAY + 0.1)
    assert bar.tip_text
    bar.handle(ev(bar, pygame.MOUSEBUTTONDOWN, at(bar, "custom:2"), button=3))  # right-click: the menu opens there
    assert bar.tip_text is None
    bar.update(now=bar.hover_since + 10)
    assert bar.tip_text is None
    bar.handle(ev(bar, pygame.MOUSEMOTION, at(bar, "settings")))
    bar.update(now=bar.hover_since + TIP_DELAY + 0.1)
    assert bar.tip_text == "Settings"


def test_a_drag_that_started_on_the_phone_is_not_swallowed_by_the_strip(bar):
    assert bar.handle(ev(bar, pygame.MOUSEBUTTONDOWN, (100, 100))) is False  # press on the phone
    assert bar.handle(ev(bar, pygame.MOUSEMOTION, at(bar, "paste"))) is False  # dragged down onto the strip
    assert bar.handle(ev(bar, pygame.MOUSEBUTTONUP, at(bar, "paste"))) is False  # the phone must see the release
    assert bar.seen == []  # and it is not a click on the button
    assert click(bar, "paste") is True and bar.seen == ["paste"]  # the next press on the strip works as usual


def test_toast_shows_above_the_strip_then_expires(bar):
    bar.toast("Screenshot saved: a.png", seconds=2)
    bar.update(now=bar.toast_until - 1)
    assert bar.toast_text
    screen = pygame.Surface((375, 715))
    screen.fill((255, 255, 255))
    bar.draw(screen)
    assert any(screen.get_at((x, bar.top - 12))[:3] != (255, 255, 255) for x in range(375))
    bar.update(now=bar.toast_until + 0.1)
    assert bar.toast_text is None


def test_a_press_whose_release_never_came_does_not_swallow_the_next_bar_click(bar):
    bar.handle(ev(bar, pygame.MOUSEBUTTONDOWN, (100, 100)))  # pressed on the phone, then the window lost focus
    bar.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=bar.main))
    assert click(bar, "paste") is True and bar.seen == ["paste"]
    bar.handle(ev(bar, pygame.MOUSEBUTTONDOWN, (100, 100)))
    bar.handle(pygame.event.Event(pygame.WINDOWLEAVE, window=bar.main))  # or the mouse left the window
    assert click(bar, "settings") is True and bar.seen == ["paste", "settings"]
