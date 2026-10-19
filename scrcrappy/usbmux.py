"""TCP to a port on the iPhone over USB, through the system's usbmuxd (Linux and macOS both run one).

usbmuxd protocol: 16-byte little-endian header (length incl. header, version 1, type 8 = plist, tag)
followed by an XML plist. After a successful Connect the same socket is a raw tunnel to the port.
"""
import plistlib
import socket
import struct

SOCKET = "/var/run/usbmuxd"
TIMEOUT = 5.0  # s for usbmuxd to answer; it can wedge (phone locked after a reboot, pairing stuck)
_CLIENT = {"ClientVersionString": "scrcrappy", "ProgName": "scrcrappy"}


def _call(sock: socket.socket, message: dict) -> dict:
    body = plistlib.dumps({**message, **_CLIENT})
    try:
        sock.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, 1) + body)
        length = struct.unpack("<IIII", _exact(sock, 16))[0]
        return plistlib.loads(_exact(sock, length - 16))
    except TimeoutError:
        raise TimeoutError(f"usbmuxd didn't answer within {TIMEOUT:g} s: unlock the phone (and tap Trust if it "
                           "asks), or unplug and replug it") from None


def _exact(sock: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("usbmuxd closed the connection")
        data += chunk
    return data


def _open() -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    sock.connect(SOCKET)
    return sock


def devices() -> dict[str, int]:
    """USB-connected iPhones: serial (UDID) -> usbmuxd device id."""
    with _open() as sock:
        reply = _call(sock, {"MessageType": "ListDevices"})
    return {d["Properties"]["SerialNumber"]: d["DeviceID"] for d in reply.get("DeviceList", [])
            if d["Properties"].get("ConnectionType") == "USB"}


def connect(port: int, serial: str | None = None) -> socket.socket:
    """A socket connected to `port` on the phone (the one with `serial`, else the first one)."""
    found = devices()
    if not found:
        raise ConnectionError("no iPhone connected over USB")
    device_id = found[serial] if serial else next(iter(found.values()))
    sock = _open()
    reply = _call(sock, {"MessageType": "Connect", "DeviceID": device_id, "PortNumber": socket.htons(port)})
    if reply.get("Number") != 0:
        sock.close()
        raise ConnectionRefusedError(f"nothing is listening on port {port} on the iPhone (usbmuxd result "
                                     f"{reply.get('Number')})")
    sock.settimeout(None)  # now a tunnel to the phone: replies may legitimately take long (pairing prompt)
    return sock
