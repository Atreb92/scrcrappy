"""Client for the ZXTouch tweak's TCP protocol (jailbroken phone, device port 6000).

Wire format, from gitssie/zxtouchrootless (pccontrol/ + its python client):
request  "<task><arg1>;;<arg2>…\\r\\n" (task id glued to the first argument)
reply    "0;;field;;field\\r\\n" (ok) or "-1;;message\\r\\n" (error); touch commands get no reply.
"""
import socket

UP, DOWN, MOVE = 0, 1, 2
TASK_TOUCH, TASK_KEYBOARD, TASK_DEVICE_INFO, TASK_SCREENSHOT = 10, 24, 25, 30
KBD_INSERT, KBD_DELETE = 1, 4
INFO_SCREEN_SIZE, INFO_ORIENTATION = 1, 2


class ZXTouchError(Exception):
    pass


def encode(task: int, *args) -> bytes:
    return (str(task) + ";;".join(str(a) for a in args) + "\r\n").encode()


def encode_touch(events: list[tuple[int, int, float, float]]) -> bytes:
    """(type, finger 1-19, x, y) events in one command; x/y in the screen-size units, 0.1 resolution."""
    body = "".join(f"{kind}{finger:02d}{int(x * 10):05d}{int(y * 10):05d}" for kind, finger, x, y in events)
    return encode(TASK_TOUCH, f"{len(events)}{body}")


class ZXTouch:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buf = bytearray()

    def _send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise ZXTouchError("connection closed by the phone") from e

    def _recv(self, n: int) -> bytes:
        try:
            chunk = self.sock.recv(n)
        except OSError as e:
            raise ZXTouchError("connection closed by the phone") from e
        if not chunk:
            raise ZXTouchError("connection closed by the phone")
        return chunk

    def _line(self) -> bytes:
        while (end := self.buf.find(b"\r\n")) < 0:
            self.buf += self._recv(4096)
        line = bytes(self.buf[:end])
        del self.buf[: end + 2]
        return line

    def _exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self._recv(n - len(self.buf))
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data

    def _request(self, task: int, *args) -> list[str]:
        self._send(encode(task, *args))
        status, *fields = self._line().decode(errors="replace").split(";;")
        if status != "0":
            raise ZXTouchError(fields[0] if fields else "ZXTouch error without a message")
        return fields

    def touch(self, events: list[tuple[int, int, float, float]]) -> None:
        self._send(encode_touch(events))

    def screen_size(self) -> tuple[float, float]:
        w, h = self._request(TASK_DEVICE_INFO, INFO_SCREEN_SIZE)[:2]
        return float(w), float(h)

    def orientation(self) -> int:
        return int(self._request(TASK_DEVICE_INFO, INFO_ORIENTATION)[0])

    def insert_text(self, text: str) -> None:
        """Type into the focused text field. One character per command, so the ';;' separator can't
        form inside an argument; '\\r' is dropped."""
        for c in text.replace("\r", ""):
            self._request(TASK_KEYBOARD, KBD_INSERT, c)

    def delete_backward(self, n: int = 1) -> None:
        self._request(TASK_KEYBOARD, KBD_DELETE, n)

    def screenshot(self) -> bytes:
        """JPEG of the screen: header "0;;image/jpeg;;<length>" then exactly that many bytes."""
        self._send(encode(TASK_SCREENSHOT))
        status, *fields = self._line().decode(errors="replace").split(";;")
        if status != "0" or len(fields) != 2:
            raise ZXTouchError(fields[0] if fields else "bad screenshot reply")
        return self._exact(int(fields[1]))

    def close(self) -> None:
        self.sock.close()
