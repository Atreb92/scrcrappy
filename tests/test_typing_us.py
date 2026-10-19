import string

from scrcrappy.typing_us import SHIFT, keystrokes


def test_letters_digits_and_shifted():
    assert keystrokes("aZ1!")[0] == [(0, 0x04), (SHIFT, 0x1D), (0, 0x1E), (SHIFT, 0x1E)]


def test_symbols_us_positions():
    assert keystrokes("-=[;'/`\\")[0] == [(0, 0x2D), (0, 0x2E), (0, 0x2F), (0, 0x33), (0, 0x34), (0, 0x38), (0, 0x35), (0, 0x31)]


def test_whitespace():
    assert keystrokes(" \t\n")[0] == [(0, 0x2C), (0, 0x2B), (0, 0x28)]


def test_crlf_is_one_enter():
    assert keystrokes("a\r\nb")[0] == [(0, 0x04), (0, 0x28), (0, 0x05)]


def test_unsupported_skipped_and_counted():
    assert keystrokes("è😀x") == ([(0, 0x1B)], 2)


def test_every_printable_ascii_is_typable():
    strokes, skipped = keystrokes(string.printable.replace("\x0b", "").replace("\x0c", "").replace("\r", ""))
    assert skipped == 0
    assert len(strokes) == len(string.printable) - 3
