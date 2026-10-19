import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy.config import Custom
from scrcrappy.toolbar import TAB, Pill, buttons


@pytest.fixture
def pill():
    pygame.init()
    main = pygame.Window("phone", (300, 500))
    calls = []
    actions = {i: (lambda *a, i=i: calls.append((i, *a))) for i in ("paste", "copy", "natural", "add", "custom", "menu")}
    p = Pill(main, buttons(has_input=True, natural=False, customs=[Custom(2, "\ue9b2", "Home")]), actions)
    p.calls = calls
    yield p
    pygame.quit()


def at(p, button_id):
    return next(r.center for b, r in p.rects if b.id == button_id)


def ev(p, kind, **kw):
    return pygame.event.Event(kind, window=p.win, **kw)


def click(p, button_id, mouse_button=1):
    p.handle(ev(p, pygame.MOUSEBUTTONUP, button=mouse_button, pos=at(p, button_id)))


def test_click_custom_runs_action_with_its_button(pill):
    click(pill, "custom:2")
    assert pill.calls == [("custom", 2)]


def test_click_add(pill):
    click(pill, "add")
    assert pill.calls == [("add",)]


def test_right_click_custom_opens_menu(pill):
    click(pill, "custom:2", mouse_button=3)
    assert pill.calls == [("menu", 2)]


def test_right_click_other_does_nothing(pill):
    click(pill, "paste", mouse_button=3)
    pill.handle(ev(pill, pygame.MOUSEBUTTONUP, button=3, pos=(0, 0)))
    assert pill.calls == []


def test_set_items_relayouts(pill):
    pill.set_items(buttons(True, False, []))
    assert not any(b.id.startswith("custom:") for b, _ in pill.rects)


def test_click_on_disabled_button_does_nothing(pill):
    click(pill, "copy")
    assert pill.calls == []


def test_toggle_flips_state(pill):
    click(pill, "natural")
    assert pill.calls == [("natural",)]
    assert next(b for b, _ in pill.rects if b.id == "natural").toggled is True


def test_tooltip_after_hover_hides_on_leave(pill):
    pill.handle(ev(pill, pygame.MOUSEMOTION, pos=at(pill, "paste")))
    pill.update(now=pill.hover_since + 0.6)
    assert pill.tip_text.startswith("Paste")
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    pill.update(now=pill.hover_since + 1.0 if pill.hover_since else 99)
    assert pill.tip_text is None


def test_collapse_then_expand_on_enter_and_recollapse_2s_after_leave(pill):
    click(pill, "collapse")
    assert pill.collapsed and pill.win.size == TAB
    pill.handle(ev(pill, pygame.WINDOWENTER))
    assert not pill.collapsed
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    left = pill.leave_at
    pill.update(now=left + 1.9)
    assert not pill.collapsed
    pill.update(now=left + 2.0)
    assert pill.collapsed


def test_coming_back_cancels_autohide(pill):
    click(pill, "collapse")
    pill.handle(ev(pill, pygame.WINDOWENTER))
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    left = pill.leave_at
    pill.handle(ev(pill, pygame.WINDOWENTER))
    pill.update(now=left + 5)
    assert not pill.collapsed


def test_pinning_while_hover_expanded_keeps_it_open(pill):
    click(pill, "collapse")
    pill.handle(ev(pill, pygame.WINDOWENTER))
    click(pill, "collapse")  # now "keep open"
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    pill.update(now=10**9)
    assert not pill.collapsed


def test_collapsing_hides_tooltip(pill):
    pill.handle(ev(pill, pygame.MOUSEMOTION, pos=at(pill, "collapse")))
    pill.update(now=pill.hover_since + 0.6)
    click(pill, "collapse")
    pill.update(now=pill.hover_since + 1.0 if pill.hover_since else 99)
    assert pill.tip_text is None


def test_events_for_other_windows_are_ignored(pill):
    assert pill.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, window=pill.main, button=1, pos=(1, 1))) is False


def test_hides_when_app_loses_focus_and_returns(pill):
    pill.update(now=0, app_focused=False)
    assert pill.visible  # brief focus gaps (clicking the pill) don't hide it
    pill.update(now=0.3, app_focused=False)
    assert not pill.visible
    pill.update(now=0.4, app_focused=True)
    assert pill.visible


def test_pin_changes_reported(pill):
    seen = []
    pill.actions["pinned"] = seen.append
    click(pill, "collapse")
    assert seen == [False]


def test_starts_collapsed_when_not_pinned():
    pygame.init()
    p = Pill(pygame.Window("phone", (300, 500)), buttons(True, False, []), {}, pinned=False)
    assert p.collapsed and not p.pinned
    pygame.quit()
