// scrcrappy BLE mouse + keyboard: the ESP32 poses as a Bluetooth LE mouse (driving the iPhone's
// AssistiveTouch cursor) and keyboard. Serial (115200) line protocol, same as scrcrappy/blemouse.py:
//   in:  "dx dy buttons wheel"        mouse report (dx/dy/wheel -127..127)
//        "k modifiers k1 .. k6"       keyboard report: modifier bits + held key usages (0 = none)
//        "?"                          status query
//        "p"                          forget the paired phone (dropping it if connected), let a new one pair, and
//                                     restart the board (UART-bridge boards only) so no trace of the old one is left
//                                     (pairing is otherwise closed once a phone is bonded)
//   out: "dbg ..." lines (connect, auth result, disconnect reason) say why a pairing fails; scrcrappy logs them.
//        The debug build (pio env *-debug, -DSCRCRAPPY_DEBUG=1) adds link parameters, MTU, PHY and, every 5 s while
//        anything changes, report / notification counters, failures and free heap.
//        "ready" (advertising), "connected" (phone subscribed to reports), "disconnected" (phone gone),
//        "pairing" (answer to "p"). "?" answers a snapshot: "ready", "fw <normal|debug> <build date>", "unpaired" |
//        "paired <id>", and while a phone
//        is connected "connected" and "peer <id> <name>" (id = last two bytes of its address, name = its GAP name)
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

#ifdef SCRCRAPPY_DEBUG
#define FW_FLAVOR "debug"
static uint32_t rxReports = 0, notifyOk = 0, notifyFail = 0;
#define COUNT_NOTIFY(ok) ((ok) ? notifyOk++ : notifyFail++)
#else
#define FW_FLAVOR "normal"
#define COUNT_NOTIFY(ok) ((void)(ok))
#endif

// HCI disconnect reasons worth naming (the host stack adds 0x200 to them: 534 = 0x200 + 0x16)
static const char* hciReason(int r) {
    switch (r >= 0x200 ? r - 0x200 : r) {
        case 0x05: return "authentication failure";
        case 0x06: return "pin or key missing";
        case 0x08: return "supervision timeout";
        case 0x13: return "remote user terminated";
        case 0x14: return "remote low resources";
        case 0x15: return "remote power off";
        case 0x16: return "local host terminated";
        case 0x3D: return "MIC failure";
        case 0x3E: return "connection failed to establish";
        default: return "other";
    }
}

// Keyboard first, with LED output: iOS only treats the device as a keyboard like this.
static const uint8_t REPORT_MAP[] = {
    0x05, 0x01, 0x09, 0x06, 0xA1, 0x01, 0x85, 0x02,  // generic desktop, keyboard, collection(application), report id 2
    0x05, 0x07, 0x19, 0xE0, 0x29, 0xE7, 0x15, 0x00, 0x25, 0x01, 0x75, 0x01, 0x95, 0x08, 0x81, 0x02,  // 8 modifier bits
    0x95, 0x01, 0x75, 0x08, 0x81, 0x01,              // reserved byte
    0x95, 0x05, 0x75, 0x01, 0x05, 0x08, 0x19, 0x01, 0x29, 0x05, 0x91, 0x02,  // 5 LED outputs
    0x95, 0x01, 0x75, 0x03, 0x91, 0x01,              // 3 bits padding
    0x95, 0x06, 0x75, 0x08, 0x15, 0x00, 0x25, 0x65, 0x05, 0x07, 0x19, 0x00, 0x29, 0x65, 0x81, 0x00,  // 6 keys
    0xC0,
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x01,  // generic desktop, mouse, collection(application), report id 1
    0x09, 0x01, 0xA1, 0x00,                          // pointer, collection(physical)
    0x05, 0x09, 0x19, 0x01, 0x29, 0x05, 0x15, 0x00, 0x25, 0x01, 0x95, 0x05, 0x75, 0x01, 0x81, 0x02,  // 5 buttons
    0x95, 0x01, 0x75, 0x03, 0x81, 0x03,              // 3 bits padding
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x09, 0x38,  // X, Y, wheel
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03, 0x81, 0x06,  // int8, relative
    0xC0, 0xC0,
};

