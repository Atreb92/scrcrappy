"""The input modes (None / BT / ESP32 / Agent) as bundles the launcher and the window both start the same way."""
import logging
import socket
import sys
from dataclasses import dataclass
from typing import Callable

from . import agent, calibrate, diagnose, links, mouse
from .calibrate import Calibrator
from .keyqueue import KeyQueue
from .links import Link
from .video import LatestFrame

log = logging.getLogger("scrcrappy.modes")
LABELS = {"none": "None", "ble": "BT", "esp32": "ESP32", "agent": "Agent"}


class ModeError(RuntimeError):
    """A mode could not start; the message is what the user is told."""


@dataclass
class Mode:
    name: str
    make_pointer: Callable[[tuple[int, int]], mouse.Pointer] | None = None
    keys: KeyQueue | None = None
    session: agent.Session | None = None
    calibrator: Calibrator | None = None
    link: Link | None = None
    device_name: str = "scrcrappy PC"
    closed: bool = False
    error: str = ""  # ESP32 only: why the board isn't usable (the mode still runs, so Settings can fix the port)

    @property
    def board(self) -> Link | None:
        return self.link if self.name == "esp32" else None

    @property
    def connected(self) -> Callable[[], bool]:
        return self.link.connected.is_set if self.link else (lambda: True)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        log.info("closing mode %s", self.name)
        if self.keys:
            self.keys.stop()
        if self.link:
            self.link.close()
        if self.session:
            self.session.close()


def _why(port: str, e: Exception) -> str:
    hint = diagnose.HINTS.get(getattr(e, "errno", None), "").split(" (")[0]
    return f"{port}: {hint}" if hint else str(e)


def selectable(name: str, platform: str | None = None) -> bool:
    """The Linux Bluetooth adapter helper doesn't exist on macOS."""
    return not (name == "ble" and (platform or sys.platform) == "darwin")


def start_mode(name: str, port: str, serial: str, frames: LatestFrame, ble_python: str = "/usr/bin/python3") -> Mode:
    """Start input mode `name` for the phone `serial`; raises ModeError (with nothing left open) if it can't."""
    log.info("starting mode %s", name)
    if name == "none":
        return Mode("none")
    if name == "agent":
        try:
            host = socket.gethostname()
            return Mode("agent", session=agent.Session(agent.connect(host).sock,
                                                       reopen=lambda: agent.connect(host, wait=1).sock))
        except (OSError, agent.AgentError) as e:
            log.error("mode agent failed to start", exc_info=True)
            raise ModeError(f"agent: {e}") from e
    if not selectable(name):
        log.error("mode %s is not available on this platform", name)
        raise ModeError("Bluetooth mouse needs Linux: use ESP32 or Agent on macOS")
    try:
        link = links.ble(ble_python) if name == "ble" else links.esp32(port)
    except (OSError, RuntimeError) as e:
        log.error("mode %s failed to start", name, exc_info=True)
        if name == "esp32":  # the port is set in Settings, which is only reachable in this mode: run without the board
            return Mode("esp32", device_name="scrcrappy ESP32", error=_why(port, e))
        raise ModeError(str(e)) from e
    keys = KeyQueue(link.send_keys)
    keys.start()
    return Mode(name, make_pointer=lambda size: mouse.Pointer(link.send, mouse.Gain(calibrate.load(serial)), size),
                keys=keys, calibrator=Calibrator(serial, link.send, frames), link=link,
                device_name="scrcrappy ESP32" if name == "esp32" else "scrcrappy PC")
