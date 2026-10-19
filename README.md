# scrcrappy

scrcpy for iOS: mirror and control an iPhone over USB.

## Install

**Linux** (Fedora shown; usbmuxd and libusb are on most desktops already):

```sh
sudo dnf install pipx usbmuxd
pipx install https://github.com/OWNER/scrcrappy/releases/download/v0.2.0/scrcrappy-0.2.0-py3-none-manylinux_2_35_x86_64.whl
```

Until the repo is public: `scripts/build-qvh.sh && pipx install .` from a checkout (needs the
Development packages below). Bluetooth mode also needs `sudo dnf install python3-dbus python3-gobject`.

**macOS** (untested):

```sh
brew tap OWNER/scrcrappy
brew install scrcrappy
```

Then run `scrcrappy` from anywhere. Releases: [docs/releasing.md](docs/releasing.md).

## Development

Fedora:

```sh
sudo dnf install golang libusb1-devel
```

macOS: `brew install go libusb pkg-config`

```sh
scripts/build-qvh.sh            # patched qvh -> scrcrappy/bin/qvh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Run

Plug in the iPhone, unlock it, trust the computer, then:

```sh
.venv/bin/scrcrappy
```

## Why a patched qvh

[qvh](https://github.com/danielpaulus/quicktime_video_hack) speaks the QuickTime USB
mirroring protocol. `third_party/qvh.patch` makes two changes:

- skip the endpoint clear-halt before reading: on Linux it dropped the PING the phone
  queues right after switching to the mirroring config, so streaming never started;
- write video unbuffered, so a still screen doesn't sit in a 4 KB buffer.
- drop qvh's own GStreamer window and audio commands (scrcrappy only runs `qvh record`), so it needs
  nothing but libusb at runtime.
- drop qvh's pairing check, the only use of go-ios (AGPL-3.0), so everything shipped stays permissively
  licensed; the licences of qvh and its Go modules ship as `scrcrappy/bin/qvh-LICENSES.txt`.

## Licence

MIT, see [LICENSE](LICENSE).

## Mouse control without jailbreak

A BLE mouse drives the AssistiveTouch cursor. Pick where it comes from with `--mouse`:

- `--mouse ble`: this computer's Bluetooth adapter (Linux only).
- `--mouse esp32 --port /dev/ttyUSB0`: an ESP32 / ESP32-C3 / ESP32-S3 running
  `firmware/esp32-mouse` (works from Linux and macOS). Flash it once with PlatformIO:
  `cd firmware/esp32-mouse && pio run -e esp32dev -t upload` (env per board in `platformio.ini`).
  On the phone it is called "scrcrappy ESP32" (the laptop helper: "scrcrappy PC").

Either way the phone sees a BLE mouse; the phone shows it as the AssistiveTouch
cursor, and scrcrappy steers that cursor to follow your mouse over the window.

1. iPhone: Settings > Accessibility > Touch > AssistiveTouch: on.
2. For `ble` only: `sudo dnf install python3-dbus python3-gobject` (the helper runs under the system python).
3. `.venv/bin/scrcrappy --mouse ble` (or `esp32`), then on the phone pair the mouse
   (AssistiveTouch > Devices > Bluetooth Devices).
4. Optional, once per phone or after changing AssistiveTouch tracking speed: open a plain light
   screen (e.g. Settings) and run `.venv/bin/scrcrappy --mouse ble --calibrate` (or `esp32`).

Click = tap, drag = drag, wheel = scroll (`--natural-scroll` inverts it).

The same BLE device is also a keyboard: keys typed in the window go to the phone by physical
position, so set the phone's hardware layout to match your computer's
(Settings > General > Keyboard > Hardware Keyboard, per language). iOS uses the layout of the
*active* input language: Ctrl+Space in the window switches it. While connected, iOS hides the
on-screen keyboard.

After updating scrcrappy, if the device description changed: "Forget" it on the phone, run
`bluetoothctl remove <phone address>` (ble) or reflash (esp32), and pair again: iOS caches it. The cursor re-syncs in the top-left corner whenever the
mouse enters the window.

## Control with a jailbreak (scrcrappy-agent)

On a jailbroken phone, install [scrcrappy-agent](../scrcrappy-agent) (a SpringBoard tweak, reached over USB
only) and run `.venv/bin/scrcrappy --mouse agent` (or pick Agent in the toolbar's Settings once). No Bluetooth, no AssistiveTouch, no calibration:

- Click / drag = touch at that exact spot; **Ctrl+drag** = two-finger pinch around the screen centre;
  wheel = short swipe (`--natural-scroll` applies).
- Keys go to the phone by physical position (same Hardware Keyboard layout note as below); held keys repeat.
- Paste (**Ctrl+Shift+V**) types any text, accents and emoji included. iOS shows *Allow Paste* in the app
  (Settings › ‹app› › Paste from Other Apps › Allow stops it); the text stays on the phone's clipboard.
- Toolbar: Copy (phone clipboard → computer), Screenshot (PNG in `~/Pictures`, or the folder in Settings), Home, App switcher, Lock.

First run: unlock the phone; it asks *Allow “‹computer›” to control this iPhone?* with a 6-digit code —
check it matches the one in the terminal, tap Allow. After each phone reboot, touch its screen once
before clicks work (the terminal says so).

## Toolbar

A small bar sits to the right of the phone window (left if there's no room) and follows it.
Hover a button for its name.

| Button | Does |
|---|---|
| Paste | Types the computer's clipboard into the phone (also **Ctrl+Shift+V**). US layout, printable ASCII + Enter/Tab; other characters are skipped and reported. |
| Copy | Phone clipboard → computer, with `--mouse agent` only (a Bluetooth keyboard/mouse can't read the phone's clipboard). |
| Custom buttons | Click a mouse button (2–5) that you bind to any AssistiveTouch action on the phone. Right-click one to edit or remove it. |
| + | Adds a custom button: pick an icon and a name, then follow the steps it shows to bind it on the phone (it has a *Send button N* button for the step where iOS asks you to press one). |
| Natural scrolling | Flips the wheel direction live. |
| Settings (gear) | Input mode (and ESP32 port) used when `--mouse` / `--port` aren't given — applies next launch; natural scrolling; screenshot folder (… opens the desktop's folder picker: zenity on Linux). Closes when you click elsewhere. |
| Chevron | Collapses the bar to a thin tab that opens while hovered; click the chevron again to keep it open. |

Custom buttons are remembered per phone and per Bluetooth device (scrcrappy PC and scrcrappy ESP32
each have their own mapping on the phone). The toolbar's state is saved in
`~/.config/scrcrappy/config.json`: custom buttons, natural scrolling, and whether the bar is pinned.
`--natural-scroll` / `--no-natural-scroll` override the saved scrolling direction.

After updating to the 5-button version, forget and re-pair the device on the phone once.

On Linux scrcrappy runs through X11 (XWayland on Wayland desktops) because Wayland doesn't let
an app place the toolbar next to its window; set `SDL_VIDEODRIVER` yourself to override.
