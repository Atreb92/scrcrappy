from typing import Callable

import pygame

from .geometry import fit, inside, to_frame
from .mouse import Pointer
from .video import LatestFrame


Keys = Callable[[int, list[int]], None]  # modifier bits, held key usages
MODIFIERS = range(0xE0, 0xE8)  # LCtrl..RGui; their bit in the report is usage - 0xE0


class Controller:
    """Window events -> phone: cursor follows the mouse (left button = tap/drag), keys go to a
    BLE keyboard by physical position (SDL scancodes are USB HID usages)."""

    def __init__(self, pointer: Pointer, natural_scroll: bool = False, keys: Keys | None = None) -> None:
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
        self.keys(self.modifiers, self.pressed[:6])  # >6 keys: the extra ones wait (no rollover error)

    def release_all(self) -> None:
        if self.keys and (self.pressed or self.modifiers):
            self.pressed, self.modifiers = [], 0
            self.keys(0, [])

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
        if event.type in (pygame.KEYDOWN, pygame.KEYUP) and self.keys and 0 < event.scancode <= 0xE7:
            self._key(event.scancode, event.type == pygame.KEYDOWN)
        elif event.type == pygame.WINDOWFOCUSLOST:
            self.release_all()  # keys released elsewhere never reach us


def run(frames: LatestFrame, alive: Callable[[], bool], make_pointer: Callable[[tuple[int, int]], Pointer] | None = None,
        natural_scroll: bool = False, keys: Keys | None = None, title: str = "scrcrappy") -> bool:
    """Show frames until the window is closed (returns True) or `alive()` goes False (returns False).
    With `make_pointer`, the phone cursor follows the mouse (pointer is built once the frame size is known)."""
    pygame.init()
    screen = pygame.display.set_mode((375, 667), pygame.RESIZABLE)
    pygame.display.set_caption(title)
    pygame.key.stop_text_input()  # raw key events only, no IME
    clock = pygame.time.Clock()
    img, controller = None, None
    try:
        while alive():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return True
                if controller and img:
                    controller.handle(event, fit(img.get_size(), screen.get_size()), img.get_size())
            if frame := frames.get():
                pixels, size, pitch = frame
                img = pygame.image.frombuffer(pixels, size, "RGB", pitch)
                if make_pointer and not controller:
                    pointer = make_pointer(size)
                    pointer.home()
                    pointer.start()
                    controller = Controller(pointer, natural_scroll, keys)
            screen.fill((0, 0, 0))
            if img:
                x, y, w, h = fit(img.get_size(), screen.get_size())
                screen.blit(pygame.transform.smoothscale(img, (w, h)), (x, y))
            pygame.display.flip()
            clock.tick(60)
        return False
    finally:
        if controller:
            controller.release_all()
            controller.pointer.stop()
        pygame.quit()
