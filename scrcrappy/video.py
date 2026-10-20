"""Phone screen capture: qvh (QuickTime USB protocol) -> named pipe -> PyAV decode; on macOS AVFoundation instead."""
import contextlib
import ctypes
import ctypes.util
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO, Callable, Iterable, Iterator

import av
import usb.backend.libusb1
import usb.core
import usb.util

APPLE = 0x05AC
Frame = tuple[bytes, tuple[int, int], int]  # RGB pixels, (width, height), bytes per row


class LatestFrame:
    """Hands the newest decoded frame to the UI; older undrawn frames are dropped."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: Frame | None = None
        self._newest: Frame | None = None

    def put(self, frame: Frame) -> None:
        with self._lock:
            self._frame = self._newest = frame

    def get(self) -> Frame | None:
        """Newest frame, or None if nothing new since the last call."""
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def peek(self) -> Frame | None:
        """Newest frame, whether or not get() already took it (calibration while the window runs)."""
        with self._lock:
            return self._newest


HOMEBREW_LIBS = ("/opt/homebrew/lib", "/usr/local/lib")  # Apple Silicon, Intel


def libusb_path(name: str, find=ctypes.util.find_library, exists=os.path.exists) -> str | None:
    """pyusb's libusb lookup, plus Homebrew's folders, which ctypes doesn't search on macOS."""
    return find(name) or next((p for d in HOMEBREW_LIBS if exists(p := f"{d}/lib{name}.dylib")), None)


def find_iphone() -> usb.core.Device | None:
    return usb.core.find(idVendor=APPLE, backend=usb.backend.libusb1.get_backend(find_library=libusb_path))


def serial_number(dev: usb.core.Device) -> str:
    """Reading it opens the phone through libusb; on macOS let go again, or no video comes while it is held."""
    serial = dev.serial_number
    if sys.platform == "darwin":
        usb.util.dispose_resources(dev)
    return serial


def reset_if_stuck(dev: usb.core.Device) -> None:
    """qvh can't switch the phone back out of the QuickTime config on Linux (usbmuxd holds it),
    and the next session then never gets the device's PING. A USB reset re-enumerates it."""
    try:
        cfg = dev.get_active_configuration()
    except usb.core.USBError:
        return
    if any(i.bInterfaceClass == 0xFF and i.bInterfaceSubClass == 0x2A for i in cfg):
        with contextlib.suppress(usb.core.USBError):  # device vanishes mid-call while resetting
            dev.reset()
        time.sleep(3)


def publish(frame: av.VideoFrame, out: LatestFrame) -> None:
    plane = frame.reformat(format="rgb24").planes[0]
    out.put((bytes(plane), (frame.width, frame.height), plane.line_size))


def decode(stream: BinaryIO, out: LatestFrame) -> None:
    """Decode an Annex-B H.264 byte stream until EOF, publishing each frame to `out`."""
    codec = av.CodecContext.create("h264", "r")
    codec.flags |= av.codec.context.Flags.low_delay
    while chunk := stream.read(65536):
        for packet in codec.parse(chunk):
            for frame in codec.decode(packet):
                publish(frame, out)


@contextlib.contextmanager
def capture(qvh: str, out: LatestFrame) -> Iterator[subprocess.Popen]:
    """Run `qvh record` into a named pipe and decode it in a background thread."""
    tmp = tempfile.mkdtemp(prefix="scrcrappy-")
    fifo, log_path = os.path.join(tmp, "video.h264"), os.path.join(tmp, "qvh.log")
    os.mkfifo(fifo)
    with open(log_path, "wb") as log:
        proc = subprocess.Popen([qvh, "record", fifo, os.devnull], stdout=log, stderr=log)
    proc.log = ""

    def reader() -> None:
        with open(fifo, "rb", buffering=0) as f:
            decode(f, out)

    threading.Thread(target=reader, daemon=True).start()
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)  # qvh then tells the phone to stop streaming
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        with open(log_path, errors="replace") as f:
            proc.log = f.read()[-1000:]  # for the error message; the folder doesn't outlive the run
        shutil.rmtree(tmp, ignore_errors=True)


# macOS: the phone is a muxed capture device once CoreMediaIO is told to allow screen-capture devices (what
# QuickTime Player does). qvh cannot claim the QuickTime USB interface there.

def parse_video_devices(lines: Iterable[str]) -> list[str]:
    """Names from ffmpeg's `list_devices` output, video section only."""
    names, in_video = [], False
    for line in lines:
        if line.startswith("AVFoundation "):
            in_video = "video" in line
        elif in_video and line.startswith("[") and "] " in line:
            names.append(line.split("] ", 1)[1].strip())
    return names


def pick_iphone(phones: dict[str, str], serial: str) -> str | None:
    """`phones` maps name -> uniqueID of the muxed capture devices. The ID holds the phone's USB serial (dashes
    aside); if none matches but only one phone is plugged in, that one is it."""
    plain = lambda text: text.replace("-", "").casefold()  # noqa: E731
    match = next((n for n, uid in phones.items() if plain(serial) in plain(uid)), None)
    return match or (next(iter(phones)) if len(phones) == 1 else None)


