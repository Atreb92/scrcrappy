def fit(frame: tuple[int, int], window: tuple[int, int]) -> tuple[int, int, int, int]:
    """Letterbox `frame` inside `window`: returns (x, y, w, h) of the drawn frame."""
    scale = min(window[0] / frame[0], window[1] / frame[1])
    w, h = round(frame[0] * scale), round(frame[1] * scale)
    return (window[0] - w) // 2, (window[1] - h) // 2, w, h


def to_frame(pos: tuple[int, int], rect: tuple[int, int, int, int], frame: tuple[int, int]) -> tuple[float, float]:
    """Window point -> frame pixel (may fall outside the frame for points in the letterbox)."""
    x, y, w, h = rect
    return (pos[0] - x) * frame[0] / w, (pos[1] - y) * frame[1] / h


def inside(pos: tuple[int, int], rect: tuple[int, int, int, int]) -> bool:
    x, y, w, h = rect
    return x <= pos[0] < x + w and y <= pos[1] < y + h


# UIInterfaceOrientation (ZXTouch orientation reply) -> clockwise rotation of the video frame vs portrait.
# ponytail: 3/4 (landscape right/left) not yet checked on the phone; swap them if landscape taps mirror.
ROTATION_BY_ORIENTATION = {1: 0, 2: 180, 3: 90, 4: 270}


def to_device(pos: tuple[int, int], rect: tuple[int, int, int, int], rotation: int,
              size: tuple[float, float]) -> tuple[float, float] | None:
    """Window point -> portrait phone coordinates in `size` units (ZXTouch's), or None outside the frame.
    `rotation` is how far the shown frame is turned clockwise from portrait."""
    if not inside(pos, rect):
        return None
    x, y, w, h = rect
    u, v = (pos[0] - x) / w, (pos[1] - y) / h  # 0..1 inside the shown frame
    px, py = {0: (u, v), 90: (v, 1 - u), 180: (1 - u, 1 - v), 270: (1 - v, u)}[rotation]
    return px * size[0], py * size[1]
