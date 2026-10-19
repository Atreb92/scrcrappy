"""Floating button pill next to the phone window: model and layout (pure), drawing and window (Pill)."""
from dataclasses import dataclass

import pygame

PILL_RATIO = 0.8  # of the phone window's height
GAP = 6  # between phone window and pill
PAD_Y, PAD_X = 8, 4
MAX_D = 40  # button diameter cap
TAB = (8, 48)  # collapsed pill
NEEDS_INPUT = "Needs --mouse ble or esp32"
COPY_TIP = "Copy to computer needs the jailbreak backend: a Bluetooth keyboard/mouse can't read the phone's clipboard."


@dataclass
class Button:
    id: str
    icon: str  # Material Symbols codepoint
    tip: str
    enabled: bool = True
    toggled: bool | None = None  # None: not a toggle
    small: bool = False


def buttons(has_input: bool, natural: bool) -> list[Button | None]:
    """The pill's items top to bottom; None is a separator."""
    def action(id_, icon, tip):
        return Button(id_, icon, tip if has_input else NEEDS_INPUT, enabled=has_input)

    return [
        action("paste", "", "Paste computer clipboard (Ctrl+Shift+V)"),
        Button("copy", "", COPY_TIP, enabled=False),
        None,
        action("home", "", "Home"),
        action("apps", "", "App switcher"),
        None,
        Button("natural", "", "Natural scrolling", toggled=natural),
        None,
        Button("collapse", "", "Collapse (shows again on hover)", small=True),
    ]


def _sizes(items: list[Button | None], height: int) -> tuple[int, list[int]]:
    weights = [1 / 3 if b is None else 0.6 if b.small else 1 for b in items]
    d = int(min(MAX_D, (height - 2 * PAD_Y) / sum(weights)))
    return d, [max(1, round(w * d)) for w in weights]


def layout(items: list[Button | None], height: int) -> tuple[int, list[tuple[Button, pygame.Rect]]]:
    """Pill width and each button's rect; buttons shrink to fit, leftover space is spread evenly."""
    d, sizes = _sizes(items, height)
    width = d + 2 * PAD_X
    gap = max(0.0, (height - 2 * PAD_Y - sum(sizes)) / (len(items) + 1))
    y, rects = PAD_Y + gap, []
    for item, size in zip(items, sizes):
        if item is not None:
            rects.append((item, pygame.Rect((width - size) // 2, int(y), size, size)))
        y += size + gap
    return width, rects


def pill_rect(main_pos: tuple[int, int], main_size: tuple[int, int], desktop_size: tuple[int, int],
              items: list[Button | None]) -> tuple[int, int, int, int]:
    """Where the pill window goes: right of the phone window (left if no room), 80% tall, centred."""
    (mx, my), (mw, mh) = main_pos, main_size
    h = round(PILL_RATIO * mh)
    w = layout(items, h)[0]
    x = mx + mw + GAP
    if x + w > desktop_size[0]:
        x = mx - GAP - w
    return x, my + (mh - h) // 2, w, h
