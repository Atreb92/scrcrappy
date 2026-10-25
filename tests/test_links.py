import os
import threading

import pytest

from scrcrappy import links


def fake_board(master: int, received: list[bytes], boot_lines: int = 0) -> None:
    """Pretends to be the firmware on the other end of a pty: ignores the first `boot_lines`
    queries (board rebooting after port open), then answers like the real thing."""
    buf = b""
    while True:
        try:
            buf += os.read(master, 1024)
        except OSError:
            return
        *lines, buf = buf.split(b"\n")
        for line in lines:
            received.append(line)
            if line == b"?":
                if boot_lines:
                    boot_lines -= 1
                else:
                    os.write(master, b"ready\nconnected\n")


def test_esp32_handshake_and_reports():
    master, slave = os.openpty()
    received = []
    threading.Thread(target=fake_board, args=(master, received, 2), daemon=True).start()
    link = links.esp32(os.ttyname(slave))
    assert link.connected.wait(2)
    link.send(-5, 12, 1, 0)
    for _ in range(100):
        if received[-1:] == [b"-5 12 1 0"]:
            break
        threading.Event().wait(0.01)
    assert received[-1] == b"-5 12 1 0"
    assert received.count(b"?") == 3  # retried through the "reboot"


def test_esp32_close_stops_the_reader_and_releases_the_port():
    master, slave = os.openpty()
    threading.Thread(target=fake_board, args=(master, [], 2), daemon=True).start()
    link = links.esp32(os.ttyname(slave))
    before = threading.active_count()
    link.close()
    for _ in range(100):
        if threading.active_count() < before:
            break
        threading.Event().wait(0.01)
    assert threading.active_count() < before  # the reader thread left its select loop
    link.send(1, 2, 0, 0)  # writing to the closed port is swallowed, not a crash


def test_esp32_silent_port_is_an_error():
    master, slave = os.openpty()
    with pytest.raises(RuntimeError, match="no scrcrappy ESP32 firmware"):
        links.esp32(os.ttyname(slave), wait=1)


def test_link_handles_lines_split_across_reads():
    chunks = iter([b"rea", b"dy\ncon", b"nected\n", b""])
    link = links.Link(lambda b: None, lambda: next(chunks))
    assert link.ready.wait(1) and link.connected.wait(1)


def test_send_keys_pads_to_six_slots():
    out = []
    link = links.Link(out.append, lambda: b"")
    link.send_keys(0x02, [0x04, 0x05])
    assert out == [b"k 2 4 5 0 0 0 0\n"]


def feed(*chunks: bytes) -> links.Link:
    """A Link whose reader gets `chunks` and then EOF; the reader thread is joined by waiting on its end."""
    queue, done = list(chunks), threading.Event()

    def read() -> bytes:
        if queue:
            return queue.pop(0)
        done.set()
        return b""

    link = links.Link(lambda b: None, read)
    done.wait(2)
    threading.Event().wait(0.05)
    return link


def test_snapshot_fills_state():
    link = feed(b"ready\npaired 3F:A2\nconnected\npeer 3F:A2 My iPhone\n")
    assert link.paired is True and link.peer == ("3F:A2", "My iPhone") and link.connected.is_set()
    assert link.last_seen > 0


def test_unpaired_snapshot():
    assert feed(b"ready\nunpaired\n").paired is False


def test_disconnected_clears_connected():
    assert not feed(b"ready\nconnected\ndisconnected\n").connected.is_set()


def test_ready_resets_state():
    link = feed(b"ready\npaired 3F:A2\nconnected\npeer 3F:A2 x\n", b"ready\n")
    assert link.paired is None and link.peer is None and not link.connected.is_set()


def test_empty_peer_name():
    assert feed(b"ready\nconnected\npeer 3F:A2\n").peer == ("3F:A2", "")


def test_pairing_calls_hook():
    calls = []
    queue = [b"pairing\n"]

    def read() -> bytes:
        return queue.pop(0) if queue else b""

    link = links.Link(lambda b: None, read, on_pairing=lambda: calls.append(1))
    threading.Event().wait(0.1)
    assert calls == [1] and link.on_pairing is not None


def test_query_and_forget_write_lines():
    written = []
    link = links.Link(written.append, lambda: b"")
    link.query()
    link.forget()
    assert written == [b"?\n", b"p\n"]


class _Pipe:
    closed = False

    def write(self, b):
        return len(b)

    def close(self):
        self.closed = True


class _Out:
    def __init__(self):
        self.first = True

    def read(self, n):
        out, self.first = (b"ready\n" if self.first else b""), False
        return out


class _Proc:
    def __init__(self, stubborn=False):
        self.stdin, self.stdout, self.stubborn, self.waited, self.killed = _Pipe(), _Out(), stubborn, [], False

    def wait(self, timeout=None):
        self.waited.append(timeout)
        if self.stubborn and not self.killed:
            raise links.subprocess.TimeoutExpired("blemouse", timeout)

    def kill(self):
        self.killed = True


def test_ble_close_ends_the_helper(monkeypatch):
    proc = _Proc()
    monkeypatch.setattr(links.subprocess, "Popen", lambda *a, **k: proc)
    links.ble("python3").close()
    assert proc.stdin.closed and proc.waited and not proc.killed


def test_ble_close_kills_a_helper_that_will_not_exit(monkeypatch):
    proc = _Proc(stubborn=True)
    monkeypatch.setattr(links.subprocess, "Popen", lambda *a, **k: proc)
    links.ble("python3").close()
    assert proc.killed


def test_open_serial_sets_raw_mode_and_baud():
    import termios
    master, slave = os.openpty()
    fd = links.open_serial(os.ttyname(slave))
    try:
        attrs = termios.tcgetattr(fd)
        assert attrs[4] == attrs[5] == termios.B115200 and not attrs[3] & termios.ECHO
    finally:
        os.close(fd)
        os.close(master)


def test_open_serial_missing_port_raises_oserror():
    with pytest.raises(OSError):
        links.open_serial("/nonexistent/ttyUSB9")


def test_open_serial_turns_termios_errors_into_oserror_and_closes_the_fd(monkeypatch):
    import termios
    master, slave = os.openpty()
    opened = []
    real_open = os.open
    monkeypatch.setattr(links.os, "open", lambda *a, **k: opened.append(real_open(*a, **k)) or opened[-1])
    monkeypatch.setattr(links.tty, "setraw", lambda fd: (_ for _ in ()).throw(termios.error(25, "Inappropriate ioctl")))
    with pytest.raises(OSError, match="cannot configure"):
        links.open_serial(os.ttyname(slave))
    with pytest.raises(OSError):
        os.fstat(opened[0])  # closed
    os.close(master)


def test_fw_line_sets_firmware_and_is_part_of_the_snapshot():
    link = feed(b"ready\nfw debug Oct 25 2026 21:00:00\npaired 3F:A2\n")
    assert link.firmware == "debug Oct 25 2026 21:00:00"
    assert feed(b"ready\npaired 3F:A2\n").firmware == ""  # an older firmware has no such line
