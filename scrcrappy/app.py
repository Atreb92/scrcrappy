import os
import sys
import threading
import time
from typing import Callable

import pygame

from .geometry import fit, inside, to_frame
from .keyqueue import KeyQueue
from .mouse import Pointer
from . import agent as agent_mod, ai as ai_mod, config
from .calibrate import Calibrator
from .config import Config, Custom
from .dialog import PANEL_W, Dialog, DialogState, Menu, Popups, Settings
from .toolbar import BAR_H, ICONS, Bar, buttons, next_free
from .video import LatestFrame


PANEL_MARGIN = 8  # between the Settings panel and the strip / the window's top
CALIBRATE_WAIT_S = 120  # the AI's calibrate tool gives up waiting (a run takes well under a minute)
MODIFIERS = range(0xE0, 0xE8)  # LCtrl..RGui; their bit in the report is usage - 0xE0
# SDL ignores the click that focuses a window by default: the toolbar would need two clicks
os.environ.setdefault("SDL_MOUSE_FOCUS_CLICKTHROUGH", "1")

CTRL, SHIFT, KEY_V = 0x11, 0x22, 0x19  # either side's modifier bits; V usage
INPUT = (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL,
         pygame.KEYDOWN, pygame.KEYUP)


def paused(event: pygame.event.Event, locked: bool) -> bool:
    """While an AI action runs, the user's mouse and keyboard reach nothing (phone window or toolbar)."""
    return locked and event.type in INPUT


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

    def release(self) -> None:
        """Let go of everything (AI control takes over): button and keys."""
        if self.held:
            self.pointer.button(False)
            self.held = False
        self.release_all()

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
        agent: agent_mod.Session | None = None, calibrator: Calibrator | None = None, mcp: bool = False) -> bool:
    """Show frames until the window is closed (returns True) or `alive()` goes False (returns False).
    With `make_pointer`, the phone cursor follows the mouse (pointer is built once the frame size is known);
    with `agent`, clicks and keys go to scrcrappy-agent instead. `calibrator` adds Calibrate to Settings.
    Toolbar and Settings changes (custom buttons, natural scrolling, …) are written to `cfg` and saved at once."""
    pygame.init()
    main = pygame.Window(title, (375, 667 + BAR_H), resizable=True)  # the phone image above the toolbar strip
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
    calibrating = False
    ai = ai_mod.AiControl(frames, session=agent, keys=keys,
                          pointer=(lambda: controller.pointer if controller else None) if make_pointer else None,
                          calibrate=(lambda: ai_calibrate()) if calibrator else None)
    was_locked = False

    def items():
        return buttons(has_input=make_pointer is not None or agent is not None, customs=customs, agent=agent is not None,
                       settings=bool(settings and not settings.closed), led=ai.server is not None)

    def toggle_ai() -> None:
        cfg.ai_control = not cfg.ai_control
        if cfg.ai_control:
            ai.enable(cfg)
        else:
            ai.disable()
        if ai.error:
            print(f"AI control: {ai.error}", file=sys.stderr)
        save_or_warn(save, cfg)
        bar.set_items(items())

    def ai_status() -> str:
        return ai.error or (f"Listening on http://127.0.0.1:{ai_mod.PORT}/mcp (this computer only). Copy the "
                            "MCP config and add it to your AI client.")

    def copy_ai_config() -> None:
        pygame.scrap.put_text(ai.client_config(cfg))
        print("AI control: MCP config copied to the clipboard", file=sys.stderr)

    def changed() -> None:
        save_or_warn(save, cfg)
        bar.set_items(items())

    def paste() -> None:
        if controller and (skipped := controller.paste()):
            print(f"paste: skipped {skipped} characters (US layout, ASCII only)", file=sys.stderr)

    def toggle_natural() -> None:
        cfg.natural_scroll = not cfg.natural_scroll
        if controller:
            controller.natural_scroll = cfg.natural_scroll
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

        rect = next(r for b, r in bar.rects if b.id == f"custom:{n}")
        mx, my = main.position
        where = (mx + rect.x, my + bar.top - 120)  # just above the strip (a window of its own for now)
        popups.open(lambda: Menu(where, n, on_edit=lambda: edit(n), on_remove=remove))

    def settings_rect(size: tuple[int, int]) -> pygame.Rect:
        """The Settings panel: centred above the strip, clipped to the room there is."""
        room = max(0, bar.top - 2 * PANEL_MARGIN)
        return pygame.Rect((main.size[0] - size[0]) // 2, bar.top - PANEL_MARGIN - min(size[1], room), size[0], min(size[1], room))

    def settings_changed() -> None:
        save_or_warn(save, cfg)
        if agent and controller:
            controller.screenshots = cfg.screenshots

    def settings_done() -> None:
        bar.set_items(items())

    def calibrate(on_done: Callable[[str | None], None] | None = None) -> None:
        """Settings › Calibrate: the pointer stops while the calibrator drives the cursor, then is rebuilt
        (on the next frame) with the new table. `on_done(error)` runs on this thread when it ends."""
        nonlocal controller, calibrating
        if calibrating:
            return on_done and on_done("already calibrating")
        if controller:
            controller.release_all()
            controller.stop()
        controller, calibrating = None, True
        main.title = f"{title} — calibrating, don't touch the mouse…"

        def work() -> None:
            try:
                calibrator.run()
                error = None
            except RuntimeError as e:
                error = str(e)
            pygame.event.post(pygame.event.Event(pygame.USEREVENT, run=lambda: calibrated(error, on_done)))

        threading.Thread(target=work, daemon=True).start()

    def calibrated(error: str | None, on_done: Callable[[str | None], None] | None) -> None:
        nonlocal calibrating
        calibrating = False
        main.title = f"{title} — calibration failed, see the terminal" if error else title
        if error:
            print(f"calibration failed: {error}", file=sys.stderr)
        if on_done:
            on_done(error)

    def ai_calibrate() -> str:
        """The AI's calibrate tool (MCP thread): run calibrate() on the window's thread and wait for it."""
        done, result = threading.Event(), []
        pygame.event.post(pygame.event.Event(
            pygame.USEREVENT, run=lambda: calibrate(lambda error: (result.append(error), done.set()))))
        if not done.wait(CALIBRATE_WAIT_S):
            raise RuntimeError("calibration is taking too long; check the window")
        if result[0]:
            raise RuntimeError(result[0])
        return f"calibrated: {calibrator.value():.2f} screen px per count for a 12-count report"

    def open_settings() -> None:
        nonlocal settings
        if settings and not settings.closed:
            settings.close()
        else:
            settings = Settings(main, settings_rect, cfg, settings_changed, toggle_natural, settings_done,
                                calibrator.value() if calibrator else None, calibrate, toggle_ai, ai_status, copy_ai_config)
        bar.set_items(items())

    bar = Bar(main, items(), {
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
    })
    if cfg.ai_control or mcp:  # --mcp: on for this run only, cfg.ai_control (what's saved) stays as it is
        had_token = bool(cfg.mcp_token)
        ai.enable(cfg)
        if not had_token:
            save_or_warn(save, cfg)
        if ai.error:
            print(f"AI control: {ai.error}", file=sys.stderr)
        bar.set_items(items())
    try:
        while alive():
            for event in pygame.event.get():
                if event.type == pygame.USEREVENT and hasattr(event, "run"):
                    event.run()  # an agent reply, handled on this thread
                    continue
                if paused(event, ai.locked()):  # checked per event: the lock starts the moment a tool does
                    continue
                if (settings and settings.handle(event)) or popups.handle(event) or bar.handle(event):
                    continue
                if event.type == pygame.WINDOWCLOSE or event.type == pygame.QUIT:
                    return True
                if event.type in (pygame.WINDOWMOVED, pygame.WINDOWRESIZED, pygame.WINDOWSIZECHANGED):
                    bar.follow()
                if popups.is_open() and event.type in INPUT[:4]:
                    continue  # a dialog or menu is up: the mouse over the phone window doesn't steer the phone cursor
                if controller and img:
                    controller.handle(event, fit(img.get_size(), (main.size[0], bar.top)), img.get_size())
            if frame := frames.get():
                pixels, size, pitch = frame
                img = pygame.image.frombuffer(pixels, size, "RGB", pitch)
                if make_pointer and not controller and not calibrating:
                    pointer = make_pointer(size)
                    pointer.home()
                    pointer.start()
                    controller = Controller(pointer, cfg.natural_scroll, keys)
            if ai.locked() != was_locked:
                was_locked = not was_locked
                if was_locked and controller:
                    controller.release()  # nothing of the user's stays pressed while the AI acts
            screen = main.get_surface()
            screen.fill((0, 0, 0))
            if img:
                x, y, w, h = fit(img.get_size(), (screen.get_width(), bar.top))
                screen.blit(pygame.transform.smoothscale(img, (w, h)), (x, y))
                now = time.monotonic()
                for rx, ry, t in ai.current_rings(now):  # where the AI touched
                    pygame.draw.circle(screen, ai_mod.RED, (x + rx / 100 * w, y + ry / 100 * h),
                                       10 + (now - t) * 40, 3)
            bar.led_colour = ai.led()
            bar.update()
            if settings:
                settings.draw(screen, bar.top)
            bar.draw(screen)
            main.flip()
            clock.tick(60)
        return False
    finally:
        ai.disable()
        if controller:
            controller.release_all()
            controller.stop()
        pygame.quit()
