"""Linux helper: the computer's Bluetooth adapter as a BLE HID keyboard + mouse, "scrcrappy PC" (HID over GATT, BlueZ D-Bus).

Runs under the *system* python (needs python3-dbus + python3-gobject), as a subprocess of scrcrappy.
stdin, one HID report per line, sent at once:
  "dx dy buttons wheel"        mouse (dx/dy/wheel in -127..127)
  "k modifiers k1 k2 k3 k4 k5 k6"   keyboard: modifier bits + held key usages (0 = none)
stdout: "ready" once advertising, "connected" when the phone subscribes to reports.
"""
import os
import signal
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

try:
    from gi.repository import GLibUnix
    signal_add = GLibUnix.signal_add
except ImportError:  # PyGObject < 3.52
    signal_add = GLib.unix_signal_add

BLUEZ = "org.bluez"
PROPS = "org.freedesktop.DBus.Properties"
NAME = "scrcrappy PC"  # the ESP32 firmware calls itself "scrcrappy ESP32"
SVC, CHR, DSC = "org.bluez.GattService1", "org.bluez.GattCharacteristic1", "org.bluez.GattDescriptor1"

REPORT_MAP = bytes.fromhex(  # keyboard first, with LED output: iOS only treats it as a keyboard like this
    "05010906a1018502"  # generic desktop, keyboard, collection(application), report id 2
    "050719e029e715002501750195088102"  # 8 modifier bits
    "950175088101"  # reserved byte
    "950575010508190129059102950175039101"  # 5 LED outputs + 3 bits padding
    "95067508150025650507190029658100"  # 6 key slots, usages 0..0x65
    "c0"
    "05010902a1018501"  # generic desktop, mouse, collection(application), report id 1
    "0901a100"  # pointer, collection(physical)
    "05091901290315002501950375018102"  # 3 buttons
    "950175058103"  # 5 bits padding
    "0501093009310938"  # X, Y, wheel
    "1581257f750895038106"  # int8, relative
    "c0c0"
)


def ay(b):
    return dbus.Array([dbus.Byte(x) for x in b], signature="y")


class Obj(dbus.service.Object):
    def __init__(self, bus, path, iface, props):
        self.path, self.iface, self.props = path, iface, props
        super().__init__(bus, path)

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return self.props


class Chr(Obj):
    def __init__(self, bus, path, uuid, flags, svc, value):
        self.value, self.notifying = value, False
        super().__init__(bus, path, CHR, {"UUID": uuid, "Service": dbus.ObjectPath(svc), "Flags": flags})

    @dbus.service.method(CHR, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, opts):
        return ay(self.value)

    @dbus.service.method(CHR, in_signature="aya{sv}")
    def WriteValue(self, value, opts):
        self.value = bytes(value)

    @dbus.service.method(CHR)
    def StartNotify(self):
        self.notifying = True
        if self.props["UUID"] == "2a4d" and self.path.endswith("c4"):  # the mouse report
            print("connected", flush=True)

    @dbus.service.method(CHR)
    def StopNotify(self):
        self.notifying = False

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, iface, changed, invalidated):
        pass

    def notify(self, value):
        self.value = value
        if self.notifying:
            self.PropertiesChanged(CHR, {"Value": ay(value)}, [])


class Dsc(Obj):
    def __init__(self, bus, path, uuid, chr_path, value):
        self.value = value
        super().__init__(bus, path, DSC, {"UUID": uuid, "Characteristic": dbus.ObjectPath(chr_path), "Flags": ["read"]})

    @dbus.service.method(DSC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, opts):
        return ay(self.value)


