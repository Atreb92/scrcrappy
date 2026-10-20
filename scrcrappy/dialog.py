"""Opened from the toolbar: windows for add/edit a custom button and its right-click menu, and the Settings\noverlay inside the phone window."""
import subprocess
import sys
import threading
import time
from typing import Callable

import pygame

from .config import ICON_CHOICES, Config, Custom
from .toolbar import DISABLED, FG, ICONS, ON_BG, ON_FG, SEP, TIP_DELAY, draw_tip, ui_font

SURFACE, TEXT, MUTED, ACCENT = (34, 34, 38), (242, 242, 247), (161, 161, 170), (10, 132, 255)  # iOS dark
FIELD, SWITCH_ON, GLASS_ALPHA, BLUR = (68, 68, 74), (48, 209, 88), 210, 8  # BLUR: shrink factor of the backdrop
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
        self.font, self.small, self.head = ui_font(14), ui_font(12), ui_font(14, True)
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
        pygame.draw.rect(surf, ACCENT if filled else FIELD, rect, border_radius=8)
        label = self.small.render(text, True, (255, 255, 255) if filled else ACCENT)
        surf.blit(label, label.get_rect(center=rect.center))

    def draw(self) -> None:
        s = self.state
        surf = self.win.get_surface()
        surf.fill(SURFACE)
        surf.blit(self.head.render("1. Pick an icon and a name", True, FG), (PAD, PAD))
        for i, (icon, _) in enumerate(ICON_CHOICES):
            r = self.hits[f"icon:{i}"]
            if icon == s.icon:
                pygame.draw.circle(surf, ON_BG, r.center, r.width // 2)
            glyph = self.icons.render(icon, True, ON_FG if icon == s.icon else FG)
            surf.blit(glyph, glyph.get_rect(center=r.center))
        name = self.hits["name"]
        surf.blit(self.small.render("Name", True, MUTED), (PAD, name.y + 7))
        pygame.draw.rect(surf, FIELD, name, border_radius=7)
        text = f"{s.name}|" if s.name else dict(ICON_CHOICES)[s.icon]  # empty: the icon's label is used
        surf.blit(self.small.render(text, True, TEXT if s.name else DISABLED), (name.x + 8, name.y + 7))
        surf.blit(self.head.render(f"2. Bind it on the iPhone (this is button {s.button})", True, FG),
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
    """Right-click menu of a custom button, an overlay in the phone window like Settings (`where(size)` puts it):
    Edit… / Remove. Takes every mouse and key event while open; closes on a choice, Esc, a click outside or
    losing focus."""
    W = 240

    def __init__(self, window: pygame.Window, where: Callable[[tuple[int, int]], pygame.Rect], button: int,
                 on_edit: Callable[[], None], on_remove: Callable[[], None],
                 on_close: Callable[[], None] = lambda: None) -> None:
        self.window, self.where, self.button, self.on_edit, self.on_remove, self.on_close = (
            window, where, button, on_edit, on_remove, on_close)
        self.font, self.small = ui_font(14), ui_font(11)
        self.note = _wrap(f"Removing keeps the phone's Button {button} mapping: set it to None there "
                          "(AssistiveTouch › Devices) if you don't want it.", self.small, 220)
        self.hits = {"edit": pygame.Rect(6, 6, self.W - 12, 30), "remove": pygame.Rect(6, 36, self.W - 12, 30)}
        self.height = 78 + 15 * len(self.note)
        self.closed = False
        self.hover: str | None = None

    @property
    def rect(self) -> pygame.Rect:
        return self.where((self.W, self.height))

    def handle(self, event: pygame.event.Event) -> bool:
        if self.closed or getattr(event, "window", None) is not self.window:
            return False
        if event.type == pygame.WINDOWFOCUSLOST:
            self.close()
            return False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
        elif event.type == pygame.MOUSEMOTION:
            self.hover = self._hit(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            hit = self._hit(event.pos)
            self.close()  # a click outside just closes it
            if hit:
                (self.on_edit if hit == "edit" else self.on_remove)()
        return event.type in INPUT

    def _hit(self, pos: tuple[int, int]) -> str | None:
        rect = self.rect
        local = (pos[0] - rect.x, pos[1] - rect.y)
        return next((k for k, r in self.hits.items() if r.collidepoint(local)), None)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.on_close()

    def draw(self, screen: pygame.Surface, dim_height: int) -> None:
        if self.closed:
            return
        dim = pygame.Surface((screen.get_width(), dim_height), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 60))
        screen.blit(dim, (0, 0))
        rect = self.rect
        surf = pygame.Surface((self.W, self.height), pygame.SRCALPHA)
        surf.blit(_glass(screen, rect), (0, 0))
        for key, text in (("edit", "Edit…"), ("remove", "Remove")):
            r = self.hits[key]
            if key == self.hover:
                pygame.draw.rect(surf, ON_BG, r, border_radius=8)
            surf.blit(self.font.render(text, True, TEXT), (r.x + 10, r.y + 6))
        pygame.draw.line(surf, SEP, (14, 70), (self.W - 14, 70))
        for i, line in enumerate(self.note):
            surf.blit(self.small.render(line, True, MUTED), (14, 76 + 15 * i))
        _round(surf, MENU_R)
        screen.blit(surf, rect.topleft)


INPUT = (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL, pygame.KEYDOWN,
         pygame.KEYUP, pygame.TEXTINPUT)
PANEL_R, MENU_R = 20, 16


def _round(surf: pygame.Surface, radius: int) -> None:
    """Round `surf`'s corners and give it a thin light edge."""
    mask = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    pygame.draw.rect(surf, (255, 255, 255, 46), surf.get_rect(), 1, border_radius=radius)


def _glass(screen: pygame.Surface, rect: pygame.Rect) -> pygame.Surface:
    """What shows through frosted glass over `rect`: the pixels there, blurred (shrunk, enlarged) and tinted."""
    clipped = rect.clip(screen.get_rect())
    if not clipped.w or not clipped.h:
        return pygame.Surface((1, 1), pygame.SRCALPHA)
    under = screen.subsurface(clipped).copy()
    w, h = under.get_size()
    small = pygame.transform.smoothscale(under, (max(1, w // BLUR), max(1, h // BLUR)))
    glass = pygame.transform.smoothscale(small, (w, h)).convert_alpha()
    tint = pygame.Surface((w, h), pygame.SRCALPHA)
    tint.fill((*SURFACE, GLASS_ALPHA))
    glass.blit(tint, (0, 0))
    return glass


CALIBRATE_TIP = ("Measures the pointer speed again. Do it after changing Tracking Speed on the iPhone (Settings › "
                 "Accessibility › Touch › AssistiveTouch), or when the cursor overshoots or falls short. Open a plain, "
                 "light screen first and don't touch the mouse for about 20 s.")
MODES = [("none", "None"), ("ble", "BT"), ("esp32", "ESP32"), ("agent", "Agent")]
PANEL_W, SWITCH = 260, (34, 18)


def pick_folder(initial: str) -> str | None:
    """The desktop's folder picker (zenity on Linux, AppleScript on macOS); None if cancelled or missing."""
    if sys.platform == "darwin":
        cmd = ["osascript", "-e", "POSIX path of (choose folder)"]
    else:
        cmd = ["zenity", "--file-selection", "--directory", f"--filename={initial.rstrip('/')}/"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
    except OSError:
        print("settings: no folder picker found (install zenity); type the path instead", file=sys.stderr)
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


class Settings:
    """The settings overlay: a panel inside the phone window (`window`) over a dimmed phone image, where `where(size)`
    puts it (a Rect in window coordinates). While open it takes every mouse and key event. Choices are written to
    `cfg` and `on_change` runs at once; typed text (port, folder) is kept on Enter, on clicking elsewhere in the
    panel, or when it closes. Closes on Esc, a click outside the panel, losing focus (except while the folder
    picker is open) and Calibrate. A window shorter than the panel clips its bottom (ponytail: scroll if it matters)."""

    def __init__(self, window: pygame.Window, where: Callable[[tuple[int, int]], pygame.Rect], cfg: Config,
                 on_change: Callable[[], None], on_natural: Callable[[], None], on_close: Callable[[], None],
                 calibration: float | None = None, on_calibrate: Callable[[], None] | None = None,
                 on_ai: Callable[[], None] | None = None, ai_status: Callable[[], str] = lambda: "",
                 on_copy: Callable[[], None] | None = None) -> None:
        """`calibration`: the pointer's current value (Bluetooth / ESP32 only); None hides that section.
        `on_ai` toggles AI control (cfg.ai_control), `ai_status()` is its address or error, `on_copy` copies
        the command that registers it with an AI client."""
        self.window, self.where, self.cfg, self.on_change, self.on_natural, self.on_close = (
            window, where, cfg, on_change, on_natural, on_close)
        self.on_calibrate, self.on_ai, self.ai_status, self.on_copy = on_calibrate, on_ai, ai_status, on_copy
        self.font, self.small, self.head = ui_font(14), ui_font(12), ui_font(14, True)
        self.calibration_lines = [] if calibration is None else _wrap(
            f"Current: {calibration:.2f} px per mouse count", self.small, PANEL_W - 2 * PAD)
        self.tips = {} if calibration is None else {"calibrate": CALIBRATE_TIP}  # hover texts by hit name
        self.hover: str | None = None
        self.hover_since = 0.0
        self.icons = pygame.font.Font(ICONS / "MaterialSymbolsRounded-outline.ttf", 18)
        self.text = {"port": cfg.port, "screenshots": cfg.screenshots}
        self.editing: str | None = None
        self.closed = self.picking = False
        self.hits: dict[str, pygame.Rect] = {}
        self._layout()

    @property
    def rect(self) -> pygame.Rect:
        return self.where((PANEL_W, self.height))

    def _layout(self) -> None:
        self.hits = {}
        cell = (PANEL_W - 2 * PAD) // len(MODES)
        for i in range(len(MODES)):
            self.hits[f"mode:{i}"] = pygame.Rect(PAD + i * cell, 34, cell, 28)
        y = 34 + 28 + 10
        if self.cfg.mouse == "esp32":
            self.hits["port"] = pygame.Rect(PAD + 40, y, PANEL_W - 2 * PAD - 40, 26)
            y += 26 + 10
        self.hits["natural"] = pygame.Rect(PANEL_W - PAD - SWITCH[0], y + 4, *SWITCH)
        y += 26 + 12
        self.shots_top = y
        self.hits["screenshots"] = pygame.Rect(PAD, y + 20, PANEL_W - 2 * PAD - 34, 26)
        self.hits["browse"] = pygame.Rect(PANEL_W - PAD - 28, y + 20, 28, 26)
        y += 20 + 26 + 12
        self.ai_top = y
        self.hits["ai"] = pygame.Rect(PANEL_W - PAD - SWITCH[0], y + 4, *SWITCH)
        y += 26
        self.ai_lines = _wrap(self.ai_status(), self.small, PANEL_W - 2 * PAD) if self.cfg.ai_control else []
        if self.cfg.ai_control:
            y += 16 * len(self.ai_lines) + 6
            self.hits["copy"] = pygame.Rect(PANEL_W - PAD - 150, y, 150, 28)
            y += 28
        if self.calibration_lines:
            self.calib_top = y + 14
            y = self.calib_top + 20 + 16 * len(self.calibration_lines) + 6
            self.hits["calibrate"] = pygame.Rect(PANEL_W - PAD - 100, y, 100, 28)
            y += 28
        self.height = y + PAD

    def handle(self, event: pygame.event.Event) -> bool:
        """True for every mouse and key event while open: nothing reaches the phone or the toolbar."""
        if self.closed or getattr(event, "window", None) is not self.window:
            return False
        if event.type == pygame.WINDOWFOCUSLOST:
            if not self.picking:
                self.close()
            return False  # the phone window still releases what is held
        if event.type == pygame.TEXTINPUT and self.editing:
            self.text[self.editing] = (self.text[self.editing] + event.text)[:300]
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE and self.editing:
            self.text[self.editing] = self.text[self.editing][:-1]
        elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
        elif event.type == pygame.MOUSEMOTION:
            hit = self._hit(event.pos)
            if hit != self.hover:
                self.hover, self.hover_since = hit, time.monotonic()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            rect = self.rect
            if rect.collidepoint(event.pos):
                local = (event.pos[0] - rect.x, event.pos[1] - rect.y)
                self._click(next((k for k, r in self.hits.items() if r.collidepoint(local)), None))
            else:
                self.close()  # on release: the press that started it never reached the phone either
        return event.type in INPUT

    def _hit(self, pos: tuple[int, int]) -> str | None:
        rect = self.rect
        local = (pos[0] - rect.x, pos[1] - rect.y)
        return next((k for k, r in self.hits.items() if r.collidepoint(local)), None) if rect.collidepoint(pos) else None

    def tip(self, now: float | None = None) -> str | None:
        """The hover text of the item under the mouse, once it has been there for TIP_DELAY."""
        now = time.monotonic() if now is None else now
        return self.tips.get(self.hover) if self.hover and now - self.hover_since >= TIP_DELAY else None

    def _click(self, hit: str | None) -> None:
        if hit not in ("port", "screenshots"):
            self._commit()
        if hit and hit.startswith("mode:"):
            self.cfg.mouse = MODES[int(hit[5:])][0]
            self.on_change()
            self._relayout()  # the port row comes and goes with ESP32
        elif hit in ("port", "screenshots") and hit != self.editing:
            self._commit()
            self.editing = hit
            pygame.key.start_text_input()
        elif hit == "natural":
            self.on_natural()
        elif hit == "ai" and self.on_ai:
            self.on_ai()
            self._relayout()
        elif hit == "copy" and self.on_copy:
            self.on_copy()
        elif hit == "calibrate":
            self.close()
            self.on_calibrate()
        elif hit == "browse" and not self.picking:
            self.picking = True

            def run() -> None:
                path = pick_folder(self.text["screenshots"] or "~/Pictures")
                pygame.event.post(pygame.event.Event(pygame.USEREVENT, run=lambda: self._picked(path)))

            threading.Thread(target=run, daemon=True).start()

    def _relayout(self) -> None:
        self._layout()

    def _picked(self, path: str | None) -> None:
        self.picking = False
        if path:
            self.text["screenshots"] = path
            self.editing = "screenshots"
            self._commit()

    def _commit(self) -> None:
        if not self.editing:
            return
        value = self.text[self.editing].strip()
        if self.editing == "port":
            value = value or Config.port
        self.text[self.editing] = value
        if getattr(self.cfg, self.editing) != value:
            setattr(self.cfg, self.editing, value)
            self.on_change()
        self.editing = None
        pygame.key.stop_text_input()

    def close(self) -> None:
        if not self.closed:
            self._commit()
            self.closed = True
            self.on_close()

    def _switch(self, surf: pygame.Surface, key: str, label: str, on: bool) -> None:
        sw = self.hits[key]
        surf.blit(self.font.render(label, True, FG), (PAD, sw.y + 2))
        pygame.draw.rect(surf, SWITCH_ON if on else (92, 92, 98), sw, border_radius=sw.height // 2)
        knob = (sw.right - sw.height // 2 if on else sw.x + sw.height // 2, sw.centery)
        pygame.draw.circle(surf, (255, 255, 255), knob, sw.height // 2 - 2)

    def _field(self, surf: pygame.Surface, key: str, placeholder: str) -> None:
        r = self.hits[key]
        pygame.draw.rect(surf, FIELD, r, border_radius=7)
        if self.editing == key:
            pygame.draw.rect(surf, ACCENT, r, 1, border_radius=7)
        text = self.text[key] + ("|" if self.editing == key else "")
        label = self.small.render(text or placeholder, True, TEXT if text else MUTED)
        clip = label.subsurface(max(0, label.get_width() - (r.width - 12)), 0,  # long paths: show the end
                                min(label.get_width(), r.width - 12), label.get_height())
        surf.blit(clip, (r.x + 6, r.y + 7))

    def draw(self, screen: pygame.Surface, dim_height: int) -> None:
        """Dim the top `dim_height` px of the window (the phone image), then draw the panel at `rect`."""
        if self.closed:
            return
        dim = pygame.Surface((screen.get_width(), dim_height), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 90))
        screen.blit(dim, (0, 0))
        rect = self.rect
        surf = pygame.Surface((PANEL_W, self.height), pygame.SRCALPHA)
        surf.blit(_glass(screen, rect), (0, 0))
        surf.blit(self.head.render("Input", True, FG), (PAD, 14))
        tag = self.small.render("next launch", True, (0xF2, 0xB7, 0x05))
        tag_bg = tag.get_rect(topleft=(PAD + 50, 13)).inflate(10, 4)
        pygame.draw.rect(surf, (0x4A, 0x3A, 0x12), tag_bg, border_radius=tag_bg.height // 2)
        surf.blit(tag, tag.get_rect(center=tag_bg.center))
        first, last = self.hits["mode:0"], self.hits[f"mode:{len(MODES) - 1}"]  # iOS segmented control
        pygame.draw.rect(surf, FIELD, first.union(last), border_radius=8)
        for i, (mode, name) in enumerate(MODES):
            r = self.hits[f"mode:{i}"]
            on = self.cfg.mouse == mode
            if on:
                pygame.draw.rect(surf, ON_BG, r.inflate(-4, -4), border_radius=6)
            label = self.small.render(name, True, ON_FG if on else FG)
            surf.blit(label, label.get_rect(center=r.center))
        if "port" in self.hits:
            surf.blit(self.small.render("Port", True, FG), (PAD, self.hits["port"].y + 7))
            self._field(surf, "port", Config.port)
        self._switch(surf, "natural", "Natural scrolling", self.cfg.natural_scroll)
        surf.blit(self.head.render("Screenshots", True, FG), (PAD, self.shots_top))
        self._field(surf, "screenshots", "~/Pictures")
        b = self.hits["browse"]
        pygame.draw.rect(surf, FIELD, b, border_radius=7)
        glyph = self.icons.render("\ue2c8", True, ACCENT)  # folder_open
        surf.blit(glyph, glyph.get_rect(center=b.center))
        self._switch(surf, "ai", "Allow AI control (MCP)", self.cfg.ai_control)
        for i, line in enumerate(self.ai_lines):
            surf.blit(self.small.render(line, True, MUTED), (PAD, self.ai_top + 28 + 16 * i))
        if "copy" in self.hits:
            c = self.hits["copy"]
            pygame.draw.rect(surf, FIELD, c, border_radius=c.height // 2)
            label = self.small.render("Copy MCP config", True, ACCENT)
            surf.blit(label, label.get_rect(center=c.center))
        if self.calibration_lines:
            surf.blit(self.head.render("Pointer calibration", True, FG), (PAD, self.calib_top))
            for i, line in enumerate(self.calibration_lines):
                surf.blit(self.small.render(line, True, MUTED), (PAD, self.calib_top + 20 + 16 * i))
            c = self.hits["calibrate"]
            pygame.draw.rect(surf, ACCENT, c, border_radius=c.height // 2)
            label = self.small.render("Calibrate", True, (255, 255, 255))
            surf.blit(label, label.get_rect(center=c.center))
        _round(surf, PANEL_R)
        screen.blit(surf, rect.topleft, area=pygame.Rect(0, 0, rect.w, rect.h))
        if text := self.tip():
            draw_tip(screen, self.small, text, self.hits[self.hover].move(rect.topleft), 260)


class Popups:
    """The toolbar's popup windows (the Add/Edit dialog); at most one open at a time."""

    def __init__(self) -> None:
        self.items: list = []

    def open(self, make: Callable[[], "Dialog"]):
        """Open the popup `make` builds, unless one is already open (then returns None)."""
        self.items = [p for p in self.items if not p.closed]
        if self.items:
            return None
        self.items.append(make())
        return self.items[-1]

    def is_open(self) -> bool:
        return any(not p.closed for p in self.items)

    def handle(self, event: pygame.event.Event) -> bool:
        return any(p.handle(event) for p in list(self.items))

    def focused(self) -> bool:
        return any(not p.closed and p.win.focused for p in self.items)
