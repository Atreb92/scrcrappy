import os

os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import pytest

from scrcrappy.config import ICON_CHOICES, Custom
from scrcrappy.dialog import PANEL_W, Dialog, DialogState


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


def menu_overlay(**kw):
    from scrcrappy.dialog import Menu
    closed = []
    window = pygame.Window("phone", (375, 715))
    menu = Menu(window, lambda size: pygame.Rect(40, 300, *size), 3, on_edit=kw.get("on_edit", lambda: None),
                on_remove=kw.get("on_remove", lambda: None), on_close=lambda: closed.append(1))
    return menu, closed


def menu_event(menu, kind, key=None, **kw):
    pos = (menu.rect.x + menu.hits[key].centerx, menu.rect.y + menu.hits[key].centery) if key else kw.pop("pos", (0, 0))
    return pygame.event.Event(kind, window=menu.window, button=1, pos=pos, **kw)


def test_menu_remove_calls_back_and_closes():
    calls = []
    m, closed = menu_overlay(on_remove=lambda: calls.append("remove"))
    assert m.handle(menu_event(m, pygame.MOUSEBUTTONUP, "remove")) is True
    assert calls == ["remove"] and m.closed and closed == [1]


def test_menu_closes_on_focus_loss_esc_and_outside_click_and_takes_input():
    m, closed = menu_overlay()
    assert m.handle(menu_event(m, pygame.MOUSEMOTION, pos=(5, 5))) is True  # the phone never sees the mouse
    assert m.handle(menu_event(m, pygame.MOUSEBUTTONDOWN, pos=(5, 5))) is True and not closed
    m.handle(menu_event(m, pygame.MOUSEBUTTONUP, pos=(5, 5)))
    assert m.closed
    m, _ = menu_overlay()
    m.handle(pygame.event.Event(pygame.KEYDOWN, window=m.window, key=pygame.K_ESCAPE))
    assert m.closed
    m, _ = menu_overlay()
    assert m.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=m.window)) is False
    assert m.closed
    m, _ = menu_overlay()
    assert m.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, window=None, button=1, pos=(5, 5))) is False and not m.closed


def test_menu_draws_over_the_window():
    m, _ = menu_overlay()
    screen = pygame.Surface((375, 715))
    screen.fill((255, 255, 255))
    m.hover = "edit"
    m.draw(screen, 667)
    assert screen.get_at((m.rect.centerx, m.rect.y + 3))[:3] != (255, 255, 255)


def test_edit_from_menu_opens_dialog():
    # the menu closes itself and then asks for the dialog
    from scrcrappy.dialog import Popups
    popups, opened = Popups(), []

    def edit():
        opened.append(popups.open(lambda: Dialog(DialogState(2, "scrcrappy PC"), on_send=lambda: None, on_done=lambda r: None)))

    menu, _ = menu_overlay(on_edit=edit)
    menu.handle(menu_event(menu, pygame.MOUSEBUTTONUP, "edit"))
    assert opened and isinstance(opened[0], Dialog)


def test_only_one_popup_at_a_time():
    from scrcrappy.dialog import Popups
    popups = Popups()
    first = popups.open(lambda: Dialog(DialogState(2, "x"), on_send=lambda: None, on_done=lambda r: None))
    assert first and popups.open(lambda: Dialog(DialogState(3, "x"), on_send=lambda: None, on_done=lambda r: None)) is None


def settings_panel(cfg, changes, **kw):
    from scrcrappy.dialog import Settings
    closed = []
    window = pygame.Window("phone", (375, 715))
    panel = Settings(window, lambda size: pygame.Rect(20, 30, *size), cfg, on_change=lambda: changes.append(1),
                     on_natural=lambda: setattr(cfg, "natural_scroll", not cfg.natural_scroll),
                     on_close=lambda: closed.append(1), **kw)
    return panel, closed


def click(panel, key):
    x, y = panel.hits[key].center
    panel.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x + panel.rect.x, y + panel.rect.y),
                                    window=panel.window))


def test_settings_mode_saves_at_once_and_esp32_shows_port():
    from scrcrappy.config import Config
    cfg, changes = Config(), []
    panel, _ = settings_panel(cfg, changes)
    assert "port" not in panel.hits
    click(panel, "mode:2")
    assert cfg.mouse == "esp32" and changes and "port" in panel.hits
    assert panel.rect.height == panel.height


