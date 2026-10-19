"""Text -> keystrokes for a phone whose hardware keyboard layout is U.S. (printable ASCII only)."""

SHIFT = 0x02  # left shift modifier bit

_KEYS: dict[str, tuple[int, int]] = {" ": (0, 0x2C), "\t": (0, 0x2B), "\n": (0, 0x28)}
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _KEYS[c] = (0, 0x04 + i)
    _KEYS[c.upper()] = (SHIFT, 0x04 + i)
for i, (plain, shifted) in enumerate(zip("1234567890", "!@#$%^&*()")):
    _KEYS[plain] = (0, 0x1E + i)
    _KEYS[shifted] = (SHIFT, 0x1E + i)
for usage, plain, shifted in ((0x2D, "-", "_"), (0x2E, "=", "+"), (0x2F, "[", "{"), (0x30, "]", "}"),
                              (0x31, "\\", "|"), (0x33, ";", ":"), (0x34, "'", '"'), (0x35, "`", "~"),
                              (0x36, ",", "<"), (0x37, ".", ">"), (0x38, "/", "?")):
    _KEYS[plain] = (0, usage)
    _KEYS[shifted] = (SHIFT, usage)


def keystrokes(text: str) -> tuple[list[tuple[int, int]], int]:
    """(modifiers, usage) per character, and how many characters the US layout can't type."""
    strokes, skipped = [], 0
    for c in text.replace("\r\n", "\n").replace("\r", ""):
        if c in _KEYS:
            strokes.append(_KEYS[c])
        else:
            skipped += 1
    return strokes, skipped
