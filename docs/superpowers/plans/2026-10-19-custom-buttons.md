# Custom Buttons + Saved Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pill's fixed Home/App buttons with user-added custom buttons (mouse buttons 2–5) created through a "+" dialog with binding instructions, removable via right-click, persisted with the rest of the toolbar state.

**Architecture:** `config.py` (pure load/save), extended `toolbar.buttons()` model, a `dialog.py` with a pure state class plus a pygame window, and a small context-menu window. `app.run` loads/saves config through callbacks.

**Tech Stack:** existing pygame-ce multi-window code, bundled Material Symbols subset (extended).

**Spec:** `docs/superpowers/specs/2026-10-19-toolbar-design.md` (Addendum section).

## Global Constraints

- Mouse buttons for custom actions: 2, 3, 4, 5 (HID mask `1 << (n - 1)`), max 4 custom buttons.
- Config path `~/.config/scrcrappy/config.json`; written after every change; missing/corrupt → defaults; explicit `--natural-scroll` overrides saved value.
- Custom buttons keyed `"<phone serial>/<ble|esp32>"`.
- Palette and pill sizing unchanged from the toolbar spec.

## Review Focus

1. Corrupt / hand-edited config (bad JSON, unknown icon, button number outside 2–5, duplicates) → app starts with defaults or drops the bad entries, never crashes. (Task 1 test)
2. Config write interrupted → previous file intact (write to temp + rename). (Task 1 test)
3. Five buttons added / one removed and re-added → numbers stay unique, freed number reused. (Task 3 test)
4. Typing a name in the dialog must not leak keystrokes to the phone; closing the dialog restores raw key handling. (Task 4 test)
5. Right-click on a non-custom pill button or empty space → nothing. (Task 5 test)

---

### Task 1: Config file

**Files:** Create `scrcrappy/config.py`; Test `tests/test_config.py`

**Interfaces — Produces:**
- `@dataclass Custom(button: int, icon: str, name: str)` (icon = codepoint char)
- `@dataclass Config(natural_scroll: bool = False, pinned: bool = True, customs: dict[str, list[Custom]] = {})`
- `PATH = Path.home()/".config"/"scrcrappy"/"config.json"`
- `load(path: Path = PATH) -> Config` (drops invalid customs: button ∉ 2..5, duplicate button, icon not in `ICON_CHOICES`), `save(cfg: Config, path: Path = PATH) -> None` (tmp + `os.replace`).
- Icons stored in JSON as hex codepoint strings (`"e9b2"`).

- [ ] Tests: `test_missing_file_gives_defaults`, `test_roundtrip`, `test_corrupt_json_gives_defaults`, `test_invalid_customs_dropped`, `test_save_is_atomic` (monkeypatch `os.replace` to raise → original file unchanged).
- [ ] RED, implement, GREEN, commit `feat: saved config`.

### Task 2: Five mouse buttons

**Files:** Modify `scrcrappy/blemouse.py`, `firmware/esp32-mouse/src/main.cpp`; Test `tests/test_descriptor.py`

- [ ] Test `test_mouse_has_five_buttons`: mouse collection contains `19012905` (usage 1..5) and `95057501 8102` → count 5 size 1; padding `95017503 8103`.
- [ ] RED; change both descriptors (buttons 5 + padding 3) and the button masks `& 0x07` → `& 0x1F`; GREEN (existing equality test keeps both in sync); compile firmware (esp32dev); commit `feat: five mouse buttons for custom actions`.

### Task 3: Toolbar model with custom buttons

**Files:** Modify `scrcrappy/toolbar.py`; Test `tests/test_toolbar.py`, `tests/test_pill.py`