static NimBLECharacteristic* input;
static NimBLECharacteristic* keyboard;
static bool subscribed = false;
static bool pairing = true;  // open until the first phone bonds, and again after "p"
static NimBLEServer* server;
static char peerId[8] = "";    // "3F:A2": the connected phone, or the bonded one when none is connected
static char peerName[64] = "";  // GAP Device Name of the connected phone, "" if unknown

static void idOf(const NimBLEAddress& a, char* out) {
    const uint8_t* v = a.getVal();  // least significant byte first
    snprintf(out, 8, "%02X:%02X", v[1], v[0]);
}

static int nameCb(uint16_t, const struct ble_gatt_error* e, struct ble_gatt_attr* a, void*) {
    if (e->status == 0 && a && a->om) {
        memset(peerName, 0, sizeof(peerName));
        os_mbuf_copydata(a->om, 0, min((int)OS_MBUF_PKTLEN(a->om), (int)sizeof(peerName) - 1), peerName);
        for (char* c = peerName; *c; c++) if (*c == '\n' || *c == '\r') *c = ' ';
    }
    return 0;
}

class ReportCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo&, uint16_t subValue) override {
        subscribed = subValue != 0;
        if (subscribed) Serial.println("connected");
    }
};

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer*, NimBLEConnInfo& info) override {
        Serial.printf("dbg connect %s bonds=%d\n", info.getAddress().toString().c_str(), NimBLEDevice::getNumBonds());
#ifdef SCRCRAPPY_DEBUG
        Serial.printf("dbg conn interval=%u latency=%u timeout=%u\n", info.getConnInterval(), info.getConnLatency(),
                      info.getConnTimeout());
#endif
    }
#ifdef SCRCRAPPY_DEBUG
    void onMTUChange(uint16_t mtu, NimBLEConnInfo&) override { Serial.printf("dbg mtu %u\n", mtu); }
    void onConnParamsUpdate(NimBLEConnInfo& info) override {  // interval in 1.25 ms units, timeout in 10 ms units
        Serial.printf("dbg conn interval=%u latency=%u timeout=%u\n", info.getConnInterval(), info.getConnLatency(),
                      info.getConnTimeout());
    }
    void onPhyUpdate(NimBLEConnInfo&, uint8_t tx, uint8_t rx) override { Serial.printf("dbg phy tx=%u rx=%u\n", tx, rx); }
    void onIdentity(NimBLEConnInfo&) override { Serial.println("dbg identity resolved"); }
#endif
    void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int reason) override {
        Serial.printf("dbg disconnect reason=%d (%s)\n", reason, hciReason(reason));
        subscribed = false;
        peerName[0] = 0;
        Serial.println("disconnected");
    }
    void onAuthenticationComplete(NimBLEConnInfo& info) override {
        Serial.printf("dbg auth enc=%d bonded=%d auth=%d\n", info.isEncrypted(), info.isBonded(), info.isAuthenticated());
        idOf(info.getIdAddress(), peerId);
        ble_uuid16_t gap = BLE_UUID16_INIT(0x2A00);  // the phone's Device Name
        ble_gattc_read_by_uuid(info.getConnHandle(), 1, 0xffff, &gap.u, nameCb, nullptr);
        if (!info.isBonded()) return;
        if (pairing || NimBLEDevice::getNumBonds() <= 1) {  // the one phone we pair with
            pairing = false;
            return;
        }
        NimBLEDevice::deleteBond(info.getIdAddress());  // a stranger: no bond, no keystrokes
        server->disconnect(info.getConnHandle());
    }
};

void setup() {
    Serial.begin(115200);
    NimBLEDevice::init("scrcrappy ESP32");
    NimBLEDevice::setSecurityAuth(true, false, true);  // bond, Just Works, secure connections
    pairing = NimBLEDevice::getNumBonds() == 0;

    server = NimBLEDevice::createServer();
    server->setCallbacks(new ServerCallbacks());
    server->advertiseOnDisconnect(true);
    NimBLEHIDDevice* hid = new NimBLEHIDDevice(server);
    hid->setManufacturer("scrcrappy");
    hid->setPnp(0x02, 0x045E, 0x0001, 0x0001);
    hid->setHidInfo(0x00, 0x02);
    hid->setReportMap((uint8_t*)REPORT_MAP, sizeof(REPORT_MAP));
    input = hid->getInputReport(1);
    input->setCallbacks(new ReportCallbacks());
    keyboard = hid->getInputReport(2);
    hid->getOutputReport(2);  // keyboard LEDs; ignored, but iOS wants a keyboard to have them
    hid->startServices();
    hid->setBatteryLevel(100);

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->setAppearance(0x03C1);  // HID keyboard (also a mouse)
    adv->addServiceUUID(hid->getHidService()->getUUID());
    adv->setName("scrcrappy ESP32");
    adv->enableScanResponse(true);
    adv->start();
    Serial.println("ready");
}

