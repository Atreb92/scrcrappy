import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def helper_map() -> bytes:
    src = (ROOT / "scrcrappy" / "blemouse.py").read_text()
    block = src[src.index("REPORT_MAP = bytes.fromhex(") : src.index("\n)\n")]
    return bytes.fromhex("".join(re.findall(r'^\s*"([0-9a-f]+)"', block, re.M)))


def firmware_map() -> bytes:
    src = (ROOT / "firmware" / "esp32-mouse" / "src" / "main.cpp").read_text()
    block = src[src.index("REPORT_MAP[] = {") : src.index("};", src.index("REPORT_MAP[] = {"))]
    return bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", block))


def test_helper_and_firmware_describe_the_same_device():
    assert helper_map() == firmware_map()


def test_keyboard_first_with_led_output():
    # iOS shows no "Hardware Keyboard" (and ignores its layout setting) otherwise
    m = helper_map()
    assert m.startswith(bytes.fromhex("05010906a1018502"))  # keyboard collection, report 2
    assert bytes.fromhex("0508190129059102") in m  # LED usage page, output report
