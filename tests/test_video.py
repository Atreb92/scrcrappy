import io
import threading
import time

import av
import pytest

from scrcrappy.geometry import fit
from scrcrappy import video
from scrcrappy.video import LatestFrame, decode


def h264(frames: int, w: int, h: int) -> bytes:
    buf = io.BytesIO()
    with av.open(buf, "w", format="h264") as out:
        stream = out.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
        for _ in range(frames):
            out.mux(stream.encode(av.VideoFrame(w, h, "yuv420p")))
        out.mux(stream.encode())
    return buf.getvalue()


def test_latest_frame_drops_old():
    f = LatestFrame()
    f.put((b"a", (1, 1), 3))
    f.put((b"b", (1, 1), 3))
    assert f.get()[0] == b"b"
    assert f.get() is None


def test_decode_publishes_rgb_frames():
    out = LatestFrame()
    decode(io.BytesIO(h264(5, 64, 48)), out)
    pixels, size, pitch = out.get()
    assert size == (64, 48)
    assert pitch >= 64 * 3 and len(pixels) >= pitch * 47 + 64 * 3


def test_fit_letterboxes_tall_frame():
    assert fit((1125, 2436), (1000, 1000)) == (269, 0, 462, 1000)


def test_fit_pillarboxes_wide_window():
    assert fit((750, 1334), (375, 667)) == (0, 0, 375, 667)
    assert fit((1334, 750), (1000, 1000)) == (0, 219, 1000, 562)


def test_libusb_found_in_homebrew_when_the_system_search_misses():
    # macOS: ctypes.util.find_library doesn't look in /opt/homebrew/lib, so pyusb found no backend
    from scrcrappy import video
    assert video.libusb_path("usb-1.0", find=lambda n: None,
                             exists=lambda p: p == "/opt/homebrew/lib/libusb-1.0.dylib") == "/opt/homebrew/lib/libusb-1.0.dylib"
    assert video.libusb_path("usb-1.0", find=lambda n: "/usr/lib/libusb-1.0.so.0", exists=lambda p: False) == "/usr/lib/libusb-1.0.so.0"
    assert video.libusb_path("usb-1.0", find=lambda n: None, exists=lambda p: False) is None


def test_peek_sees_the_newest_frame_even_after_the_window_took_it():
    # calibrating inside the running app: the window loop get()s every frame, calibration still needs the newest
    from scrcrappy.video import LatestFrame
    frames = LatestFrame()
    assert frames.peek() is None
    frames.put((b"a", (1, 1), 3))
    assert frames.get() == (b"a", (1, 1), 3)
    assert frames.peek() == (b"a", (1, 1), 3) and frames.get() is None


AVF_LISTING = ["AVFoundation video devices:\n", "[0] iPhone\n", "[1] Capture screen 0\n",
               "AVFoundation audio devices:\n", "[0] ZoomAudioDevice\n"]


def test_parse_video_devices_ignores_the_audio_section():
    assert video.parse_video_devices(AVF_LISTING) == ["iPhone", "Capture screen 0"]


def test_pick_iphone_matches_the_usb_serial():
    phones = {"Ann's iPhone": "00008020-001A2B3C4D5E", "Bob's iPhone": "00008110-00FF"}
    assert video.pick_iphone(phones, "00008110-00ff") == "Bob's iPhone"
    assert video.pick_iphone(phones, "00008110" + "00FF") == "Bob's iPhone"  # dashes don't matter


def test_pick_iphone_falls_back_to_the_only_phone_and_never_guesses_between_two():
    assert video.pick_iphone({"My iPhone": "opaque-id"}, "abc") == "My iPhone"
    assert video.pick_iphone({"A": "x", "B": "y"}, "abc") is None
    assert video.pick_iphone({}, "abc") is None


def source(frames: int):
    def open_source(name: str, stop):
        assert name == "iPhone"
        for _ in range(frames):
            yield av.VideoFrame(64, 48, "uyvy422")
    return open_source


def wait_done(proc) -> None:
    for _ in range(200):
        if proc.poll() is not None:
            return
        time.sleep(0.01)
    raise AssertionError("capture did not stop")


def test_capture_avf_publishes_rgb_frames_and_stops_at_the_end_of_the_stream():
    out = LatestFrame()
    with video.capture_avf(out, "s", devices=lambda: {"iPhone": "s"}, open_source=source(3)) as proc:
        wait_done(proc)
    pixels, size, pitch = out.peek()
    assert size == (64, 48) and pitch >= 64 * 3 and len(pixels) >= pitch * 47 + 64 * 3


def test_capture_avf_without_a_phone_says_why():
    with video.capture_avf(LatestFrame(), "s", wait=0.05, devices=lambda: {}, open_source=source(0)) as proc:
        wait_done(proc)
    assert "no iPhone" in proc.log and "camera" in proc.log


