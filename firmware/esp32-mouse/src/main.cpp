// scrcrappy BLE mouse + keyboard: the ESP32 poses as a Bluetooth LE mouse (driving the iPhone's
// AssistiveTouch cursor) and keyboard. Serial (115200) line protocol, same as scrcrappy/blemouse.py:
//   in:  "dx dy buttons wheel"        mouse report (dx/dy/wheel -127..127)
//        "k modifiers k1 .. k6"       keyboard report: modifier bits + held key usages (0 = none)
//        "?"                          status query
//        "p"                          forget the paired phone (dropping it if connected) and let a new one pair
//                                     (pairing is otherwise closed once a phone is bonded)
//   out: "ready" (advertising), "connected" (phone subscribed to reports), "disconnected" (phone gone),
//        "pairing" (answer to "p"). "?" answers a snapshot: "ready", "unpaired" | "paired <id>", and while a phone
//        is connected "connected" and "peer <id> <name>" (id = last two bytes of its address, name = its GAP name)
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

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
    void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
        subscribed = false;
        peerName[0] = 0;
        Serial.println("disconnected");
    }
    void onAuthenticationComplete(NimBLEConnInfo& info) override {
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
            continue;
        }
        if (line[0] == 'k') {
            int m, k[6];
            if (sscanf(line, "k %d %d %d %d %d %d %d", &m, &k[0], &k[1], &k[2], &k[3], &k[4], &k[5]) != 7) continue;
            uint8_t report[8] = {(uint8_t)m, 0};
            for (int i = 0; i < 6; i++) report[2 + i] = (uint8_t)k[i];
            keyboard->setValue(report, sizeof(report));
            keyboard->notify();
            continue;
        }
        int dx, dy, buttons, wheel;
        if (sscanf(line, "%d %d %d %d", &dx, &dy, &buttons, &wheel) != 4) continue;
        uint8_t report[4] = {(uint8_t)(buttons & 0x1F), (uint8_t)(int8_t)dx, (uint8_t)(int8_t)dy, (uint8_t)(int8_t)wheel};
        input->setValue(report, sizeof(report));
        input->notify();
    }
}
