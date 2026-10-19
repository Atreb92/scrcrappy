import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy.config import ICON_CHOICES, Custom
from scrcrappy.dialog import Dialog, DialogState


@pytest.fixture(autouse=True)
def video():
    pygame.init()
    yield
    pygame.quit()


def test_state_defaults_and_result():
    s = DialogState(4, "scrcrappy PC")
    assert s.icon == ICON_CHOICES[0][0] and s.name == ""
    s.select(2)
    s.type("Lock")
    s.backspace()
    assert s.result() == Custom(4, ICON_CHOICES[2][0], "Loc")


def test_edit_prefills():
    s = DialogState(3, "scrcrappy PC", Custom(3, ICON_CHOICES[1][0], "Apps"))
    assert (s.icon, s.name, s.title) == (ICON_CHOICES[1][0], "Apps", "Edit button")


def test_steps_name_device_and_button():
    text = " ".join(DialogState(4, "scrcrappy ESP32").steps())
    assert "AssistiveTouch › Devices › scrcrappy ESP32" in text
    assert "Send button 4" in text
    assert "Button 4" in text and "Secondary Click" in text


def dialog(**kw):
    done = []
    d = Dialog(DialogState(4, "scrcrappy PC"), on_send=kw.get("on_send", lambda: None), on_done=done.append)
    return d, done


def ev(d, kind, **kw):
    return pygame.event.Event(kind, window=d.win, **kw)


def test_typing_goes_to_name(  ):
    d, _ = dialog()
    d.handle(ev(d, pygame.TEXTINPUT, text="Hi"))
    d.handle(ev(d, pygame.KEYDOWN, key=pygame.K_BACKSPACE, scancode=0x2A))
    assert d.state.name == "H"


def test_other_windows_events_ignored():
    d, _ = dialog()
    assert d.handle(pygame.event.Event(pygame.TEXTINPUT, window=None, text="x")) is False
    assert d.state.name == ""


def test_escape_cancels():
    d, done = dialog()
    d.handle(ev(d, pygame.KEYDOWN, key=pygame.K_ESCAPE, scancode=0x29))
    assert done == [None] and d.closed


def test_ok_returns_custom():
    d, done = dialog()
    d.handle(ev(d, pygame.MOUSEBUTTONUP, button=1, pos=d.hits["icon:5"].center))
    d.handle(ev(d, pygame.MOUSEBUTTONUP, button=1, pos=d.hits["ok"].center))
    assert done == [Custom(4, ICON_CHOICES[5][0], "")]


def test_click_send_calls_on_send():
    sent = []
    d, done = dialog(on_send=lambda: sent.append(1))
    d.handle(ev(d, pygame.MOUSEBUTTONUP, button=1, pos=d.hits["send"].center))
    assert sent == [1] and done == []


def test_menu_remove_calls_back():
    from scrcrappy.dialog import Menu
    calls = []
    m = Menu((100, 100), 3, on_edit=lambda: calls.append("edit"), on_remove=lambda: calls.append("remove"))
    m.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, window=m.win, button=1, pos=m.hits["remove"].center))
    assert calls == ["remove"] and m.closed


def test_menu_closes_when_focus_lost():
    from scrcrappy.dialog import Menu
    m = Menu((100, 100), 3, on_edit=lambda: None, on_remove=lambda: None)
    m.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=m.win))
    assert m.closed
