# macOS video capture through AVFoundation

## Problem

On macOS (26.7, Apple Silicon, libusb 1.0.30) the qvh capture cannot work:

1. qvh opens a fresh libusb context per step; after a context that opened devices is closed, the next
   `libusb_init` fails with `-99` (reproduced in plain Go with gousb).
2. With one shared context, claiming the QuickTime interface (`Valeria`, class 255/42) still fails with
   `IOCreatePlugInInterfaceForService: out of resources`, also as root. Every other interface behaves normally.

## Decision

On macOS, do not use qvh. macOS already exposes a trusted iPhone as a muxed capture device (this is what
QuickTime Player uses). Linux keeps qvh unchanged.

Spike (2026-10-21, iPhone 8, iOS 16.7.1): setting `kCMIOHardwarePropertyAllowScreenCaptureDevices` (`'yes '`) in the
process, pumping the CoreFoundation run loop for a moment, then `av.open("iPhone", format="avfoundation",
options={"framerate": "60", "pixel_format": "uyvy422"})` gives 750x1334 frames, first frame after 0.12 s, ~55 fps.

## Design

- `video.capture_avf(out)`: same contract as `video.capture` (context manager yielding an object with `.poll()`
  and `.log`; frames go to a `LatestFrame`), so `__main__` and `app.run` do not change.
- A worker thread: allow screen-capture devices (ctypes, CoreMediaIO), pump the run loop until a device that is not
  `Capture screen N` is listed (device arrival needs the run loop), open it with PyAV, convert each frame to
  rgb24, `out.put`. `BlockingIOError` from the demuxer just means "no frame yet".
- The thread ends on EOF, an error or the stop flag; `.poll()` is `None` while it runs. A timeout with no device
  gives a log line naming the likely causes (phone locked / not trusted, camera permission).
- `__main__`: on darwin there is no qvh lookup and no `reset_if_stuck` (the phone never enters the QuickTime
  config there). `find_iphone` (pyusb) stays: it supplies the serial that keys calibration and settings.
- Camera permission: macOS asks once for the terminal app; the capture asks for it up front.
- Packaging: the Homebrew formula no longer builds qvh (no Go dependency) on macOS.

## Not covered yet

- Several iPhones at once: the device list names them by phone name only; the first one wins.
- Rotation: checked on a real phone after the first version runs.
- The qvh patch fixes (shared libusb context, closing the leaked handle) stay out of this change.