def test_settings_typed_folder_kept_on_enter_and_on_close():
    from scrcrappy.config import Config
    cfg, changes = Config(), []
    panel, closed = settings_panel(cfg, changes)
    click(panel, "screenshots")
    panel.handle(pygame.event.Event(pygame.TEXTINPUT, text="~/shots", window=panel.window))
    panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, window=panel.window))
    assert cfg.screenshots == "~/shots" and len(changes) == 1
    click(panel, "screenshots")
    panel.handle(pygame.event.Event(pygame.TEXTINPUT, text="2", window=panel.window))
    panel.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=panel.window))  # clicked back on the phone
    assert cfg.screenshots == "~/shots2" and closed == [1]


def test_settings_natural_switch_and_empty_port_falls_back():
    from scrcrappy.config import Config
    cfg, changes = Config(mouse="esp32", port="/dev/x"), []
    panel, _ = settings_panel(cfg, changes)
    click(panel, "natural")
    assert cfg.natural_scroll is True
    click(panel, "port")
    for _ in range(6):
        panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, window=panel.window))
    panel.close()
    assert cfg.port == "/dev/ttyUSB0"


def test_calibration_section_only_with_a_mouse_and_calibrate_closes_the_panel():
    from scrcrappy.config import Config
    panel, _ = settings_panel(Config(), [])
    assert "calibrate" not in panel.hits  # agent / no input: nothing to calibrate
    started = []
    panel, closed = settings_panel(Config(), [], calibration=1.859, on_calibrate=lambda: started.append(1))
    assert any("1.86" in line for line in panel.calibration_lines)
    assert len(panel.calibration_lines) == 1  # short; the explanation is the Calibrate button's tooltip
    assert "Tracking Speed" in panel.tips["calibrate"]
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
    assert cfg.ai_control and "copy" in panel.hits and panel.rect.height == panel.height
    assert panel.ai_lines == ["http://127.0.0.1:7331/mcp"]
    click(panel, "copy")
    assert copied == [1]


def test_settings_overlay_takes_all_input_and_closes_on_outside_click_or_esc():
    from scrcrappy.config import Config
    panel, closed = settings_panel(Config(), [])
    w = panel.window
    for kind in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN, pygame.KEYUP, pygame.TEXTINPUT):
        assert panel.handle(pygame.event.Event(kind, window=w, pos=(5, 5), button=1, key=pygame.K_a, text="a"))
    assert not closed  # a press outside doesn't close: the release does, so the toolbar never sees the click
    assert panel.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(5, 5), window=w))
    assert closed == [1]
    panel, closed = settings_panel(Config(), [])
    panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, window=panel.window))
    assert closed == [1]


def test_settings_overlay_ignores_other_windows_and_stays_open_for_the_folder_picker():
    from scrcrappy.config import Config
    panel, closed = settings_panel(Config(), [])
    assert panel.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, window=None)) is False
    panel.picking = True
    panel.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=panel.window))
    assert not closed
    panel.picking = False
    assert panel.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=panel.window)) is False  # phone sees it too
    assert closed == [1]


def test_settings_overlay_draws_onto_the_window_surface():
    from scrcrappy.config import Config
    panel, _ = settings_panel(Config(mouse="esp32"), [], calibration=1.5)
    screen = pygame.Surface((375, 715))
    screen.fill((255, 255, 255))
    panel.draw(screen, 667)
    assert screen.get_at((370, 10))[:3] != (255, 255, 255)  # dimmed
    assert screen.get_at((30 + 5, 30 + 5))[:3] != (255, 255, 255)  # the panel's own colour, not the image's
    assert screen.get_at((370, 700))[:3] == (255, 255, 255)  # the bar's area is left alone


def test_popups_report_whether_one_is_open():
    from scrcrappy.dialog import Popups

    class Fake:
        closed = False

    p = Popups()
    assert not p.is_open()
    popup = p.open(Fake)
    assert p.is_open() and p.open(Fake) is None
    popup.closed = True
    assert not p.is_open()


def test_calibrate_tooltip_shows_after_a_hover_delay():
    from scrcrappy.config import Config
    from scrcrappy.toolbar import TIP_DELAY
    panel, _ = settings_panel(Config(), [], calibration=1.5)
    x, y = panel.hits["calibrate"].center
    panel.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(x + panel.rect.x, y + panel.rect.y), window=panel.window))
    assert panel.tip(panel.hover_since + TIP_DELAY - 0.1) is None
    assert "Tracking Speed" in panel.tip(panel.hover_since + TIP_DELAY + 0.1)
    panel.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(1, 1), window=panel.window))  # off the button
    assert panel.tip(panel.hover_since + 5) is None
    screen = pygame.Surface((375, 715))
    panel.handle(pygame.event.Event(pygame.MOUSEMOTION, pos=(x + panel.rect.x, y + panel.rect.y), window=panel.window))
    panel.hover_since -= 5
    panel.draw(screen, 667)  # draws the tooltip without error


