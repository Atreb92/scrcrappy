"""Floating button pill next to the phone window: model and layout (pure), drawing and window (Pill)."""
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

PILL_RATIO = 0.8  # of the phone window's height
GAP = 11  # between phone window and pill
PAD_Y, PAD_X = 8, 4
MAX_D = 40  # button diameter cap
TAB = (8, 48)  # collapsed pill
NEEDS_INPUT = "Needs --mouse ble or esp32"
COPY_TIP = "Needs jailbreak"  # a Bluetooth keyboard/mouse can't read the phone's clipboard


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
        action("paste", "\ue14f", "Paste computer clipboard (Ctrl+Shift+V)"),
        Button("copy", "\ue14d", COPY_TIP, enabled=False),
        None,
        action("home", "\ue9b2", "Home"),
        action("apps", "\ue8eb", "App switcher"),
        None,
        Button("natural", "\ue8d5", "Natural scrolling", toggled=natural),
        None,
        Button("collapse", "\ue5cb", "Collapse (shows again on hover)", small=True),
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


# --- the pill window ----------------------------------------------------------------------------

ICONS = Path(__file__).with_name("icons")
BG, FG, ON_BG, ON_FG, DISABLED, SEP = (0xDF, 0xE6, 0xF1), (0x3A, 0x46, 0x56), (0xB9, 0xCB, 0xE8), (0x0F, 0x2A, 0x4D), (0xA9, 0xB3, 0xC1), (0xC6, 0xCF, 0xDB)
HOVER = (0x3A, 0x46, 0x56, 26)  # FG at 10%
TIP_BG, TIP_FG = (0x30, 0x30, 0x34), (0xF2, 0xF0, 0xF4)
TIP_DELAY, TIP_WIDTH = 0.5, 220
AUTOHIDE = 3.0  # s after the mouse leaves a hover-opened pill
CHEVRON_COLLAPSE, CHEVRON_KEEP = "", ""