**Interfaces:**
- `ICON_CHOICES: list[tuple[str, str]]` (codepoint, label) — 16 entries (home, view_carousel, lock, tune, notifications, screenshot_monitor, mic, volume_up, volume_down, volume_off, screen_rotation, search, photo_camera, vibration, accessibility_new, star); verify codepoints from the font's `.codepoints` file.
- `buttons(has_input: bool, natural: bool, customs: list[Custom]) -> list[Button | None]`: paste, copy, None, *customs as `Button(f"custom:{n}", icon, f"{name or label} (button {n})")`*, add (`id="add"`, icon add U+E145; disabled with tip "All 4 custom buttons in use" or NEEDS_INPUT), None, natural, None, collapse.
- `next_free(customs) -> int | None`.
- Pill: `Pill.set_items(items)` re-lays out; right-click (MOUSEBUTTONUP button 3) on a `custom:N` button calls `actions["menu"](n)`; left click on `custom:N` calls `actions["custom"](n)`; `add` calls `actions["add"]()`.
- [ ] Tests: `test_customs_between_separators_with_add`, `test_add_disabled_when_full`, `test_next_free_reuses_lowest`, `test_right_click_custom_opens_menu`, `test_right_click_other_does_nothing`, update old home/apps tests.
- [ ] RED, implement, GREEN, commit `feat: custom buttons on the pill`.

### Task 4: Add/Edit dialog

**Files:** Create `scrcrappy/dialog.py`; Test `tests/test_dialog.py`

**Interfaces:**
- `class DialogState(button: int, device: str, custom: Custom | None = None)`: `icon`, `name`, `select(i)`, `type(text)`, `backspace()`, `result() -> Custom`, `steps() -> list[str]` (menu path with `device` name, "Send button N" step, Secondary-Click hint).
- `class Dialog(state, on_send: Callable[[], None], on_done: Callable[[Custom | None], None])`: pygame Window ~400×420, draws grid / name field / steps / buttons (Send button N, Cancel, Add|Save), `handle(event) -> bool` for its own window (TEXTINPUT/KEYDOWN Backspace/Enter/Escape, clicks), starts text input while focused and stops it on close.
- [ ] Tests (dummy SDL): `test_state_defaults_and_result`, `test_steps_name_device_and_button`, `test_typing_goes_to_name_not_phone` (TEXTINPUT on dialog window → name changes; Controller untouched), `test_escape_cancels`, `test_click_send_calls_on_send`.
- [ ] RED, implement, GREEN, commit `feat: add/edit custom button dialog`.

### Task 5: Context menu + wiring + persistence

**Files:** Create menu inside `scrcrappy/dialog.py` (`Menu(pos, on_edit, on_remove)` small window, closes on focus loss); Modify `scrcrappy/app.py`, `scrcrappy/__main__.py`, `scripts/make-icons.sh` + regenerate icons; Test `tests/test_dialog.py`, `tests/test_main.py`

- [ ] `__main__`: `cfg = config.load()`; key `f"{serial}/{args.mouse}"`; `natural = True if args.natural_scroll else cfg.natural_scroll` (flag is store_true: only an explicit flag overrides); pass `cfg`, key to `app.run`.
- [ ] `app.run(..., cfg: Config | None, device_key: str | None, device_name: str)`: builds items from `cfg.customs[key]`; actions custom → `pointer.click(1 << (n-1))`, add → open Dialog(next_free), menu → Menu(edit → Dialog prefilled, remove → drop + save); natural toggle, pin/collapse → update cfg + `config.save`.
- [ ] Tests: `test_menu_remove_calls_back`, `test_flag_overrides_saved_natural` (main with patched load/run).
- [ ] Regenerate icons with the new glyph list; check every ICON_CHOICES glyph renders.
- [ ] Full suite GREEN; commit `feat: custom button dialog, menu and saved config wired in`.
- [ ] Manual (user): re-pair once (5 buttons), add Home=2 / App switcher=3 via +, restart → buttons still there; remove one; natural/pin persist.

### Task 6: Docs

- [ ] README Toolbar section: custom buttons via +, right-click edit/remove, config file location; drop the old fixed Home/App text. TODO.md: replace the "Home / App switcher need a one-time mapping" item (done by the dialog). Commit `docs: custom buttons`.