def test_settings_does_not_look_at_the_disk_every_frame(monkeypatch):
    from scrcrappy import dialog
    from scrcrappy.config import Config
    calls = []
    monkeypatch.setattr(dialog, "default_folder_label", lambda: calls.append(1) or "~/Pictures")
    panel, _ = settings_panel(Config(), [])
    screen = pygame.Surface((375, 715))
    for _ in range(5):
        panel.draw(screen, 667)
    assert len(calls) == 1


def test_settings_scrolls_in_a_window_shorter_than_the_panel():
    from scrcrappy.config import Config
    window = pygame.Window("phone", (300, 400))
    cfg, calls = Config(), []
    panel = __import__("scrcrappy.dialog", fromlist=["Settings"]).Settings(
        window, lambda size: pygame.Rect(10, 8, size[0], 200), cfg, on_change=lambda: None, on_natural=lambda: None,
        on_close=lambda: None, calibration=1.5, on_calibrate=lambda: calls.append(1))
    assert panel.hits["calibrate"].bottom > 200  # below the visible part
    for _ in range(20):
        panel.handle(pygame.event.Event(pygame.MOUSEWHEEL, window=window, x=0, y=-1))  # wheel down
    assert panel.scroll == panel.height - 200  # as far as there is something to show
    x, y = panel.hits["calibrate"].center
    panel.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, window=window,
                                    pos=(10 + x, 8 + y - panel.scroll)))
    assert calls == [1]
    screen = pygame.Surface((300, 400))
    panel.draw(screen, 352)  # draws the scrolled view without error


class FakeBoard:
    """The parts of links.Link the Settings board section reads."""

    def __init__(self, paired=True, peer=("3F:A2", "iPhone"), connected=True, last_seen=100.0):
        import threading
        self.paired, self.peer, self.last_seen = paired, peer, last_seen
        self.connected = threading.Event()
        if connected:
            self.connected.set()
        self.queries = self.forgets = 0

    def query(self):
        self.queries += 1

    def forget(self):
        self.forgets += 1


def test_board_status_rows():
    from scrcrappy.dialog import board_status
    assert board_status(FakeBoard(), 101) == ("green", "Connected to iPhone (…3F:A2)")
    assert board_status(FakeBoard(peer=("3F:A2", "")), 101) == ("green", "Connected (…3F:A2)")
    assert board_status(FakeBoard(peer=None), 101) == ("green", "Connected")
    assert board_status(FakeBoard(connected=False), 101) == ("grey", "Paired, not connected")
    assert board_status(FakeBoard(paired=False, peer=None, connected=False), 101) == ("blue", "Open to pairing")
    assert board_status(FakeBoard(paired=None, peer=None, connected=False), 101) == ("grey", "Reflash the board for status")
    assert board_status(FakeBoard(), 103) == ("grey", "Board not answering")  # 3 s of silence


def test_board_status_name_is_cleaned_and_truncated():
    from scrcrappy.dialog import board_status
    text = board_status(FakeBoard(peer=("3F:A2", "A\x07B" + "x" * 200)), 101)[1]
    assert "\x07" not in text and "…3F:A2" in text and len(text) < 60


def board_panel(mode="esp32", board=None):
    from scrcrappy.config import Config
    cfg = Config()
    cfg.mouse = mode
    return settings_panel(cfg, [], board=board)[0]


def test_board_section_follows_the_board_not_the_saved_mode():
    assert "forget" in board_panel(board=FakeBoard()).hits
    assert "forget" not in board_panel(board=None).hits
    assert "forget" in board_panel(mode="ble", board=FakeBoard()).hits  # launched with --mouse esp32, saved mode differs


def test_forget_needs_two_clicks_within_three_seconds(monkeypatch):
    from scrcrappy import dialog
    clock = [50.0]
    monkeypatch.setattr(dialog.time, "monotonic", lambda: clock[0])
    board = FakeBoard()
    panel = board_panel(board=board)
    click(panel, "forget")
    assert board.forgets == 0 and panel.confirming()
    clock[0] += 3.5  # too late: starts over
    assert not panel.confirming()
    click(panel, "forget")
    assert board.forgets == 0
    clock[0] += 1
    click(panel, "forget")
    assert board.forgets == 1 and not panel.confirming()


def test_tick_polls_once_a_second_only_while_open():
    board = FakeBoard()
    panel = board_panel(board=board)
    panel.tick(10.0)
    panel.tick(10.5)
    panel.tick(11.1)
    assert board.queries == 2
    panel.close()
    panel.tick(20.0)
    assert board.queries == 2


