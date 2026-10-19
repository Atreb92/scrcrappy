from typing import Callable

import pygame

from .geometry import fit, inside, to_frame
from .mouse import Pointer
from .video import LatestFrame


class Controller:
    """Window mouse events -> phone pointer (cursor follows the mouse, left button = tap/drag)."""

    def __init__(self, pointer: Pointer) -> None:
        self.pointer, self.held = pointer, False

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
            p.wheel(event.y)
        elif event.type == pygame.WINDOWENTER and not self.held:
            p.home()  # re-sync drift; the next motion event brings the cursor back under the mouse
        elif event.type in (pygame.WINDOWLEAVE, pygame.WINDOWFOCUSLOST) and self.held:
            p.button(False)  # never leave a finger down on the phone
            self.held = False


def run(frames: LatestFrame, alive: Callable[[], bool], make_pointer: Callable[[tuple[int, int]], Pointer] | None = None,
        title: str = "scrcrappy") -> bool:
    """Show frames until the window is closed (returns True) or `alive()` goes False (returns False).
    With `make_pointer`, the phone cursor follows the mouse (pointer is built once the frame size is known)."""
    pygame.init()
    screen = pygame.display.set_mode((375, 667), pygame.RESIZABLE)
    pygame.display.set_caption(title)
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
                    controller = Controller(pointer)
            screen.fill((0, 0, 0))
            if img:
                x, y, w, h = fit(img.get_size(), screen.get_size())
                screen.blit(pygame.transform.smoothscale(img, (w, h)), (x, y))
            pygame.display.flip()
            clock.tick(60)
        return False
    finally:
        if controller:
            controller.pointer.stop()
        pygame.quit()