void loop() {
    static char line[48];
    static size_t len = 0;
    static uint32_t checked = 0;
#ifdef SCRCRAPPY_DEBUG
    static uint32_t statsAt = 0, lastRx = 0, lastOk = 0, lastFail = 0;
    if (millis() - statsAt > 5000) {  // only while something changed: an idle board stays quiet
        statsAt = millis();
        if (rxReports != lastRx || notifyOk != lastOk || notifyFail != lastFail) {
            lastRx = rxReports, lastOk = notifyOk, lastFail = notifyFail;
            Serial.printf("dbg stats rx=%u notify_ok=%u notify_fail=%u heap=%u up=%us\n", rxReports, notifyOk,
                          notifyFail, ESP.getFreeHeap(), millis() / 1000);
        }
    }
#endif
    if (millis() - checked > 500) {  // advertising must never stay off while no phone is connected (it did after "p")
        checked = millis();
        NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
        if (!server->getConnectedCount() && !adv->isAdvertising()) adv->start();
    }
    while (Serial.available()) {
        char c = Serial.read();
        if (c != '\n') {
            if (len < sizeof(line) - 1) line[len++] = c;
            continue;
        }
        line[len] = 0;
        len = 0;
        if (line[0] == '?') {
            Serial.println("ready");
            Serial.printf("fw %s %s %s\n", FW_FLAVOR, __DATE__, __TIME__);
            if (NimBLEDevice::getNumBonds() == 0) {
                Serial.println("unpaired");
            } else {
                char id[8];
                idOf(NimBLEDevice::getBondedAddress(0), id);
                Serial.printf("paired %s\n", id);
            }
            if (subscribed) {
                Serial.println("connected");
                Serial.printf("peer %s %s\n", peerId, peerName);
            }
            continue;
        }
        if (line[0] == 'p') {
            NimBLEDevice::deleteAllBonds();
            if (server->getConnectedCount()) server->disconnect(server->getPeerInfo(0).getConnHandle());
            pairing = true;
            Serial.println("pairing");
#if !ARDUINO_USB_CDC_ON_BOOT
            // The stack keeps recognising the forgotten phone (its address resolves to the old identity) and its
            // next pairing fails until the board restarts. A restart is harmless behind a UART bridge; a native-USB
            // board would re-enumerate and lose the serial port, so those keep the old behaviour.
            Serial.flush();
            delay(100);
            ESP.restart();
#endif
            continue;
        }
        if (line[0] == 'k') {
            int m, k[6];
            if (sscanf(line, "k %d %d %d %d %d %d %d", &m, &k[0], &k[1], &k[2], &k[3], &k[4], &k[5]) != 7) continue;
            uint8_t report[8] = {(uint8_t)m, 0};
            for (int i = 0; i < 6; i++) report[2 + i] = (uint8_t)k[i];
            keyboard->setValue(report, sizeof(report));
#ifdef SCRCRAPPY_DEBUG
            rxReports++;
#endif
            COUNT_NOTIFY(keyboard->notify());
            continue;
        }
        int dx, dy, buttons, wheel;
        if (sscanf(line, "%d %d %d %d", &dx, &dy, &buttons, &wheel) != 4) continue;
        uint8_t report[4] = {(uint8_t)(buttons & 0x1F), (uint8_t)(int8_t)dx, (uint8_t)(int8_t)dy, (uint8_t)(int8_t)wheel};
        input->setValue(report, sizeof(report));
#ifdef SCRCRAPPY_DEBUG
        rxReports++;
#endif
        COUNT_NOTIFY(input->notify());
    }
}
