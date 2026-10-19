"""Small windows opened from the toolbar: add/edit a custom button, and its right-click menu."""
from typing import Callable

import pygame

from .config import ICON_CHOICES, Custom
from .toolbar import DISABLED, FG, ICONS, ON_BG, ON_FG, SEP

SURFACE, TEXT, MUTED, ACCENT = (0xF4, 0xF7, 0xFB), (0x1D, 0x25, 0x30), (0x6B, 0x75, 0x84), (0x2F, 0x5E, 0xA8)
COLS, CELL, PAD, WIDTH = 8, 44, 16, 400


class DialogState:
    """What the Add/Edit window edits: icon, name and the binding instructions for one mouse button."""

    def __init__(self, button: int, device: str, custom: Custom | None = None) -> None:
        self.button, self.device = button, device
        self.icon = custom.icon if custom else ICON_CHOICES[0][0]
        self.name = custom.name if custom else ""
        self.title = "Edit button" if custom else "Add button"

    def select(self, i: int) -> None:
        self.icon = ICON_CHOICES[i][0]

    def type(self, text: str) -> None:
        self.name = (self.name + text)[:30]

    def backspace(self) -> None:
        self.name = self.name[:-1]

    def result(self) -> Custom:
        return Custom(self.button, self.icon, self.name.strip())

    def steps(self) -> list[str]:
        n, label = self.button, dict(ICON_CHOICES)[self.icon]
        return [
            f"On the iPhone open Settings › Accessibility › Touch › AssistiveTouch › Devices › {self.device} "
            "and tap Customise Additional Buttons…",
            f"When the phone says “Press a button on your pointer device”, click Send button {n} here.",
            f"Pick the action (e.g. {label}). If the phone shows a new Button {n} row set to Secondary Click "
            "instead, tap that row and pick the action there.",
        ]


