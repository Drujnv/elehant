# Источники, лицензии и что именно мы взяли

## 1. Протокол Элехант

| Источник | Что дал | Как использовали | Лицензия/статус |
|---|---|---|---|
| [`vooon/elehant-to-mqtt`](https://github.com/vooon/elehant-to-mqtt) | открытая карта 19-байтного пакета | сверка полей; **код не копировали** | проверить LICENSE перед публикацией |
| orycan.ru (статья + разбор APK) | независимая раскладка 17-байтного пакета | сверка с нашей; совпала | статья, не код; ссылка обязательна |
| [`SCRAME314/elehantmi`](https://github.com/SCRAME314/elehantmi) | HA-интеграция «добавление через интерфейс» | изучили подход; код не копировали | проверить LICENSE |
| [`mitri4/esphome_elehant`](https://github.com/mitri4/esphome_elehant) | газовый счётчик на ESP32 | идея ESP32-приёма; код не копировали | проверить LICENSE |
| приложение «Счётчики Элехант» 5.1.1 | поведение, экран, сверка | только наблюдения | APK не публикуем |

## 2. Чип nRF24LE1

| Источник | Что дал |
|---|---|
| Nordic nRF24LE1 datasheet/SDK | архитектура, пины, UART/SPI |
| [`sonocotta/nRF24LE1-Example`](https://github.com/sonocotta/nRF24LE1-Example) | примеры SDK |
| [`polkabana/nRF24LE1_Programmer`](https://github.com/polkabana/nRF24LE1_Programmer) | Arduino-программатор |
| [`puskyer/nrf24le1_flasher`](https://github.com/puskyer/nrf24le1_flasher) | FT232R flasher |
| [`derekstavis/nrf24le1-libbcm2835`](https://github.com/derekstavis/nrf24le1-libbcm2835) | Raspberry Pi |

## 3. Шлюз/умный дом

| Источник | Что дал |
|---|---|
| [`alutov/ESP32-R4sGate-for-Redmond`](https://github.com/alutov/ESP32-R4sGate-for-Redmond) | база R4S-шлюза; для Элеханта — только идея дополнительного BLE-приёмника |
| Home Assistant MQTT docs | формат discovery/сенсоров |
| `bleak` | BLE-сканер для Windows/Linux |

## 4. Что взяли буквально, а что нет

- **Не копировали** чужой код декодеров/интеграций.
- Взяли **идею карты полей** и сверили её с независимым разбором.
- Наши добавления: двухканальность 03/04, температура холодной воды, аудит
  байтов, B1-пакеты, чиповая часть, интеграционный контур.
- Перед публикацией нужно:
  1. проверить лицензии `vooon/elehant-to-mqtt`, `SCRAME314/elehantmi`,
     `mitri4/esphome_elehant`, `sonocotta/nRF24LE1-Example`,
     `polkabana/nRF24LE1_Programmer`, `puskyer/nrf24le1_flasher`,
     `derekstavis/nrf24le1-libbcm2835`;
  2. указать авторов и ссылки в README;
  3. не включать чужие бинарники/прошивки.

## 5. Чего в публикации не будет

- MAC/серийников/показаний владельца;
- логина/пароля/API-ключа `cntdev.ru`;
- персональных данных;
- APK/прошивок вендора;
- чужих дампов и кода без лицензии.

## 6. Наш вклад

Проект **Elehant** — независимый открытый разбор счётчиков Элехант. Всё, что
публикуется, проверено на своих приборах; персональные данные не публикуются.
