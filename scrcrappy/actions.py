"""What AI control does, shared by `scrcrappy agent` and the MCP server: coordinates in percent of the
upright screenshot, touch step lists, how to type, and screenshots ready to hand out."""
import io

import pygame

from . import geometry
from .typing_us import keystrokes
from .video import Frame

ORIENTATIONS = {1: "portrait", 2: "portrait-upside-down", 3: "landscape-right", 4: "landscape-left"}
CAP = 1568  # long edge: AI clients shrink larger images anyway
TAP_S, LONG_PRESS_MS, SWIPE_MS, MOVE_S = 0.08, 1000, 300, 0.016

Step = tuple[float, str, float, float]  # seconds to wait first, phase, x %, y %


def _numbers(text: str, counts: tuple[int, ...], what: str) -> list[float]:
    try:
        values = [float(v) for v in text.split(",")]
    except ValueError:
        values = []
    if len(values) not in counts:
        raise ValueError(f"expected {what}, got {text!r}")
    coords = values[:counts[0]]
    if not all(0 <= v <= 100 for v in coords):
        raise ValueError(f"coordinates are percent of the screenshot, 0-100: {text!r}")
    if len(values) > counts[0] and values[-1] <= 0:
        raise ValueError(f"duration must be positive milliseconds: {text!r}")
    return values


def parse_point(text: str) -> tuple[float, float, float | None]:
    """"x,y" or "x,y,ms" (percent, percent, optional duration)."""
    v = _numbers(text, (2, 3), "x,y or x,y,ms")
    return v[0], v[1], v[2] if len(v) == 3 else None


def parse_points(text: str) -> tuple[float, float, float, float, float | None]:
    """"x1,y1,x2,y2" or with ",ms"."""
    v = _numbers(text, (4, 5), "x1,y1,x2,y2 or x1,y1,x2,y2,ms")
    return v[0], v[1], v[2], v[3], v[4] if len(v) == 5 else None


def to_portrait(x: float, y: float, orientation: int) -> tuple[float, float]:
    """Percent of the upright screenshot -> the agent's portrait fractions."""
    return geometry.to_portrait(x / 100, y / 100, geometry.ROTATION_BY_ORIENTATION.get(orientation, 0))


def tap(x: float, y: float) -> list[Step]:
    return [(0, "down", x, y), (TAP_S, "up", x, y)]


def long_press(x: float, y: float, ms: float | None = None) -> list[Step]:
    return [(0, "down", x, y), ((ms or LONG_PRESS_MS) / 1000, "up", x, y)]


def swipe(x1: float, y1: float, x2: float, y2: float, ms: float | None = None) -> list[Step]:
    seconds = (ms or SWIPE_MS) / 1000
    n = max(1, round(seconds / MOVE_S))
    moves = [(seconds / n, "move", x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(1, n + 1)]
    return [(0, "down", x1, y1), *moves, (0, "up", x2, y2)]


def typing_plan(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Keys when a US layout types all of it (no prompt, clipboard untouched), else paste the whole text."""
    strokes, skipped = keystrokes(text)
    return ("keys", strokes) if not skipped else ("paste", [])


def _png(surf: pygame.Surface, cap: int) -> tuple[bytes, int, int]:
    w, h = surf.get_size()
    if max(w, h) > cap:
        k = cap / max(w, h)
        surf = pygame.transform.smoothscale(surf, (round(w * k), round(h * k)))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "screen.png")
    return buf.getvalue(), *surf.get_size()


def upright_png(png: bytes, orientation: int, cap: int = CAP) -> tuple[bytes, int, int]:
    """The agent's portrait-panel PNG turned the way the app shows, capped to `cap` px."""
    img = pygame.image.load(io.BytesIO(png), "screen.png")
    return _png(pygame.transform.rotate(img, -geometry.ROTATION_BY_ORIENTATION.get(orientation, 0)), cap)


def frame_png(frame: Frame, cap: int = CAP) -> tuple[bytes, int, int]:
    """A video frame (already upright) as PNG, capped to `cap` px."""
    pixels, size, pitch = frame
    return _png(pygame.image.frombuffer(pixels, size, "RGB", pitch), cap)