def _wrap(text: str, font: pygame.font.Font, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and font.size(f"{line} {word}")[0] > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


class Dialog:
    """The Add/Edit button window. `on_send` clicks the button on the phone (for iOS's binding step);
    `on_done` gets the result, or None when cancelled."""

    def __init__(self, state: DialogState, on_send: Callable[[], None], on_done: Callable[[Custom | None], None]) -> None:
        self.state, self.on_send, self.on_done = state, on_send, on_done
        self.font = pygame.font.Font(None, 20)
        self.small = pygame.font.Font(None, 18)
        self.icons = pygame.font.Font(ICONS / "MaterialSymbolsRounded-outline.ttf", 22)
        self.closed = False
        self.hits: dict[str, pygame.Rect] = {}
        self._layout()
        self.win = pygame.Window(state.title, (WIDTH, self.height))
        self.win.focus()  # in front of the phone window
        pygame.key.start_text_input()  # the name field; key events for this window never reach the phone
        self.draw()

    def _layout(self) -> None:
        y = PAD + 22
        for i in range(len(ICON_CHOICES)):
            r, c = divmod(i, COLS)
            self.hits[f"icon:{i}"] = pygame.Rect(PAD + c * CELL, y + r * CELL, CELL - 4, CELL - 4)
        y += CELL * ((len(ICON_CHOICES) + COLS - 1) // COLS) + 8
        self.hits["name"] = pygame.Rect(PAD + 50, y, WIDTH - 2 * PAD - 50, 28)
        y += 28 + 18 + 22
        self.step_lines = [_wrap(s, self.small, WIDTH - 2 * PAD - 22) for s in self.state.steps()]
        self.steps_top = y
        y += sum(18 * len(lines) + 6 for lines in self.step_lines)
        self.hits["send"] = pygame.Rect(PAD + 22, y, 150, 30)
        y += 30 + 18
        self.hits["cancel"] = pygame.Rect(WIDTH - PAD - 190, y, 80, 30)
        self.hits["ok"] = pygame.Rect(WIDTH - PAD - 100, y, 100, 30)
        self.height = y + 30 + PAD

    def handle(self, event: pygame.event.Event) -> bool:
        """Consume events for this window; returns False for everything else."""
        if self.closed or getattr(event, "window", None) is not self.win:
            return False
        if event.type == pygame.TEXTINPUT:
            self.state.type(event.text)
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE:
            self.state.backspace()
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._finish(self.state.result())
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE or event.type == pygame.WINDOWCLOSE:
            self._finish(None)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit = next((k for k, r in self.hits.items() if r.collidepoint(event.pos)), None)
            if hit and hit.startswith("icon:"):
                self.state.select(int(hit[5:]))
            elif hit == "send":
                self.on_send()
            elif hit == "cancel":
                self._finish(None)
            elif hit == "ok":
                self._finish(self.state.result())
        if not self.closed:
            self.draw()
        return True

    def _finish(self, result: Custom | None) -> None:
        self.closed = True
        pygame.key.stop_text_input()
        self.win.destroy()
        self.on_done(result)

    def _button(self, surf: pygame.Surface, rect: pygame.Rect, text: str, filled: bool) -> None:
        pygame.draw.rect(surf, ACCENT if filled else (255, 255, 255), rect)
        pygame.draw.rect(surf, ACCENT, rect, 1)
        label = self.small.render(text, True, (255, 255, 255) if filled else ACCENT)
        surf.blit(label, label.get_rect(center=rect.center))

    def draw(self) -> None:
        s = self.state
        surf = self.win.get_surface()
        surf.fill(SURFACE)
        surf.blit(self.font.render("1. Pick an icon and a name", True, FG), (PAD, PAD))
        for i, (icon, _) in enumerate(ICON_CHOICES):
            r = self.hits[f"icon:{i}"]
            if icon == s.icon:
                pygame.draw.circle(surf, ON_BG, r.center, r.width // 2)
            glyph = self.icons.render(icon, True, ON_FG if icon == s.icon else FG)
            surf.blit(glyph, glyph.get_rect(center=r.center))
        name = self.hits["name"]
        surf.blit(self.small.render("Name", True, MUTED), (PAD, name.y + 7))
        pygame.draw.rect(surf, (255, 255, 255), name)
        pygame.draw.rect(surf, SEP, name, 1)
        text = f"{s.name}|" if s.name else dict(ICON_CHOICES)[s.icon]  # empty: the icon's label is used
        surf.blit(self.small.render(text, True, TEXT if s.name else DISABLED), (name.x + 8, name.y + 7))
        surf.blit(self.font.render(f"2. Bind it on the iPhone (this is button {s.button})", True, FG),
                  (PAD, self.steps_top - 22))
        y = self.steps_top
        for n, lines in enumerate(self.step_lines, 1):
            surf.blit(self.small.render(f"{n}.", True, MUTED), (PAD, y))
            for line in lines:
                surf.blit(self.small.render(line, True, TEXT), (PAD + 22, y))
                y += 18
            y += 6
        self._button(surf, self.hits["send"], f"Send button {s.button}", False)
        self._button(surf, self.hits["cancel"], "Cancel", False)
        self._button(surf, self.hits["ok"], "Save" if s.title == "Edit button" else "Add to toolbar", True)
        self.win.flip()


class Menu:
    """Right-click menu of a custom button: Edit… / Remove. Closes when it loses focus."""

    def __init__(self, pos: tuple[int, int], button: int, on_edit: Callable[[], None], on_remove: Callable[[], None]) -> None:
        self.button, self.on_edit, self.on_remove = button, on_edit, on_remove
        self.font, self.small = pygame.font.Font(None, 20), pygame.font.Font(None, 16)
        self.note = _wrap(f"Removing keeps the phone's Button {button} mapping: set it to None there "
                          "(AssistiveTouch › Devices) if you don't want it.", self.small, 220)
        self.hits = {"edit": pygame.Rect(0, 4, 240, 30), "remove": pygame.Rect(0, 34, 240, 30)}
        self.closed = False
        self.win = pygame.Window("scrcrappy menu", (240, 72 + 15 * len(self.note)), borderless=True, utility=True)
        self.win.position = pos
        self.win.focus()
        self.draw()

    def handle(self, event: pygame.event.Event) -> bool:
        if self.closed or getattr(event, "window", None) is not self.win:
            return False
        if event.type == pygame.WINDOWFOCUSLOST or event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit = next((k for k, r in self.hits.items() if r.collidepoint(event.pos)), None)
            if hit:
                self.close()
                (self.on_edit if hit == "edit" else self.on_remove)()
        elif event.type == pygame.MOUSEMOTION:
            self.draw(event.pos)
        return True

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.win.destroy()

    def draw(self, mouse: tuple[int, int] | None = None) -> None:
        surf = self.win.get_surface()
        surf.fill(SURFACE)
        for key, text in (("edit", "Edit…"), ("remove", "Remove")):
            r = self.hits[key]
            if mouse and r.collidepoint(mouse):
                pygame.draw.rect(surf, ON_BG, r)
            surf.blit(self.font.render(text, True, TEXT), (12, r.y + 8))
        pygame.draw.line(surf, SEP, (8, 66), (232, 66))
        for i, line in enumerate(self.note):
            surf.blit(self.small.render(line, True, MUTED), (12, 70 + 15 * i))
        self.win.flip()
