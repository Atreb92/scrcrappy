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
