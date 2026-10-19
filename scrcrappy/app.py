import os
import sys
import time
from typing import Callable

import pygame

from .geometry import fit, inside, to_frame
from .keyqueue import KeyQueue
from .mouse import Pointer
from . import agent as agent_mod, config
from .config import Config, Custom
from .dialog import Dialog, DialogState, Menu, Popups, Settings
from .toolbar import GAP, ICONS, Pill, buttons, next_free
from .video import LatestFrame


MODIFIERS = range(0xE0, 0xE8)  # LCtrl..RGui; their bit in the report is usage - 0xE0
# SDL ignores the click that focuses a window by default: the toolbar would need two clicks
os.environ.setdefault("SDL_MOUSE_FOCUS_CLICKTHROUGH", "1")

CTRL, SHIFT, KEY_V = 0x11, 0x22, 0x19  # either side's modifier bits; V usage


class Controller:
    """Window events -> phone: cursor follows the mouse (left button = tap/drag), keys go to a
    BLE keyboard by physical position (SDL scancodes are USB HID usages)."""

    def __init__(self, pointer: Pointer, natural_scroll: bool = False, keys: KeyQueue | None = None) -> None:
        self.pointer, self.natural_scroll, self.held = pointer, natural_scroll, False
        self.keys, self.pressed = keys, []  # pressed: held non-modifier keys, oldest first
        self.modifiers = 0

    def _key(self, usage: int, down: bool) -> None:
        if usage in MODIFIERS:
            bit = 1 << (usage - 0xE0)
            self.modifiers = self.modifiers | bit if down else self.modifiers & ~bit
        elif down and usage not in self.pressed:
            self.pressed.append(usage)
        elif not down and usage in self.pressed:
            self.pressed.remove(usage)
        else:
            return
        self.keys.report(self.modifiers, self.pressed[:6])  # >6 keys: the extra ones wait (no rollover error)

    def stop(self) -> None:
        self.pointer.stop()

    def release_all(self) -> None:
        if self.keys and (self.pressed or self.modifiers):
            self.pressed, self.modifiers = [], 0
            self.keys.report(0, [])

    def paste(self) -> int:
        """Type the computer's clipboard into the phone; returns how many characters were skipped."""
        if not self.keys:
            return 0
        self.keys.report(0, [])  # let go of the modifiers held for the shortcut
        return self.keys.type_text(pygame.scrap.get_text() or "")

    def handle(self, event: pygame.event.Event, rect: tuple[int, int, int, int], frame: tuple[int, int]) -> None:
        p = self.pointer
        if event.type == pygame.MOUSEMOTION:
            p.move_to(*to_frame(event.pos, rect, frame))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and inside(event.pos, rect):
            p.move_to(*to_frame(event.pos, rect, frame))
            p.button(True)
            self.held = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.held:
            p.button(False)
            self.held = False
        elif event.type == pygame.MOUSEWHEEL:
            notches = -event.y if event.flipped else event.y  # undo the OS's own natural-scroll flip
            p.wheel(-notches if self.natural_scroll else notches)
        elif event.type == pygame.WINDOWENTER and not self.held:
            p.home()  # re-sync drift; the next motion event brings the cursor back under the mouse
        elif event.type in (pygame.WINDOWLEAVE, pygame.WINDOWFOCUSLOST) and self.held:
            p.button(False)  # never leave a finger down on the phone
            self.held = False
        if (event.type == pygame.KEYDOWN and self.keys and event.scancode == KEY_V
                and self.modifiers & CTRL and self.modifiers & SHIFT):
            self.paste()
        elif event.type in (pygame.KEYDOWN, pygame.KEYUP) and self.keys and 0 < event.scancode <= 0xE7:
            self._key(event.scancode, event.type == pygame.KEYDOWN)
        elif event.type == pygame.WINDOWFOCUSLOST:
            self.release_all()  # keys released elsewhere never reach us


def save_or_warn(save: Callable[[Config], None], cfg: Config) -> None:
    """Settings are saved after every toolbar change; a failed save must not end the session."""
    try:
        save(cfg)
    except OSError as e:
        print(f"warning: could not save settings: {e}", file=sys.stderr)


