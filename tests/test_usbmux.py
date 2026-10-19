import plistlib
import socket
import struct
import threading

import pytest

from scrcrappy import usbmux


def fake_usbmuxd(path, devices, accept_port):
    """Minimal usbmuxd: answers ListDevices, then Connect (ok only for `accept_port`), then echoes."""
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen()

    def serve():
        while True:
            conn, _ = srv.accept()
            while True:
                head = conn.recv(16)
                if not head:
                    break
                length, version, kind, tag = struct.unpack("<IIII", head)
                msg = plistlib.loads(conn.recv(length - 16))
                if msg["MessageType"] == "ListDevices":
                    reply = {"DeviceList": devices}
                else:
                    port = socket.ntohs(msg["PortNumber"])
                    reply = {"MessageType": "Result", "Number": 0 if port == accept_port else 3}
                body = plistlib.dumps(reply)
                conn.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, tag) + body)
                if msg["MessageType"] == "Connect" and reply["Number"] == 0:
                    while data := conn.recv(1024):  # tunnel: echo
                        conn.sendall(data)
                    break

    threading.Thread(target=serve, daemon=True).start()


DEV = {"DeviceID": 7, "Properties": {"SerialNumber": "abc", "ConnectionType": "USB"}}


def test_connect_tunnels_to_device_port(tmp_path, monkeypatch):
    sock_path = tmp_path / "usbmuxd"
    fake_usbmuxd(sock_path, [DEV], accept_port=6000)
    monkeypatch.setattr(usbmux, "SOCKET", str(sock_path))
    s = usbmux.connect(6000)
    s.sendall(b"ping")
    assert s.recv(4) == b"ping"


def test_refused_port_raises(tmp_path, monkeypatch):
    sock_path = tmp_path / "usbmuxd"
    fake_usbmuxd(sock_path, [DEV], accept_port=6000)
    monkeypatch.setattr(usbmux, "SOCKET", str(sock_path))
    with pytest.raises(ConnectionRefusedError, match="6001"):
        usbmux.connect(6001)


def test_no_device_raises(tmp_path, monkeypatch):
    sock_path = tmp_path / "usbmuxd"
    fake_usbmuxd(sock_path, [], accept_port=6000)
    monkeypatch.setattr(usbmux, "SOCKET", str(sock_path))
    with pytest.raises(ConnectionError, match="no iPhone"):
        usbmux.connect(6000)


def test_picks_device_by_serial(tmp_path, monkeypatch):
    sock_path = tmp_path / "usbmuxd"
    other = {"DeviceID": 9, "Properties": {"SerialNumber": "zzz", "ConnectionType": "USB"}}
    fake_usbmuxd(sock_path, [other, DEV], accept_port=6000)
    monkeypatch.setattr(usbmux, "SOCKET", str(sock_path))
    assert usbmux.devices() == {"zzz": 9, "abc": 7}
