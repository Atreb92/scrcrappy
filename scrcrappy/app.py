from typing import Callable

import pygame

from .geometry import fit
from .video import LatestFrame


def run(frames: LatestFrame, alive: Callable[[], bool], title: str = "scrcrappy") -> bool:
    """Show frames until the window is closed (returns True) or `alive()` goes False (returns False)."""
    pygame.init()
    screen = pygame.display.set_mode((375, 667), pygame.RESIZABLE)
    pygame.display.set_caption(title)
    clock = pygame.time.Clock()
    img = None
    try:
        while alive():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return True
            if frame := frames.get():
                pixels, size, pitch = frame
                img = pygame.image.frombuffer(pixels, size, "RGB", pitch)
            screen.fill((0, 0, 0))
            if img:
                x, y, w, h = fit(img.get_size(), screen.get_size())
                screen.blit(pygame.transform.smoothscale(img, (w, h)), (x, y))
            pygame.display.flip()
            clock.tick(60)
        return False
    finally:
        pygame.quit()
