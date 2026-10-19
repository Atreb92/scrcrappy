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


# UIInterfaceOrientation (agent `screen` reply) -> clockwise rotation of the upright app vs the portrait panel.
# 3 = Home button on the right: the agent's screenshots need 90° counter-clockwise to be upright (seen on the
# iPhone 8). ponytail: taps in landscape not yet checked on the phone; swap 3/4 if they land mirrored.
ROTATION_BY_ORIENTATION = {1: 0, 2: 180, 3: 270, 4: 90}


def rotation(orientation: int, frame: tuple[int, int]) -> int:
    """How far the shown video frame is turned from portrait. The video turns with the app; while the frame's
    shape doesn't match the orientation (stream hasn't turned yet, or the reply is stale) treat it as portrait."""
    r = ROTATION_BY_ORIENTATION.get(orientation, 0)
    return r if (r in (90, 270)) == (frame[0] > frame[1]) else 0


def to_device(pos: tuple[int, int], rect: tuple[int, int, int, int], rotation: int,
              size: tuple[float, float]) -> tuple[float, float] | None:
    """Window point -> portrait phone coordinates in `size` units ((1, 1): fractions), or None outside the frame.
    `rotation` is how far the shown frame is turned clockwise from portrait."""
    if not inside(pos, rect):
        return None
    x, y, w, h = rect
    u, v = (pos[0] - x) / w, (pos[1] - y) / h  # 0..1 inside the shown frame
    px, py = {0: (u, v), 90: (v, 1 - u), 180: (1 - u, 1 - v), 270: (1 - v, u)}[rotation]
    return px * size[0], py * size[1]
