import socket

import pytest

from scrcrappy.zxtouch import DOWN, MOVE, UP, ZXTouch, ZXTouchError, encode, encode_touch


def pair(reply: bytes = b""):
    a, b = socket.socketpair()
    b.sendall(reply)
    return ZXTouch(a), b


def received(peer) -> bytes:
    peer.settimeout(0.2)
    data = b""
    try:
        while chunk := peer.recv(4096):
            data += chunk
    except socket.timeout:
        pass
    return data


def test_encode_glues_task_to_first_arg():
    assert encode(25, 1) == b"251\r\n"
    assert encode(24, 1, "a") == b"241;;a\r\n"


def test_encode_touch_single_down():
    assert encode_touch([(DOWN, 1, 187.5, 406.0)]) == b"1011010187504060\r\n"


def test_encode_touch_two_fingers():
    assert encode_touch([(MOVE, 1, 10, 20), (MOVE, 2, 30, 40)]) == b"10220100100002002020030000400\r\n"


def test_touch_sends_without_waiting_for_a_reply():
    z, peer = pair()
    z.touch([(UP, 1, 1, 2)])
    assert received(peer) == b"1010010001000020\r\n"


def test_screen_size_parses_reply():
    z, peer = pair(b"0;;375;;812\r\n")
    assert z.screen_size() == (375.0, 812.0)
    assert received(peer) == b"251\r\n"


def test_error_reply_raises():
    z, _ = pair(b"-1;;nope\r\n")
    with pytest.raises(ZXTouchError, match="nope"):
        z.orientation()


def test_screenshot_reads_exact_bytes_and_keeps_the_rest():
    z, _ = pair(b"0;;image/jpeg;;3\r\nabc0;;1\r\n")
    assert z.screenshot() == b"abc"
    assert z.orientation() == 1


def test_insert_text_one_char_per_command():
    # ';;' is the field separator: a ';' must never end up next to another inside one command
    z, peer = pair(b"0\r\n" * 4)
    z.insert_text("è;;\r\n")
    assert received(peer) == "241;;è\r\n241;;;\r\n241;;;\r\n241;;\n\r\n".encode()


def test_delete_backward():
    z, peer = pair(b"0\r\n")
    z.delete_backward(2)
    assert received(peer) == b"244;;2\r\n"


def test_connection_closed_mid_reply_raises():
    z, peer = pair(b"0;;37")
    peer.close()
    with pytest.raises(ZXTouchError, match="closed"):
        z.screen_size()


def test_connection_reset_while_reading_raises():
    class Reset:
        def sendall(self, data):
            pass

        def recv(self, n):
            raise ConnectionResetError("phone unplugged")

    with pytest.raises(ZXTouchError, match="closed"):
        ZXTouch(Reset()).orientation()
