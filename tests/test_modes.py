import threading

import pytest

from scrcrappy import modes


class FakeLink:
    def __init__(self):
        self.connected, self.closed, self.sent = threading.Event(), 0, []

    def send(self, *a):
        self.sent.append(a)

    def send_keys(self, *a):
        pass

    def close(self):
        self.closed += 1


class FakeKeys:
    def __init__(self, send):
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


class FakeSession:
    def __init__(self, sock, reopen=None):
        self.sock, self.closed = sock, 0

    def close(self):
        self.closed += 1


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(modes, "KeyQueue", FakeKeys)
    monkeypatch.setattr(modes.sys, "platform", "linux")
    monkeypatch.setattr(modes.links, "esp32", lambda port: FakeLink())
    monkeypatch.setattr(modes.links, "ble", lambda python: FakeLink())
    monkeypatch.setattr(modes.agent, "connect", lambda host, wait=10: type("A", (), {"sock": object()})())
    monkeypatch.setattr(modes.agent, "Session", FakeSession)


def start(name, **kw):
    return modes.start_mode(name, "/dev/ttyUSB0", "abc", None, **kw)


def test_none_has_no_input():
    m = start("none")
    assert (m.name, m.make_pointer, m.keys, m.session, m.calibrator, m.link) == ("none", None, None, None, None, None)
    assert m.board is None and m.connected() is True and m.device_name == "scrcrappy PC"
    m.close()


def test_esp32_builds_link_keys_pointer_and_calibrator():
    m = start("esp32")
    assert m.board is m.link and m.keys.started == 1 and m.make_pointer and m.calibrator
    assert m.device_name == "scrcrappy ESP32"
    assert m.connected() is False
    m.link.connected.set()
    assert m.connected() is True


def test_ble_has_no_board():
    m = start("ble")
    assert m.link and m.board is None and m.device_name == "scrcrappy PC"


def test_agent_wraps_a_session():
    m = start("agent")
    assert isinstance(m.session, FakeSession) and m.keys is None and m.make_pointer is None


@pytest.mark.parametrize("name,target,exc", [
    ("esp32", "esp32", OSError("no such port")),
    ("ble", "ble", RuntimeError("helper failed")),
    ("agent", "connect", modes.agent.AgentError("no agent")),
])
def test_failures_become_mode_errors(monkeypatch, name, target, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(modes.agent if target == "connect" else modes.links, target, boom)
    with pytest.raises(modes.ModeError, match=str(exc)):
        start(name)


def test_close_closes_each_resource_once():
    m = start("esp32")
    m.session = FakeSession(None)
    m.close()
    m.close()
    assert (m.link.closed, m.keys.stopped, m.session.closed) == (1, 1, 1)


def test_selectable_blocks_only_ble_on_macos():
    assert not modes.selectable("ble", "darwin")
    assert all(modes.selectable(n, "darwin") for n in ("none", "esp32", "agent"))
    assert all(modes.selectable(n, "linux") for n in modes.LABELS)


def test_ble_on_macos_raises_mode_error(monkeypatch):
    monkeypatch.setattr(modes.sys, "platform", "darwin")
    with pytest.raises(modes.ModeError, match="Linux"):
        start("ble")
