"""The toolbar: a button strip at the bottom of the phone window. Model and layout (pure), drawing and events (Bar)."""
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from .config import BUTTONS, ICON_CHOICES, Custom

PAD_Y, PAD_X = 8, 4
MAX_D = 40  # button diameter cap
BAR_H = 48
TIP_GAP = 6  # between a tooltip and the strip
NEEDS_INPUT = "Needs --mouse ble, esp32 or agent"
LED_TIP = "AI control: green = waiting, yellow = an AI is working, red = AI acting (your input is paused)"
COPY_TIP = "Needs --mouse agent (jailbreak)"  # a Bluetooth keyboard/mouse can't read the phone's clipboard


@dataclass
class Button:
    id: str
    icon: str  # Material Symbols codepoint
    tip: str
    enabled: bool = True
    toggled: bool | None = None  # None: not a toggle
    small: bool = False


def next_free(customs: list[Custom]) -> int | None:
    """Lowest mouse button not used by a custom button."""
    used = {c.button for c in customs}
    return next((n for n in BUTTONS if n not in used), None)


def buttons(has_input: bool, customs: list[Custom], agent: bool = False,
            settings: bool = False, led: bool = False) -> list[Button | None]:
    """The bar's items left to right; None is a separator. With the agent (jailbreak): copy, screenshot and the
    phone's buttons instead of the AssistiveTouch custom buttons."""
    def action(id_, icon, tip):
        return Button(id_, icon, tip if has_input else NEEDS_INPUT, enabled=has_input)

    paste = action("paste", "\ue14f", "Paste computer clipboard (Ctrl+Shift+V)")
    if agent:
        middle = [paste, Button("copy", "\ue14d", "Copy phone clipboard to the computer"),
                  Button("screenshot", "\uec08", "Save a screenshot"), None,
                  Button("home", "\ue9b2", "Home"), Button("switcher", "\ue8eb", "App switcher"),
                  Button("lock", "\uf8c7", "Lock")]
    else:
        labels = dict(ICON_CHOICES)
        add = [action("add", "\ue145", "Add a button…")] if next_free(customs) is not None else []  # gone when all used
        middle = [
            paste,
            Button("copy", "\ue14d", COPY_TIP, enabled=False),
            None,
            *(action(f"custom:{c.button}", c.icon,
                     f"{c.name or labels.get(c.icon, 'Custom')} (button {c.button}) · right-click to edit or remove")
              for c in sorted(customs, key=lambda c: c.button)),
            *add,
        ]
    status = [Button("led", "", LED_TIP, enabled=False, small=True)] if led else []  # AI control on
    return [
        *status,
        *middle,
        None,
        Button("settings", "\ue8b8", "Settings", toggled=settings),
    ]


def _sizes(items: list[Button | None], height: int) -> tuple[int, list[int]]:
    weights = [1 / 3 if b is None else 0.35 if b.small else 1 for b in items]
    d = int(min(MAX_D, (height - 2 * PAD_Y) / sum(weights)))
    return d, [max(1, round(w * d)) for w in weights]


