# scrcrappy toolbar (design)

## Intent

Common actions should be one click away instead of keybinds to remember. A small floating
bar next to the phone window holds them. User-chosen look: Material-style, light, unobtrusive,
can be collapsed out of the way.

Mockup (visual companion, `.superpowers/brainstorm/…/content/toolbar-final.html`): the
approved look: tonal palette, 80% height, small chevron, collapsed tab.

## Goals

1. Floating **pill** to the right of the phone window, its own borderless window that follows
   the phone window when it moves or resizes.
2. Buttons, top to bottom: **Paste**, **Copy**, separator, **Home**, **App switcher**,
   separator, **Natural scroll** (toggle), separator, **Collapse** (small chevron, ~60% of a
   normal button).
3. Icons only (Material Symbols Rounded), tooltip on hover with the action name.
4. **Collapse**: pill shrinks to a thin tab beside the window; hovering the tab expands it,
   leaving collapses again. Clicking the chevron while expanded toggles pinned-open vs.
   collapse-on-leave.
5. **Paste** = type the computer clipboard into the phone as keystrokes. Also on
   **Ctrl+Shift+V** in the phone window.
6. **Copy** disabled (greyed) with BLE/ESP32 backends; tooltip: "Copy to computer needs the
   jailbreak backend: a Bluetooth keyboard/mouse can't read the phone's clipboard." (User
   decision.) Enabled later by the ZXTouch backend.
7. Natural scroll toggle starts from `--natural-scroll`, flips live.

## Look (user decisions)

- Palette "tonal blue-grey": pill `#dfe6f1`, icon `#3a4656`, hover overlay
  `rgba(58,70,86,.10)`, active toggle fill `#b9cbe8` / icon `#0f2a4d`, disabled icon `#a9b3c1`,
  separators `#c6cfdb`, tooltip `#303034` on text `#f2f0f4`. Soft shadow if feasible.
- Pill height = **80% of the phone window height**, vertically centred on it (centring: my
  call). **Square corners** (user decision, 2026-10-19): rounded ends need a see-through
  window, which XWayland didn't keep (X Shape got reset) and native Wayland can't combine with
  positioning the window next to the phone. Buttons scale with the height (cap at ~40 px).
- Active toggle: filled icon + tonal circle. Hover: round translucent overlay.

## Constraints

- Linux (Fedora, Wayland session) and macOS. Stays in pygame-ce (multi-window via
  `pygame.Window`), no new GUI framework. Material Symbols font bundled (Apache-2.0) as a TTF.
- Settings stay CLI flags (no config file); the bar only changes live state.
- No mouse/keyboard backend → bar still shows; Paste/Home/App switcher greyed with tooltip
  "needs --mouse ble or esp32".

## Decisions with risk (verify first, my calls)

- **Pill follows the window**: verified on the user's Fedora: SDL2 runs on XWayland by
  default, where the app may position its windows, and the pill follows while dragging and
  resizing. Forcing `SDL_VIDEODRIVER=wayland` would break this (Wayland forbids it).
- **Home / App switcher** on iPhone 8 (physical home button, no swipe gestures): first try
  iOS hardware-keyboard shortcuts (e.g. Cmd+H style); if none work, use AssistiveTouch's
  device-button mapping: user sets mouse button 2 = Home, button 3 = App Switcher once
  (AssistiveTouch > Devices > scrcrappy PC), and the bar clicks those buttons. README
  documents whichever is used.
- **Paste typing table**: US layout only (user's phone is set to U.S.), printable ASCII +
  Enter + Tab. Other characters are skipped and counted; window title or stderr says
  "skipped N characters". Typing pace: key reports go through the link without the mouse
  pacing; down+up per char, ~10 ms apart.

## Non-goals

- Phone → computer clipboard (needs jailbreak backend).
- Ctrl→Cmd remapping (separate decision).
- Other layouts for paste, labels under icons, themes/dark mode, config persistence.

## Settled by me (builder-check answers)

- No room on the right (window at screen edge / maximized): pill goes on the left side.
- Phone window minimized or closed: pill hides / closes with it.
- After a pill click, focus returns to the phone window so typing keeps going to the phone.
- Moving the mouse from the pill back onto the phone triggers the usual corner re-sync
  (same as any window enter).
- Keys typed during a paste are queued after it.

## Left to the builder

- Module split, drawing approach (pre-rendered icon surfaces), tooltip delay (~500 ms),
  exact separator spacing, collapse animation (none is fine).
- Clipboard read via `pygame.scrap`.

## Addendum (2026-10-19): custom buttons + saved config (user-approved)

Replaces the fixed Home / App switcher buttons. Mockup: `.superpowers/brainstorm/…/content/custom-buttons.html`.

- **Custom buttons** (BLE / ESP32 only; the jailbreak backend gets its own later): the pill shows
  user-added buttons, then a **+**. Each custom button clicks one mouse button, 2–5 (next free
  one assigned automatically; max 4). **+** greys out with a reason when all are used or there is
  no mouse backend.
- **+** opens an **Add button** window: icon grid (16 Material icons), optional name, numbered
  binding steps naming the phone's menu path (`Settings › Accessibility › Touch › AssistiveTouch ›
  Devices › <scrcrappy PC|scrcrappy ESP32>` › Customise Additional Buttons), a **Send button N**
  button for iOS's "Press a button on your pointer device" step, and the hint that iOS may add a
  *Button N* row set to Secondary Click which must be opened to pick the action. Cancel / Add.
- **Right-click a custom button**: menu **Edit…** (same window, prefilled, same button number) and
  **Remove** (frees the number; reminds that the phone keeps its mapping until set to None).
- **HID**: mouse report grows from 3 to 5 buttons (helper + firmware) → one re-pair.
- **Saved config** `~/.config/scrcrappy/config.json`, written after every change, loaded at start:
  custom buttons per *phone serial + mouse backend*; natural scrolling; pill pinned/collapsed.
  An explicit `--natural-scroll` overrides the saved value. Corrupt/missing file → defaults.
- Real mouse in the phone window: unchanged (left button only).
