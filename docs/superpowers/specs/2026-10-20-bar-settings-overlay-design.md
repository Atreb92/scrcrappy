# Toolbar bar + Settings overlay (design)

Date: 2026-10-20. Replaces the floating pill. First step towards native Wayland (see "Why").

## Why

The pill, its tooltips and the Settings fly-out are separate OS windows placed beside the phone window. Native
Wayland won't let a client place windows or rely on focus, so scrcrappy forces X11/XWayland
(`__main__.py`, README). Moving the toolbar and Settings *into* the phone window removes the need for window
placement; the remaining separate windows (Add/Edit dialog, right-click menu) are handled in the Wayland step.

## What changes

- **Bar**: the same buttons as a horizontal strip, `BAR_H` (48 px) tall, at the bottom of the phone window.
  The window is the phone image plus the strip; the image is letterboxed in the area above it. Always visible:
  no collapse button, no `pinned` setting (removed from config; old files with it still load).
- **Tooltips** are drawn inside the window, above the hovered button.
- **Settings** is an overlay panel inside the window, centred above the bar, over a dimmed phone image (like
  iOS Control Center). While open it takes all mouse and keyboard input (nothing reaches the phone). It closes on
  Esc, a click outside the panel, the window losing focus (except while the folder picker is open), Calibrate,
  or the gear again. Typed text (port, folder) is kept on close, as today.
- **No option to switch back**: the pill code, `pill_rect`, `--ui` and the collapse/pin logic are deleted.
- Add/Edit dialog and the right-click menu stay separate windows for now (X11 positions them next to the bar).

## Non-goals / limits

- Native Wayland itself (driver choice, Dialog and Menu in-window): next step.
- The panel is not scrollable: in a window shorter than the panel (about 520 px with every section on) the bottom
  is clipped. Scrolling can come when needed.
- Bar width: the built-in buttons plus a few custom ones fit 375 px; many custom buttons shrink and then overflow
  (no overflow menu yet).

## Testing

Unit tests for the bar (layout, hit testing, tooltip, event consumption), the overlay (hit offsets, outside click,
Esc, focus loss, picker exception, key capture), and the app loop (settings save/calibrate flows through the gear).