def layout(items: list[Button | None], height: int) -> tuple[int, list[tuple[Button, pygame.Rect]]]:
    """Strip thickness and each button's rect for a strip `height` long, laid out top to bottom (hlayout turns it
    on its side); buttons shrink to fit, leftover space is spread evenly."""
    d, sizes = _sizes(items, height)
    width = d + 2 * PAD_X
    gap = max(0.0, (height - 2 * PAD_Y - sum(sizes)) / (len(items) + 1))
    y, rects = PAD_Y + gap, []
    for item, size in zip(items, sizes):
        if item is not None:
            rects.append((item, pygame.Rect((width - size) // 2, int(y), size, size)))
        y += size + gap
    return width, rects


# --- drawing ------------------------------------------------------------------------------------------

ICONS = Path(__file__).with_name("icons")
# iOS dark: the bar, the dialogs' windows and the Settings glass all draw from this palette
BG, FG, ON_BG, ON_FG, DISABLED, SEP = (28, 28, 30), (232, 232, 238), (76, 76, 82), (255, 255, 255), (110, 110, 118), (72, 72, 78)
EDGE = (62, 62, 66)  # hairline on top of the bar
HOVER = (255, 255, 255, 30)
TIP_BG, TIP_FG = (58, 58, 62), (242, 242, 247)
TIP_DELAY, TIP_WIDTH = 0.5, 220


def _wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and font.size(f"{line} {word}")[0] > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


def hlayout(items: list[Button | None], width: int) -> list[tuple[Button, pygame.Rect]]:
    """Each button's rect along a horizontal strip of `width` x BAR_H: `layout`, turned on its side."""
    cross, rects = layout(items, width)
    top = (BAR_H - cross) // 2
    return [(b, pygame.Rect(r.y, top + r.x, r.h, r.w)) for b, r in rects]


class Bar:
    """The buttons in a BAR_H strip at the bottom of the phone window; draw it onto the window's surface each
    frame, before flip. Tooltips pop up above it."""

    def __init__(self, main: pygame.Window, items: list[Button | None], actions: dict[str, Callable]) -> None:
        self.main, self.actions = main, actions
        self._fonts: dict[tuple[bool, int], pygame.font.Font] = {}  # per instance: fonts die with pygame.quit()
        self.hover: Button | None = None
        self.hover_since = 0.0
        self.tip_text: str | None = None
        self.led_colour: tuple[int, int, int] | None = None
        self.items: list[Button | None] = []
        self.rects: list[tuple[Button, pygame.Rect]] = []
        self.set_items(items)

    def icon_font(self, filled: bool, size: int) -> pygame.font.Font:
        if (filled, size) not in self._fonts:
            self._fonts[(filled, size)] = pygame.font.Font(
                ICONS / f"MaterialSymbolsRounded-{'filled' if filled else 'outline'}.ttf", size)
        return self._fonts[(filled, size)]

    @property
    def top(self) -> int:
        return self.main.size[1] - BAR_H

    def set_items(self, items: list[Button | None]) -> None:
        self.items = items
        self.hover, self.tip_text = None, None
        self.follow()

    def follow(self) -> None:
        self.rects = [(b, r.move(0, self.top)) for b, r in hlayout(self.items, self.main.size[0])]

    def focused(self) -> bool:
        return self.main.focused

    def _hit(self, pos: tuple[int, int]) -> Button | None:
        return next((b for b, r in self.rects if r.collidepoint(pos)), None)

    def handle(self, event: pygame.event.Event) -> bool:
        """Consume the mouse events that land on the strip; everything else goes on to the phone."""
        if event.type == pygame.WINDOWLEAVE and getattr(event, "window", None) is self.main:
            self.hover, self.tip_text = None, None
            return False
        if event.type not in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return False
        if getattr(event, "window", None) is not self.main or event.pos[1] < self.top:
            if event.type == pygame.MOUSEMOTION:
                self.hover, self.tip_text = None, None
            return False
        if event.type == pygame.MOUSEMOTION:
            hit = self._hit(event.pos)
            if hit is not self.hover:
                self.hover, self.hover_since, self.tip_text = hit, time.monotonic(), None
        elif event.type == pygame.MOUSEBUTTONUP and (hit := self._hit(event.pos)):
            if event.button == 1:
                self._click(hit)
            elif event.button == 3 and hit.id.startswith("custom:"):
                self.actions["menu"](int(hit.id[7:]))
        return True

    def _click(self, button: Button) -> None:
        if not button.enabled:
            return
        if button.toggled is not None:
            button.toggled = not button.toggled
        if button.id.startswith("custom:"):
            self.actions["custom"](int(button.id[7:]))
        else:
            self.actions[button.id]()

    def update(self, now: float | None = None, app_focused: bool | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.hover and self.tip_text is None and now - self.hover_since >= TIP_DELAY:
            b = self.hover
            self.tip_text = f"{b.tip}: {'on' if b.toggled else 'off'}" if b.toggled is not None and b.id != "settings" else b.tip

    def draw(self, surf: pygame.Surface) -> None:
        w = surf.get_width()
        pygame.draw.rect(surf, BG, (0, self.top, w, BAR_H))
        pygame.draw.line(surf, EDGE, (0, self.top), (w, self.top))
        for item, rect in self.rects:
            if item.id == "led":
                if self.led_colour:
                    pygame.draw.circle(surf, self.led_colour, rect.center, max(3, rect.width // 3))
                continue
            if item.toggled:
                pygame.draw.circle(surf, ON_BG, rect.center, rect.width // 2)
            if item is self.hover and item.enabled:
                overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
                pygame.draw.circle(overlay, HOVER, (rect.width // 2, rect.height // 2), rect.width // 2)
                surf.blit(overlay, rect)
            color = DISABLED if not item.enabled else ON_FG if item.toggled else FG
            glyph = self.icon_font(bool(item.toggled), max(8, int(rect.width * 0.6))).render(item.icon, True, color)
            surf.blit(glyph, glyph.get_rect(center=rect.center))
        for i, item in enumerate(self.items):  # separators between the neighbours
            if item is None:
                a = next(r for b, r in self.rects if b is self.items[i - 1])
                b = next(r for b, r in self.rects if b is self.items[i + 1])
                x = (a.right + b.left) // 2
                pygame.draw.line(surf, SEP, (x, self.top + BAR_H * 0.28), (x, self.top + BAR_H * 0.72))
        if self.tip_text and self.hover:
            self._draw_tip(surf)

    def _draw_tip(self, surf: pygame.Surface) -> None:
        font = self._tip_font = getattr(self, "_tip_font", None) or pygame.font.Font(None, 18)
        lines = _wrap(self.tip_text, font, min(TIP_WIDTH, surf.get_width() - 24) - 16)
        size = (16 + max(font.size(l)[0] for l in lines), 10 + 18 * len(lines))
        rect = next(r for b, r in self.rects if b is self.hover)
        x = min(max(6, rect.centerx - size[0] // 2), surf.get_width() - size[0] - 6)
        box = pygame.Rect(x, self.top - TIP_GAP - size[1], *size)
        pygame.draw.rect(surf, TIP_BG, box, border_radius=6)
        for i, line in enumerate(lines):
            surf.blit(font.render(line, True, TIP_FG), (box.x + 8, box.y + 5 + 18 * i))
