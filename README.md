# scrcrappy

scrcpy for iOS: mirror an iPhone's screen over USB (control comes next).

## Setup

Fedora:

```sh
sudo dnf install golang libusb1-devel gstreamer1-devel gstreamer1-plugins-base-devel
```

macOS: `brew install go libusb pkg-config gstreamer`

```sh
scripts/build-qvh.sh            # patched qvh -> bin/qvh
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

## Mouse control without jailbreak

A BLE mouse drives the AssistiveTouch cursor. Pick where it comes from with `--mouse`:

- `--mouse ble`: this computer's Bluetooth adapter (Linux only).
- `--mouse esp32 --port /dev/ttyUSB0`: an ESP32 / ESP32-C3 / ESP32-S3 running
  `firmware/esp32-mouse` (works from Linux and macOS). Flash it once with PlatformIO:
  `cd firmware/esp32-mouse && pio run -e esp32dev -t upload` (env per board in `platformio.ini`).
  On the phone it is called "scrcrappy mouse ESP32".

Either way the phone sees a BLE mouse; the phone shows it as the AssistiveTouch
cursor, and scrcrappy steers that cursor to follow your mouse over the window.

1. iPhone: Settings > Accessibility > Touch > AssistiveTouch: on.
2. For `ble` only: `sudo dnf install python3-dbus python3-gobject` (the helper runs under the system python).
3. `.venv/bin/scrcrappy --mouse ble` (or `esp32`), then on the phone pair the mouse
   (AssistiveTouch > Devices > Bluetooth Devices).
4. Optional, once per phone or after changing AssistiveTouch tracking speed: open a plain light
   screen (e.g. Settings) and run `.venv/bin/scrcrappy --mouse ble --calibrate` (or `esp32`).

Click = tap, drag = drag, wheel = scroll (`--natural-scroll` inverts it). The cursor re-syncs in the top-left corner whenever the
mouse enters the window.