def test_tick_without_a_board_is_harmless():
    board_panel(board=None).tick(1.0)


def press(panel, key, kind=pygame.MOUSEBUTTONDOWN):
    x, y = panel.hits[key].center
    return panel.handle(pygame.event.Event(kind, button=1, pos=(x + panel.rect.x, y + panel.rect.y), window=panel.window))


def test_settings_press_one_button_release_on_another_does_not_click():
    calls = []
    panel, _ = settings_panel(__import__("scrcrappy.config", fromlist=["Config"]).Config(), [], on_calibrate=lambda: calls.append(1),
                              calibration=1.0)
    press(panel, "calibrate")
    assert panel.pressed == "calibrate"
    press(panel, "natural", pygame.MOUSEBUTTONUP)
    assert calls == [] and panel.pressed is None and not panel.closed


def test_settings_press_and_release_on_the_same_button_clicks():
    calls = []
    panel, _ = settings_panel(__import__("scrcrappy.config", fromlist=["Config"]).Config(), [], on_calibrate=lambda: calls.append(1),
                              calibration=1.0)
    press(panel, "calibrate")
    press(panel, "calibrate", pygame.MOUSEBUTTONUP)
    assert calls == [1] and panel.pressed is None


def test_menu_press_one_row_release_on_another_does_not_act():
    calls = []
    m, _ = menu_overlay(on_remove=lambda: calls.append("remove"), on_edit=lambda: calls.append("edit"))
    m.handle(menu_event(m, pygame.MOUSEBUTTONDOWN, "edit"))
    assert m.pressed == "edit"
    m.handle(menu_event(m, pygame.MOUSEBUTTONUP, "remove"))
    assert calls == [] and m.pressed is None


def test_menu_pressed_cleared_on_focus_loss():
    m, _ = menu_overlay()
    m.handle(menu_event(m, pygame.MOUSEBUTTONDOWN, "edit"))
    m.handle(pygame.event.Event(pygame.WINDOWFOCUSLOST, window=m.window))
    assert m.pressed is None


def test_board_status_silence_counts_from_when_settings_opened():
    from scrcrappy.dialog import board_status
    stale = FakeBoard(last_seen=10.0)
    assert board_status(stale, 100.0)[1] == "Board not answering"
    assert board_status(stale, 100.0, opened=99.5)[1] == "Connected to iPhone (…3F:A2)"  # the reply to our '?' is on its way


def test_board_status_long_name_keeps_the_id_visible():
    from scrcrappy.dialog import board_status
    board = FakeBoard(peer=("6F:BF", "Alessandro’s iPhone"))
    text = board_status(board, 101, fits=lambda t: len(t) <= 30)[1]
    assert len(text) <= 30 and text.endswith("(…6F:BF)") and "…" in text.split("(")[0]


def test_status_text_fits_the_panel_in_pixels():
    panel = board_panel(board=FakeBoard(peer=("6F:BF", "Alessandro’s iPhone with a very long name")))
    text = panel.board_text(panel.opened_at + 0.5)[1]
    assert panel.small.size(text)[0] <= PANEL_W - 2 * 16 - 18 and text.endswith("(…6F:BF)")


def test_status_holds_while_a_snapshot_is_arriving():
    panel = board_panel(board=FakeBoard(last_seen=50.0))
    now = panel.opened_at + 1
    panel.board.last_seen = now - 1
    first = panel.board_text(now)
    panel.board.paired, panel.board.peer = None, None  # the 'ready' of a new snapshot has just reset them
    panel.board.connected.clear()
    panel.board.last_seen = now - 0.01
    assert panel.board_text(now) == first
    assert panel.board_text(now + 0.5) != first  # a snapshot that never completes does show


def test_calibrate_is_disabled_without_a_bluetooth_connection():
    from scrcrappy.config import Config
    started = []
    panel, closed = settings_panel(Config(), [], calibration=1.5, on_calibrate=lambda: started.append(1),
                                   connected=lambda: False)
    click(panel, "calibrate")
    assert started == [] and not closed and not panel.closed
    panel.hover, panel.hover_since = "calibrate", 0.0
    assert "connect" in panel.tip(now=100.0).lower()


def test_calibrate_works_once_connected():
    from scrcrappy.config import Config
    state, started = [False], []
    panel, _ = settings_panel(Config(), [], calibration=1.5, on_calibrate=lambda: started.append(1),
                              connected=lambda: state[0])
    click(panel, "calibrate")
    state[0] = True
    click(panel, "calibrate")
    assert started == [1]
