# ESP32: BLE-приёмник Элехант

## Зачем

Счётчик может быть далеко от сервера. ESP32 ставится рядом со стояком, слушает
BLE-рекламу и публикует данные в MQTT → Home Assistant/Grafana.

Прибор **не подключается** GATT-ом: нужен только passive scan.

## Файлы

- `elehant_decode.c/.h` — разбор 17-байтного manufacturer payload.

## Arduino (NimBLE)

```cpp
#include <NimBLEDevice.h>
#include "elehant_decode.h"

class Callbacks : public NimBLEAdvertisedDeviceCallbacks {
    void onResult(NimBLEAdvertisedDevice *dev) override {
        if (!dev->haveManufacturerData()) return;
        std::string mfg = dev->getManufacturerData();
        if (mfg.size() < 2) return;
        uint16_t company = (uint8_t)mfg[0] | ((uint16_t)(uint8_t)mfg[1] << 8);
        if (company != 0xFFFF) return;

        elehant_data_t d;
        if (!elehant_decode((const uint8_t *)mfg.data() + 2, mfg.size() - 2, &d)) return;

        Serial.printf("%s: %.4f m3, %.2f C, bat_raw %u, ch %u\n",
            dev->getAddress().toString().c_str(), d.volume_m3,
            d.temperature_c, d.battery_raw, d.channel);
        // MQTT publish: elehant/<device_id>/state
    }
};

void setup() {
    Serial.begin(115200);
    NimBLEDevice::init("elehant-proxy");
    auto *scan = NimBLEDevice::getScan();
    scan->setAdvertisedDeviceCallbacks(new Callbacks());
    scan->setActiveScan(false);
    scan->start(0, false);
}
void loop() { delay(1000); }
```

> В NimBLE manufacturer data включает company ID (первые 2 байта);
> поэтому payload начинается с `mfg + 2`.

## ESP-IDF (GAP scan)

```c
if (param->scan_rst.adv_data_len >= 19) {
    const uint8_t *a = param->scan_rst.ble_adv;
    /* company 0xFFFF обычно идёт в manufacturer data; проверьте свою сборку */
    elehant_data_t d;
    if (elehant_decode(a + 2, param->scan_rst.adv_data_len - 2, &d)) {
        ESP_LOGI("ELEHANT", "%.4f m3 %.2f C bat %u ch %u",
                 d.volume_m3, d.temperature_c, d.battery_raw, d.channel);
    }
}
```

## MQTT/Home Assistant

Предлагаемые топики:
```
elehant/<device_id>/state          JSON (retain)
elehant/<device_id>/volume_m3
elehant/<device_id>/temperature_c
elehant/<device_id>/battery_raw
elehant/<device_id>/last_seen
```

`device_id` — `B0:01:02:...` без двоеточий/нижним регистром.
Готовый пример HA — `../homeassistant/elehant_mqtt.yaml`.

## Практика

- **ESP32-WROOM-32** чувствительнее, чем C3; для дальнего счётчика лучше он.
- Питание: USB 5 В или 3,3 В; не от батарейки надолго.
- Сканирование постоянное, но BLE-сканер потребляет; при питании от USB нормально.
- Если пакеты редки — это не поломка: без расхода прибор вещает реже (до 15 мин).
- Не пытайтесь подключаться GATT — его нет.

## Что можно улучшить

- RSSI и `last_seen` для диагностики «молчания»;
- два канала СВТ (`03`/`04`) как отдельные сенсоры;
- B1-пакеты в отдельный debug-топик (без серийников в публичном HA).
