// scrcrappy BLE mouse: the ESP32 poses as a Bluetooth LE mouse for the iPhone's AssistiveTouch.
// Serial (115200) line protocol, same as scrcrappy/blemouse.py:
//   in:  "dx dy buttons wheel"  one HID report, notified at once (dx/dy/wheel -127..127)
//        "?"                    status query
//   out: "ready" (advertising), "connected" (phone subscribed to reports)
#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>

static const uint8_t REPORT_MAP[] = {
    0x05, 0x01, 0x09, 0x02, 0xA1, 0x01, 0x85, 0x01,  // generic desktop, mouse, collection(application), report id 1
    0x09, 0x01, 0xA1, 0x00,                          // pointer, collection(physical)
    0x05, 0x09, 0x19, 0x01, 0x29, 0x03, 0x15, 0x00, 0x25, 0x01, 0x95, 0x03, 0x75, 0x01, 0x81, 0x02,  // 3 buttons
    0x95, 0x01, 0x75, 0x05, 0x81, 0x03,              // 5 bits padding
    0x05, 0x01, 0x09, 0x30, 0x09, 0x31, 0x09, 0x38,  // X, Y, wheel
    0x15, 0x81, 0x25, 0x7F, 0x75, 0x08, 0x95, 0x03, 0x81, 0x06,  // int8, relative
    0xC0, 0xC0,
};

static NimBLECharacteristic* input;
static bool subscribed = false;

class ReportCallbacks : public NimBLECharacteristicCallbacks {
    void onSubscribe(NimBLECharacteristic*, NimBLEConnInfo&, uint16_t subValue) override {
        subscribed = subValue != 0;
        if (subscribed) Serial.println("connected");
    }
};

void setup() {
    Serial.begin(115200);
    NimBLEDevice::init("scrcrappy mouse ESP32");
    NimBLEDevice::setSecurityAuth(true, false, true);  // bond, Just Works, secure connections

    NimBLEServer* server = NimBLEDevice::createServer();
    server->advertiseOnDisconnect(true);
    NimBLEHIDDevice* hid = new NimBLEHIDDevice(server);
    hid->setManufacturer("scrcrappy");
    hid->setPnp(0x02, 0x045E, 0x0001, 0x0001);
    hid->setHidInfo(0x00, 0x02);
    hid->setReportMap((uint8_t*)REPORT_MAP, sizeof(REPORT_MAP));
    input = hid->getInputReport(1);
    input->setCallbacks(new ReportCallbacks());
    hid->startServices();
    hid->setBatteryLevel(100);

    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    adv->setAppearance(0x03C2);  // HID mouse
    adv->addServiceUUID(hid->getHidService()->getUUID());
    adv->setName("scrcrappy mouse ESP32");
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
            if (subscribed) Serial.println("connected");
            continue;
        }
        int dx, dy, buttons, wheel;
        if (sscanf(line, "%d %d %d %d", &dx, &dy, &buttons, &wheel) != 4) continue;
        uint8_t report[4] = {(uint8_t)(buttons & 0x07), (uint8_t)(int8_t)dx, (uint8_t)(int8_t)dy, (uint8_t)(int8_t)wheel};
        input->setValue(report, sizeof(report));
        input->notify();
    }
}