class App(dbus.service.Object):
    """GATT services: device information (PnP ID), battery, HID. iOS caches this layout once bonded."""

    def __init__(self, bus):
        super().__init__(bus, "/scrcrappy")
        self.objs = []

        def svc(i, uuid):
            self.objs.append(Obj(bus, f"/scrcrappy/s{i}", SVC, {"UUID": uuid, "Primary": True}))
            return self.objs[-1].path

        def chr(svc_path, j, uuid, flags, value):
            self.objs.append(Chr(bus, f"{svc_path}/c{j}", uuid, flags, svc_path, value))
            return self.objs[-1]

        s = svc(0, "180a")
        chr(s, 0, "2a50", ["read"], bytes([0x02, 0x5E, 0x04, 0x01, 0x00, 0x01, 0x00]))
        s = svc(1, "180f")
        chr(s, 0, "2a19", ["read", "notify"], bytes([100]))
        s = svc(2, "1812")
        chr(s, 0, "2a4a", ["read"], bytes([0x11, 0x01, 0x00, 0x02]))  # HID information
        chr(s, 1, "2a4b", ["read", "encrypt-read"], REPORT_MAP)  # encrypted read forces bonding
        chr(s, 2, "2a4c", ["write-without-response"], b"\x00")  # control point
        chr(s, 3, "2a4e", ["read", "write-without-response"], b"\x01")  # protocol mode: report
        self.report = chr(s, 4, "2a4d", ["read", "notify", "encrypt-read"], bytes(4))
        self.objs.append(Dsc(bus, f"{self.report.path}/d0", "2908", self.report.path, bytes([0x01, 0x01])))
        self.keys = chr(s, 5, "2a4d", ["read", "notify", "encrypt-read"], bytes(8))
        self.objs.append(Dsc(bus, f"{self.keys.path}/d0", "2908", self.keys.path, bytes([0x02, 0x01])))
        leds = chr(s, 6, "2a4d", ["read", "write", "write-without-response", "encrypt-read", "encrypt-write"], b"\x00")
        self.objs.append(Dsc(bus, f"{leds.path}/d0", "2908", leds.path, bytes([0x02, 0x02])))  # report 2, output

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {dbus.ObjectPath(o.path): {o.iface: o.props} for o in self.objs}


class Adv(Obj):
    def __init__(self, bus):
        super().__init__(bus, "/scrcrappy/adv", "org.bluez.LEAdvertisement1", {
            "Type": "peripheral", "ServiceUUIDs": ["1812"], "Appearance": dbus.UInt16(0x03C1),  # keyboard: as mouse (0x03C2) iOS never registered the keyboard part
            "LocalName": NAME, "Discoverable": True})

    @dbus.service.method("org.bluez.LEAdvertisement1")
    def Release(self):
        pass


class Agent(dbus.service.Object):
    """Just Works pairing: accept everything (a mouse has no display or keyboard)."""
    A = "org.bluez.Agent1"

    @dbus.service.method(A)
    def Release(self): pass

    @dbus.service.method(A, in_signature="os")
    def AuthorizeService(self, dev, uuid): pass

    @dbus.service.method(A, in_signature="ou")
    def RequestConfirmation(self, dev, passkey): pass

    @dbus.service.method(A, in_signature="o")
    def RequestAuthorization(self, dev): pass

    @dbus.service.method(A)
    def Cancel(self): pass


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    hci = bus.get_object(BLUEZ, "/org/bluez/hci0")
    adapter = dbus.Interface(hci, PROPS)
    # the phone shows the adapter's alias once connected; put the computer's own settings back on exit
    changed = {"Powered": True, "Pairable": True, "Alias": NAME}
    saved = {k: adapter.Get("org.bluez.Adapter1", k) for k in changed}
    for k, v in changed.items():
        adapter.Set("org.bluez.Adapter1", k, v)
    try:
        serve(bus, hci)
    finally:
        for k, v in saved.items():
            adapter.Set("org.bluez.Adapter1", k, v)


def serve(bus, hci):
    agent = Agent(bus, "/scrcrappy/agent")
    agents = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
    agents.RegisterAgent(agent, "NoInputNoOutput")
    agents.RequestDefaultAgent(agent)

    app, adv, loop = App(bus), Adv(bus), GLib.MainLoop()

    def fail(e):
        print(f"error: {e}", file=sys.stderr, flush=True)
        loop.quit()

    dbus.Interface(hci, "org.bluez.GattManager1").RegisterApplication(app, {}, reply_handler=lambda: None, error_handler=fail)
    dbus.Interface(hci, "org.bluez.LEAdvertisingManager1").RegisterAdvertisement(
        adv, {}, reply_handler=lambda: print("ready", flush=True), error_handler=fail)

    buf = b""

    def on_stdin(fd, cond):
        nonlocal buf
        data = os.read(fd, 4096)
        if not data:  # scrcrappy exited
            loop.quit()
            return False
        *lines, buf = (buf + data).split(b"\n")
        for line in lines:
            if line.startswith(b"k "):
                mods, *keys = (int(v) for v in line.split()[1:])
                app.keys.notify(bytes([mods & 0xFF, 0, *(k & 0xFF for k in keys)]))
            else:
                dx, dy, buttons, wheel = (int(v) for v in line.split())
                app.report.notify(bytes([buttons & 0x07, dx & 0xFF, dy & 0xFF, wheel & 0xFF]))
        return True

    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, on_stdin)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal_add(GLib.PRIORITY_DEFAULT, sig, loop.quit)
    loop.run()


if __name__ == "__main__":
    main()