def muxed_devices() -> dict[str, str]:
    """name -> uniqueID of AVFoundation's muxed devices (iPhones); ffmpeg's listing carries no IDs."""
    ctypes.CDLL("/System/Library/Frameworks/AVFoundation.framework/AVFoundation")
    objc = ctypes.CDLL(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = objc.sel_registerName.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def msg(obj, sel: bytes, *args, restype=ctypes.c_void_p, argtypes=()):
        objc.objc_msgSend.restype, objc.objc_msgSend.argtypes = restype, [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
        return objc.objc_msgSend(obj, objc.sel_registerName(sel), *args)

    def text(ns) -> str:
        return msg(ns, b"UTF8String", restype=ctypes.c_char_p).decode()

    muxed = msg(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:", b"muxx", argtypes=[ctypes.c_char_p])  # AVMediaTypeMuxed
    found = msg(objc.objc_getClass(b"AVCaptureDevice"), b"devicesWithMediaType:", muxed, argtypes=[ctypes.c_void_p])
    devices = (msg(found, b"objectAtIndex:", i, argtypes=[ctypes.c_ulong]) for i in range(msg(found, b"count", restype=ctypes.c_ulong)))
    return {text(msg(d, b"localizedName")): text(msg(d, b"uniqueID")) for d in devices}


def find_phones() -> dict[str, str]:
    """The muxed devices, once ffmpeg's listing (which also lets macOS deliver arrivals) shows them."""
    ids = muxed_devices() if (names := list_devices()) else {}
    return {n: ids[n] for n in names if n in ids}


def _run_loop(seconds: float) -> None:
    """Device arrivals are delivered through the CoreFoundation run loop of the calling thread."""
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]
    cf.CFRunLoopRunInMode(ctypes.c_void_p.in_dll(cf, "kCFRunLoopDefaultMode"), seconds, False)


_allowed = False


def _allow_screen_capture_devices() -> None:
    """Set once per process: a repeat was never tried, so one success is enough; a failure is retried."""
    global _allowed
    if _allowed:
        return

    class Address(ctypes.Structure):
        _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]

    cmio = ctypes.CDLL("/System/Library/Frameworks/CoreMediaIO.framework/CoreMediaIO")
    cmio.CMIOObjectSetPropertyData.argtypes = [ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32,
                                               ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    address = Address(*(struct.unpack(">I", c.encode())[0] for c in ("yes ", "glob")), 0)  # ...AllowScreenCaptureDevices
    status = cmio.CMIOObjectSetPropertyData(1, ctypes.byref(address), 0, None, 4, ctypes.byref(ctypes.c_uint32(1)))  # 1 = system object
    _allowed = status == 0


def list_devices() -> list[str]:
    _allow_screen_capture_devices()
    _run_loop(0.5)
    level = av.logging.get_level()
    av.logging.set_level(av.logging.INFO)  # ffmpeg prints the list at info level
    try:
        with av.logging.Capture() as logs:
            with contextlib.suppress(OSError):  # ffmpeg exits with an error after listing
                av.open("", format="avfoundation", options={"list_devices": "true"})
    finally:
        av.logging.set_level(level)
    return parse_video_devices(message for _, _, message in logs)


STALL = 5  # seconds without a frame before the stream counts as dead


def open_iphone(name: str, stop: threading.Event) -> Iterator[av.VideoFrame]:
    container = av.open(name, format="avfoundation", timeout=15,
                        options={"framerate": "60", "pixel_format": "uyvy422"})
    try:
        stream = container.streams.video[0]
        last = time.monotonic()
        while not stop.is_set():
            try:
                packet = next(container.demux(stream))
            except BlockingIOError:  # no frame ready yet
                if time.monotonic() - last > STALL:
                    raise TimeoutError(f"no video from the phone for {STALL} s (unplugged or locked?)") from None
                time.sleep(0.005)
                continue
            except StopIteration:
                return
            last = time.monotonic()
            yield from packet.decode()
    finally:
        container.close()


class AvfCapture:
    """What `capture_avf` yields: the same `poll()` / `log` as the qvh process."""

    def __init__(self) -> None:
        self.log = ""
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None

    def poll(self) -> int | None:
        return None if self.thread and self.thread.is_alive() else 0


@contextlib.contextmanager
def capture_avf(out: LatestFrame, serial: str, wait: float = 15, devices: Callable[[], dict[str, str]] = find_phones,
                open_source: Callable[[str, threading.Event], Iterable[av.VideoFrame]] = open_iphone) -> Iterator[AvfCapture]:
    cap = AvfCapture()
    # The phone only shows up when it is looked for from the thread that runs the program's main run loop,
    # so this waits here, not in the streaming thread.
    deadline, name, told = time.monotonic() + wait, None, False
    while not (name := pick_iphone(devices(), serial)) and time.monotonic() < deadline:
        if not told:
            print("waiting for the iPhone (unlock it, tap Trust if asked)...", file=sys.stderr)
            told = True
        time.sleep(0.01)
    if not name:
        cap.log = ("no iPhone found by macOS: unlock it, trust this Mac, and allow camera access for this "
                   "terminal app in System Settings > Privacy & Security > Camera")
        yield cap
        return

    def run() -> None:
        try:
            for frame in open_source(name, cap.stop):
                if cap.stop.is_set():
                    break
                publish(frame, out)
            if not cap.stop.is_set():
                cap.log = "the phone stopped sending video (unplugged or locked?)"
        except Exception as e:  # noqa: BLE001 - whatever ended the stream goes to the error message
            cap.log = f"{type(e).__name__}: {e}"

    cap.thread = threading.Thread(target=run, daemon=True)
    cap.thread.start()
    try:
        yield cap
    finally:
        cap.stop.set()
        cap.thread.join(timeout=5)