def test_capture_avf_stops_a_running_stream_on_exit():
    def endless(name, stop):
        while True:
            yield av.VideoFrame(64, 48, "uyvy422")
            time.sleep(0.001)
    with video.capture_avf(LatestFrame(), "s", devices=lambda: {"iPhone": "s"}, open_source=endless) as proc:
        time.sleep(0.05)
        assert proc.poll() is None
    assert proc.poll() is not None


def test_list_devices_reads_ffmpegs_info_level_listing(monkeypatch):
    def fake_open(name, format, options):  # ffmpeg prints the list at info level, then exits with an error
        for line in AVF_LISTING:
            av.logging.log(av.logging.INFO, "avfoundation", line)
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(video, "_allow_screen_capture_devices", lambda: None)
    monkeypatch.setattr(video, "_run_loop", lambda seconds: None)
    monkeypatch.setattr(video.av, "open", fake_open)
    av.logging.set_level(av.logging.WARNING)  # PyAV's usual default: info messages are dropped
    assert video.list_devices() == ["iPhone", "Capture screen 0"]
    assert av.logging.get_level() == av.logging.WARNING  # put back


class FakeDev:
    def __init__(self, calls):
        self.calls = calls

    @property
    def serial_number(self):
        self.calls.append("read")
        return "abc"


def test_serial_number_lets_go_of_the_phone_on_macos(monkeypatch):
    calls = []
    monkeypatch.setattr(video.sys, "platform", "darwin")
    monkeypatch.setattr(video.usb.util, "dispose_resources", lambda dev: calls.append("dispose"))
    assert video.serial_number(FakeDev(calls)) == "abc"
    assert calls == ["read", "dispose"]  # libusb would keep the phone open, and macOS then sends no video


def test_serial_number_leaves_the_phone_alone_on_linux(monkeypatch):
    calls = []
    monkeypatch.setattr(video.sys, "platform", "linux")
    monkeypatch.setattr(video.usb.util, "dispose_resources", lambda dev: calls.append("dispose"))
    assert video.serial_number(FakeDev(calls)) == "abc"
    assert calls == ["read"]


def test_allow_screen_capture_devices_is_retried_until_it_succeeds(monkeypatch):
    results, calls = iter([1, 0, 0]), []

    def set_property(*args):
        calls.append(1)
        return next(results)

    cmio = type("Cmio", (), {"CMIOObjectSetPropertyData": staticmethod(set_property)})()

    monkeypatch.setattr(video, "_allowed", False)
    monkeypatch.setattr(video.ctypes, "CDLL", lambda path: cmio)
    for _ in range(3):
        video._allow_screen_capture_devices()
    assert len(calls) == 2  # the failed call is repeated, the successful one is not


def test_capture_avf_keeps_looking_for_the_phone():
    seen = iter([{}, {}, {"iPhone": "s"}])
    out = LatestFrame()
    with video.capture_avf(out, "s", devices=lambda: next(seen), open_source=source(2)) as proc:
        wait_done(proc)
    assert out.peek() is not None


def test_capture_avf_a_stream_that_just_ends_still_explains_itself():
    with video.capture_avf(LatestFrame(), "s", devices=lambda: {"iPhone": "s"}, open_source=source(2)) as proc:
        wait_done(proc)
    assert "stopped sending video" in proc.log


def test_capture_avf_reports_why_a_stream_failed():
    def broken(name, stop):
        raise RuntimeError("camera busy")
        yield  # a generator, like the real source

    with video.capture_avf(LatestFrame(), "s", devices=lambda: {"iPhone": "s"}, open_source=broken) as proc:
        wait_done(proc)
    assert proc.log == "RuntimeError: camera busy"


class FakeContainer:
    """av.open's result when ffmpeg never has a frame ready (phone unplugged, locked)."""

    def __init__(self):
        self.closed = False
        self.streams = type("S", (), {"video": [object()]})()

    def demux(self, stream):
        raise BlockingIOError

    def close(self):
        self.closed = True


def test_open_iphone_gives_up_when_no_frame_comes(monkeypatch):
    box = FakeContainer()
    monkeypatch.setattr(video.av, "open", lambda *a, **k: box)
    monkeypatch.setattr(video, "STALL", 0.05)
    with pytest.raises(TimeoutError, match="no video"):
        next(video.open_iphone("iPhone", threading.Event()))
    assert box.closed


def test_open_iphone_stops_when_asked_even_without_frames(monkeypatch):
    box, stop = FakeContainer(), threading.Event()
    monkeypatch.setattr(video.av, "open", lambda *a, **k: box)
    stop.set()
    assert list(video.open_iphone("iPhone", stop)) == []
    assert box.closed
