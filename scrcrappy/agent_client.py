"""Reference client for the scrcrappy-agent protocol (PROTOCOL.md). Python stdlib only.

scrcrappy vendors this file; keep it self-contained.
"""
import hashlib
import hmac
import json
import os
import secrets
import socket
from pathlib import Path
from typing import Callable

from . import usbmux

PORT = 7330
MAX_FRAME = 16 * 1024 * 1024
KEY_DIR = Path.home() / ".config" / "scrcrappy"


# --- framing: 4-byte big-endian length + UTF-8 JSON object

def encode_frame(obj: dict) -> bytes:
    body = json.dumps(obj, ensure_ascii=False).encode()
    return len(body).to_bytes(4, "big") + body


def read_frame(read: Callable[[int], bytes]) -> dict:
    def exact(n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = read(n - len(data))
            if not chunk:
                raise ConnectionError("agent closed the connection")
            data += chunk
        return data

    length = int.from_bytes(exact(4), "big")
    if length > MAX_FRAME:
        raise ValueError(f"frame too large: {length} bytes")
    return json.loads(exact(length))


# --- keys: a random secret per phone; id and key are derived separately

def host_id(secret: bytes) -> str:
    return hashlib.sha256(b"scrcrappy-id" + secret).hexdigest()


def host_key(secret: bytes) -> bytes:
    return hashlib.sha256(b"scrcrappy-key" + secret).digest()


def pairing_code(secret: bytes) -> str:
    """6 digits shown on the phone and by scrcrappy, so the user can compare them."""
    return f"{int.from_bytes(hashlib.sha256(secret).digest()[:3], 'big') % 1_000_000:06d}"


def auth_mac(secret: bytes, nonce: bytes) -> str:
    return hmac.new(host_key(secret), nonce, hashlib.sha256).hexdigest()


def auth_message(host: str, secret: bytes, nonce: bytes) -> dict:
    return {"cmd": "auth", "host": host, "id": host_id(secret), "mac": auth_mac(secret, nonce)}


def load_secret(udid: str) -> bytes:
    """This computer's secret for the phone `udid`, created (mode 600) on first use."""
    path = KEY_DIR / f"agent-{udid}.key"
    if not path.exists():
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(32))
    return path.read_bytes()


# --- connection

class AgentError(Exception):
    pass


class Agent:
    """One connection to the agent. `hello` is read on connect; call auth() (or pair() first)."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.hello = read_frame(sock.recv)
        self.nonce = bytes.fromhex(self.hello["nonce"])

    @classmethod
    def connect(cls, serial: str | None = None) -> "Agent":
        return cls(usbmux.connect(PORT, serial))

    def request(self, obj: dict) -> dict:
        self.sock.sendall(encode_frame(obj))
        reply = read_frame(self.sock.recv)
        if "error" in reply:
            raise AgentError(reply["error"])
        return reply

    def send(self, obj: dict) -> None:
        """Fire-and-forget (touch)."""
        self.sock.sendall(encode_frame(obj))

    def auth(self, host: str, secret: bytes) -> None:
        self.request(auth_message(host, secret, self.nonce))

    def pair(self, host: str, secret: bytes) -> None:
        """Shows the Allow prompt on the phone; blocks until the user answers (or 30 s)."""
        self.request({"cmd": "pair", "host": host, "secret": secret.hex()})

    def apps(self) -> list[dict]:
        """Openable apps sorted by name: {"id", "name", "pid" (only when running)}."""
        return self.request({"cmd": "apps"})["apps"]

    def open_app(self, bundle_id: str) -> None:
        self.request({"cmd": "open", "id": bundle_id})

    def open_url(self, url: str) -> None:
        """Opens a URL or deeplink, the way tapping a link would."""
        self.request({"cmd": "open_url", "url": url})

    def close(self) -> None:
        self.sock.close()