class Pill:
    """Borderless window beside the phone window holding the buttons. Pinned open by default;
    the chevron collapses it to a tab that opens while hovered (click the chevron again to pin)."""

    def __init__(self, main: pygame.Window, items: list[Button | None], actions: dict[str, Callable[[], None]]) -> None:
        self.main, self.items, self.actions = main, items, actions
        self.win = pygame.Window("scrcrappy tools", TAB, borderless=True, utility=True)
        self.tip_win: pygame.Window | None = None
        self.tip_text: str | None = None
        self.collapsed, self.pinned = False, True
        self.hover: Button | None = None
        self.hover_since = 0.0
        self.leave_at: float | None = None  # when the mouse left a hover-opened pill
        self.rects: list[tuple[Button, pygame.Rect]] = []
        self._fonts: dict[tuple[str, int], pygame.font.Font] = {}
        self.follow()

    def font(self, filled: bool, size: int) -> pygame.font.Font:
        key = ("filled" if filled else "outline", size)
        if key not in self._fonts:
            self._fonts[key] = pygame.font.Font(ICONS / f"MaterialSymbolsRounded-{key[0]}.ttf", size)
        return self._fonts[key]

    def follow(self) -> None:
        """Re-place next to the phone window (call after it moved, resized or was restored)."""
        desktop = pygame.display.get_desktop_sizes()[0]
        x, y, w, h = pill_rect(self.main.position, self.main.size, desktop, self.items)
        if self.collapsed:
            mx, my = self.main.position
            self.win.size = TAB
            self.win.position = (x if x > mx else mx - GAP - TAB[0], my + (self.main.size[1] - TAB[1]) // 2)
            self.rects = []
        else:
            self.win.size, self.win.position = (w, h), (x, y)
            self.rects = layout(self.items, h)[1]
        self._show_tip(None)

    def _set_collapsed(self, collapsed: bool) -> None:
        if collapsed != self.collapsed:
            self.collapsed, self.hover = collapsed, None
            self.follow()

    def handle(self, event: pygame.event.Event) -> bool:
        """Consume events meant for the pill; returns False for everything else."""
        if getattr(event, "window", None) not in (self.win, self.tip_win) or self.win is None:
            return False
        if event.type == pygame.WINDOWENTER:
            self.leave_at = None
            self._set_collapsed(False)
        elif event.type == pygame.WINDOWLEAVE:
            self.hover = None
            self._show_tip(None)
            if not self.pinned:
                self.leave_at = time.monotonic()
        elif event.type == pygame.MOUSEMOTION:
            hit = self._hit(event.pos)
            if hit is not self.hover:
                self.hover, self.hover_since = hit, time.monotonic()
                self._show_tip(None)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and (hit := self._hit(event.pos)):
            self._click(hit)
        return True

    def _hit(self, pos: tuple[int, int]) -> Button | None:
        return next((b for b, r in self.rects if r.collidepoint(pos)), None)

    def _click(self, button: Button) -> None:
        if not button.enabled:
            return
        if button.id == "collapse":
            if self.pinned:
                self.pinned = False
                self._set_collapsed(True)
            else:
                self.pinned, self.leave_at = True, None
        else:
            if button.toggled is not None:
                button.toggled = not button.toggled
            self.actions[button.id]()
        self.main.focus()  # keep typing going to the phone

    def update(self, now: float | None = None) -> None:
        """Tooltip and auto-hide timing; call once per frame."""
        now = time.monotonic() if now is None else now
        if self.leave_at is not None and now - self.leave_at >= AUTOHIDE:
            self.leave_at = None
            self._set_collapsed(True)
        if self.hover and self.tip_text is None and now - self.hover_since >= TIP_DELAY:
            self._show_tip(self._tip_for(self.hover))

    def _tip_for(self, button: Button) -> str:
        if button.id == "collapse":
            return "Collapse (shows again on hover)" if self.pinned else "Keep open"
        if button.toggled is not None:
            return f"{button.tip}: {'on' if button.toggled else 'off'}"
        return button.tip

    def _show_tip(self, text: str | None) -> None:
        self.tip_text = text
        if text is None:
            if self.tip_win:
                self.tip_win.hide()
            return
        lines = _wrap(text, pygame.font.Font(None, 18), TIP_WIDTH - 16)
        font = pygame.font.Font(None, 18)
        size = (min(TIP_WIDTH, 16 + max(font.size(l)[0] for l in lines)), 10 + 18 * len(lines))
        rect = next(r for b, r in self.rects if b is self.hover)
        px, py = self.win.position
        right = px > self.main.position[0]
        x = px + self.win.size[0] + GAP if right else px - GAP - size[0]
        if self.tip_win is None:
            self.tip_win = pygame.Window("scrcrappy tip", size, borderless=True, utility=True)
        self.tip_win.size, self.tip_win.position = size, (x, py + rect.centery - size[1] // 2)
        surf = self.tip_win.get_surface()
        surf.fill(TIP_BG)
        for i, line in enumerate(lines):
            surf.blit(font.render(line, True, TIP_FG), (8, 5 + 18 * i))
        self.tip_win.show()
        self.tip_win.flip()

    def draw(self) -> None:
        surf = self.win.get_surface()
        surf.fill(BG)
        if not self.collapsed:
            for item, rect in self.rects:
                filled = bool(item.toggled)
                if item.id == "collapse" and not self.pinned:
                    icon = CHEVRON_KEEP
                else:
                    icon = item.icon
                if item.toggled:
                    pygame.draw.circle(surf, ON_BG, rect.center, rect.width // 2)
                if item is self.hover and item.enabled:
                    overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
                    pygame.draw.circle(overlay, HOVER, (rect.width // 2, rect.height // 2), rect.width // 2)
                    surf.blit(overlay, rect)
                color = DISABLED if not item.enabled else ON_FG if item.toggled else FG
                glyph = self.font(filled, max(8, int(rect.width * 0.6))).render(icon, True, color)
                surf.blit(glyph, glyph.get_rect(center=rect.center))
            for i, item in enumerate(self.items):  # separators: thin line between the neighbours
                if item is None:
                    above = next(r for b, r in self.rects if b is self.items[i - 1])
                    below = next(r for b, r in self.rects if b is self.items[i + 1])
                    y = (above.bottom + below.top) // 2
                    w = int(self.rects[0][1].width * 0.55)
                    pygame.draw.line(surf, SEP, ((surf.get_width() - w) // 2, y), ((surf.get_width() + w) // 2, y))
        self.win.flip()

    def hide(self) -> None:
        self.win.hide()
        self._show_tip(None)

    def show(self) -> None:
        self.win.show()
        self.follow()


def _wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and font.size(f"{line} {word}")[0] > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]