def run(frames: LatestFrame, alive: Callable[[], bool], make_pointer: Callable[[tuple[int, int]], Pointer] | None = None,
        keys: KeyQueue | None = None, cfg: Config | None = None, device_key: str = "", device_name: str = "scrcrappy PC",
        save: Callable[[Config], None] = config.save, title: str = "scrcrappy",
        agent: agent_mod.Session | None = None) -> bool:
    """Show frames until the window is closed (returns True) or `alive()` goes False (returns False).
    With `make_pointer`, the phone cursor follows the mouse (pointer is built once the frame size is known);
    with `agent`, clicks and keys go to scrcrappy-agent instead.
    Toolbar and Settings changes (custom buttons, natural scrolling, pinned, …) are written to `cfg` and saved at once."""
    pygame.init()
    main = pygame.Window(title, (375, 667), resizable=True)
    main.set_icon(pygame.image.load(ICONS / "scrcrappy.png"))  # rendered from icons/scrcrappy.svg
    pygame.key.stop_text_input()  # raw key events only, no IME
    clock = pygame.time.Clock()
    img, controller = None, None
    cfg = cfg or Config()
    if agent:
        controller = agent_mod.Controller(agent, cfg.natural_scroll)
        controller.screenshots = cfg.screenshots
        pygame.key.set_repeat(400, 33)  # agent keys are press+release: held keys repeat from here
    customs = cfg.customs.setdefault(device_key, [])
    popups = Popups()
    settings: Settings | None = None
    settings_closed_at = 0.0

    def items():
        return buttons(has_input=make_pointer is not None or agent is not None, customs=customs, agent=agent is not None, settings=bool(settings and not settings.closed))

    def changed() -> None:
        save_or_warn(save, cfg)
        pill.set_items(items())

    def paste() -> None:
        if controller and (skipped := controller.paste()):
            print(f"paste: skipped {skipped} characters (US layout, ASCII only)", file=sys.stderr)

    def toggle_natural() -> None:
        cfg.natural_scroll = not cfg.natural_scroll
        if controller:
            controller.natural_scroll = cfg.natural_scroll
        save_or_warn(save, cfg)

    def set_pinned(pinned: bool) -> None:
        cfg.pinned = pinned
        save_or_warn(save, cfg)

    def click(n: int) -> None:
        if controller:
            controller.pointer.click(1 << (n - 1))

    def edit(n: int | None = None) -> None:
        current = next((c for c in customs if c.button == n), None)
        button = n if current else next_free(customs)
        if button is None:
            return

        def done(result: Custom | None) -> None:
            if result:
                customs[:] = [c for c in customs if c.button != result.button] + [result]
                changed()

        popups.open(lambda: Dialog(DialogState(button, device_name, current), on_send=lambda: click(button), on_done=done))

    def menu(n: int) -> None:
        def remove() -> None:
            customs[:] = [c for c in customs if c.button != n]
            changed()

        rect = next(r for b, r in pill.rects if b.id == f"custom:{n}")
        px, py = pill.win.position
        popups.open(lambda: Menu((px + pill.win.size[0] + 4, py + rect.y), n, on_edit=lambda: edit(n), on_remove=remove))

    def place(size: tuple[int, int]) -> tuple[int, int]:
        """Beside the pill, away from the phone window, centred on the gear."""
        (px, py), (pw, _) = pill.win.position, pill.win.size
        x = px + pw + GAP if px > main.position[0] else px - GAP - size[0]
        gear = next((r for b, r in pill.rects if b.id == "settings"), None)
        y = py + (gear.centery if gear else 0) - size[1] // 2
        return x, max(0, min(y, pygame.display.get_desktop_sizes()[0][1] - size[1]))

    def settings_changed() -> None:
        save_or_warn(save, cfg)
        if agent and controller:
            controller.screenshots = cfg.screenshots

    def settings_done() -> None:
        nonlocal settings_closed_at
        settings_closed_at = time.monotonic()
        pill.set_items(items())

    def open_settings() -> None:
        nonlocal settings
        if settings and not settings.closed:
            settings.close()
        elif time.monotonic() - settings_closed_at > 0.5:  # else this click is what closed it (focus moved)
            settings = popups.open(lambda: Settings(cfg, place, settings_changed, toggle_natural, settings_done)) or settings
        pill.set_items(items())

    pill = Pill(main, items(), {
        "paste": paste,
        "copy": lambda: controller.copy(),
        "screenshot": lambda: controller.screenshot(),
        "home": lambda: controller.home(),
        "switcher": lambda: controller.switcher(),
        "lock": lambda: controller.lock(),
        "custom": click,
        "add": edit,
        "menu": menu,
        "settings": open_settings,
        "pinned": set_pinned,
    }, pinned=cfg.pinned)
    try:
        while alive():
            for event in pygame.event.get():
                if event.type == pygame.USEREVENT and hasattr(event, "run"):
                    event.run()  # an agent reply, handled on this thread
                    continue
                if popups.handle(event) or pill.handle(event):
                    continue
                if event.type == pygame.WINDOWCLOSE or event.type == pygame.QUIT:
                    return True
                if event.type in (pygame.WINDOWMOVED, pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
                    pill.follow()
                if controller and img:
                    controller.handle(event, fit(img.get_size(), main.size), img.get_size())
            if frame := frames.get():
                pixels, size, pitch = frame
                img = pygame.image.frombuffer(pixels, size, "RGB", pitch)
                if make_pointer and not controller:
                    pointer = make_pointer(size)
                    pointer.home()
                    pointer.start()
                    controller = Controller(pointer, cfg.natural_scroll, keys)
            screen = main.get_surface()
            screen.fill((0, 0, 0))
            if img:
                x, y, w, h = fit(img.get_size(), screen.get_size())
                screen.blit(pygame.transform.smoothscale(img, (w, h)), (x, y))
            main.flip()
            pill.update(app_focused=pill.focused() or popups.focused())
            pill.draw()
            if settings:
                settings.draw()
            clock.tick(60)
        return False
    finally:
        if controller:
            controller.release_all()
            controller.stop()
        pygame.quit()
