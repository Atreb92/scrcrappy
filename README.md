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
