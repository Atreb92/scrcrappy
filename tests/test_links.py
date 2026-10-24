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
