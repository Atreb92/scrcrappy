import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy.toolbar import TAB, Pill, buttons


@pytest.fixture
def pill():
    pygame.init()
    main = pygame.Window("phone", (300, 500))
    calls = []
    actions = {i: (lambda i=i: calls.append(i)) for i in ("paste", "copy", "home", "apps", "natural")}
    p = Pill(main, buttons(has_input=True, natural=False), actions)
    p.calls = calls
    yield p
    pygame.quit()


def at(p, button_id):
    return next(r.center for b, r in p.rects if b.id == button_id)


def ev(p, kind, **kw):
    return pygame.event.Event(kind, window=p.win, **kw)


def click(p, button_id):
    p.handle(ev(p, pygame.MOUSEBUTTONUP, button=1, pos=at(p, button_id)))


def test_click_runs_action(pill):
    click(pill, "home")
    assert pill.calls == ["home"]


def test_click_on_disabled_button_does_nothing(pill):
    click(pill, "copy")
    assert pill.calls == []


def test_toggle_flips_state(pill):
    click(pill, "natural")
    assert pill.calls == ["natural"]
    assert next(b for b, _ in pill.rects if b.id == "natural").toggled is True


def test_tooltip_after_hover_hides_on_leave(pill):
    pill.handle(ev(pill, pygame.MOUSEMOTION, pos=at(pill, "home")))
    pill.update(now=pill.hover_since + 0.6)
    assert pill.tip_text == "Home"
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    pill.update(now=pill.hover_since + 1.0 if pill.hover_since else 99)
    assert pill.tip_text is None


def test_collapse_then_expand_on_enter_and_recollapse_3s_after_leave(pill):
    click(pill, "collapse")
    assert pill.collapsed and pill.win.size == TAB
    pill.handle(ev(pill, pygame.WINDOWENTER))
    assert not pill.collapsed
    pill.handle(ev(pill, pygame.WINDOWLEAVE))
    left = pill.leave_at
    pill.update(now=left + 2.9)
    assert not pill.collapsed
    pill.update(now=left + 3.0)
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
