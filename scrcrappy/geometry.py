def fit(frame: tuple[int, int], window: tuple[int, int]) -> tuple[int, int, int, int]:
    """Letterbox `frame` inside `window`: returns (x, y, w, h) of the drawn frame."""
    scale = min(window[0] / frame[0], window[1] / frame[1])
    w, h = round(frame[0] * scale), round(frame[1] * scale)
    return (window[0] - w) // 2, (window[1] - h) // 2, w, h
