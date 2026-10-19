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


def test_edit_from_menu_opens_dialog():
    # the menu closes itself and then asks for the dialog: that must not count as "a popup is open"
    from scrcrappy.dialog import Menu, Popups
    popups = Popups()
    opened = []

    def edit():
        opened.append(popups.open(lambda: Dialog(DialogState(2, "scrcrappy PC"), on_send=lambda: None, on_done=lambda r: None)))

    menu = popups.open(lambda: Menu((10, 10), 2, on_edit=edit, on_remove=lambda: None))
    popups.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, window=menu.win, button=1, pos=menu.hits["edit"].center))
    assert opened and isinstance(opened[0], Dialog)


def test_only_one_popup_at_a_time():
    from scrcrappy.dialog import Popups
    popups = Popups()
    first = popups.open(lambda: Dialog(DialogState(2, "x"), on_send=lambda: None, on_done=lambda r: None))
    assert first and popups.open(lambda: Dialog(DialogState(3, "x"), on_send=lambda: None, on_done=lambda r: None)) is None


def settings_panel(cfg, changes, **kw):
    from scrcrappy.dialog import Settings
    closed = []
    panel = Settings(cfg, place=lambda size: (0, 0), on_change=lambda: changes.append(1),
                     on_natural=lambda: setattr(cfg, "natural_scroll", not cfg.natural_scroll),
                     on_close=lambda: closed.append(1), **kw)
    return panel, closed


def click(panel, key):
    panel.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=panel.hits[key].center, window=panel.win))


def test_settings_mode_saves_at_once_and_esp32_shows_port():
    from scrcrappy.config import Config
    cfg, changes = Config(), []
    panel, _ = settings_panel(cfg, changes)
    assert "port" not in panel.hits
    click(panel, "mode:2")
    assert cfg.mouse == "esp32" and changes and "port" in panel.hits
    assert panel.win.size[1] == panel.height


def test_settings_typed_folder_kept_on_enter_and_on_close():
    from scrcrappy.config import Config
    cfg, changes = Config(), []
    panel, closed = settings_panel(cfg, changes)
    click(panel, "screenshots")
    panel.handle(pygame.event.Event(pygame.TEXTINPUT, text="~/shots", window=panel.win))
    panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, window=panel.win))
    assert cfg.screenshots == "~/shots" and len(changes) == 1
    click(panel, "screenshots")
    panel.handle(pygame.event.Event(pygame.TEXTINPUT, text="2", window=panel.win))
    panel.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=panel.win))  # clicked back on the phone
    assert cfg.screenshots == "~/shots2" and closed == [1]


def test_settings_natural_switch_and_empty_port_falls_back():
    from scrcrappy.config import Config
    cfg, changes = Config(mouse="esp32", port="/dev/x"), []
    panel, _ = settings_panel(cfg, changes)
    click(panel, "natural")
    assert cfg.natural_scroll is True
    click(panel, "port")
    for _ in range(6):
        panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, window=panel.win))
    panel.close()
    assert cfg.port == "/dev/ttyUSB0"


def test_calibration_section_only_with_a_mouse_and_calibrate_closes_the_panel():
    from scrcrappy.config import Config
    panel, _ = settings_panel(Config(), [])
    assert "calibrate" not in panel.hits  # agent / no input: nothing to calibrate
    started = []
    panel, closed = settings_panel(Config(), [], calibration=1.859, on_calibrate=lambda: started.append(1))
    assert any("1.86" in line for line in panel.calibration_lines)
    assert any("Tracking Speed" in line for line in panel.calibration_lines)
    click(panel, "calibrate")
    assert started == [1] and closed == [1] and panel.closed


def test_ai_switch_shows_status_and_copy():
    from scrcrappy.config import Config
    cfg, copied = Config(), []

    def toggle():
        cfg.ai_control = not cfg.ai_control

    panel, _ = settings_panel(cfg, [], on_ai=toggle, ai_status=lambda: "http://127.0.0.1:7331/mcp",
                              on_copy=lambda: copied.append(1))
    assert "copy" not in panel.hits
    click(panel, "ai")
    assert cfg.ai_control and "copy" in panel.hits and panel.win.size[1] == panel.height
    assert panel.ai_lines == ["http://127.0.0.1:7331/mcp"]
    click(panel, "copy")
    assert copied == [1]
