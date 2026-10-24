import pytest

from scrcrappy import calibrate


class NoFrames:
    def peek(self):
        return None


def test_cancel_stops_the_measurement_and_saves_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sent = []
    c = calibrate.Calibrator("abc", send=lambda *a: (sent.append(a), len(sent) == 3 and c.cancel()), frames=NoFrames())
    with pytest.raises(calibrate.Cancelled):
        c.run()
    assert len(sent) <= 5  # stopped within a report or two, not after the whole sweep
    assert not calibrate.gain_path("abc").exists()


def test_a_cancel_before_the_run_does_not_leak_into_it(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = calibrate.Calibrator("abc", send=lambda *a: None, frames=None)
    monkeypatch.setattr(calibrate, "calibrate", lambda send, frames, cancel=None: {12: 2.5})
    c.cancel()
    c.run()
    assert calibrate.load("abc")[12.0] == 2.5
