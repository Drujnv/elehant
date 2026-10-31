#!/usr/bin/env python3
"""Элехант: чтение счётчиков воды/газа из BLE-рекламы.

Никакого GATT и сопряжения: прибор только вещает manufacturer data 0xFFFF.
Скрипт декодирует пакет и печатает JSON; опционально публикует в MQTT
(для Home Assistant/Grafana).

Запуск:
  python elehant_reader.py --scan 60
  python elehant_reader.py --scan 0 --mqtt 127.0.0.1 --topic-prefix elehant
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass

MANUFACTURER_ID = 0xFFFF
WATER_MARKERS = {bytes.fromhex("960102"): "water", bytes.fromhex("960101"): "gas",
                 bytes.fromhex("0a010201"): "water_legacy"}


@dataclass
class Reading:
    mac: str
    device_id: str
    kind: str
    channel: int
    serial: int
    volume_m3: float
    temperature_c: float
    battery_raw: int
    flags: int
    packet_counter: int
    rssi: int
    ts: float


def decode(mac: str, data: bytes, rssi: int = 0) -> Reading | None:
    """data — manufacturer payload без company ID (17 байт)."""
    if len(data) < 17 or data[0] != 0x80:
        return None
    kind = "unknown"
    for marker, name in WATER_MARKERS.items():
        if data[2:2 + len(marker)] == marker:
            kind = name
            break
    serial = data[6] | (data[7] << 8) | (data[8] << 16)
    volume_raw = data[9] | (data[10] << 8) | (data[11] << 16) | (data[12] << 24)
    temperature_raw = data[14] | (data[15] << 8)
    return Reading(
        mac=mac.upper(),
        device_id=f"B0:{data[5]:02X}:02:{serial:06X}",
        kind=kind,
        channel=int(data[5]),
        serial=serial,
        volume_m3=round(volume_raw / 10000.0, 4),
        temperature_c=round(temperature_raw / 100.0, 2),
        battery_raw=int(data[13]),
        flags=int(data[16]),
        packet_counter=int(data[1]),
        rssi=int(rssi),
        ts=time.time(),
    )


async def scan(seconds: float, mqtt_host: str | None, prefix: str) -> int:
    from bleak import BleakScanner

    publisher = None
    if mqtt_host:
        import paho.mqtt.client as mqtt

        publisher = mqtt.Client()
        publisher.connect(mqtt_host, 1883, 30)
        publisher.loop_start()

    seen = 0

    def callback(device, adv) -> None:
        nonlocal seen
        payload = (adv.manufacturer_data or {}).get(MANUFACTURER_ID)
        if payload is None:
            return
        reading = decode(device.address, bytes(payload), adv.rssi)
        if reading is None:
            return
        seen += 1
        print(json.dumps(asdict(reading), ensure_ascii=False), flush=True)
        if publisher is not None:
            topic = f"{prefix}/{reading.device_id.replace(':', '').lower()}/state"
            publisher.publish(topic, json.dumps(asdict(reading), ensure_ascii=False), retain=True)

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    try:
        if seconds <= 0:
            while True:
                await asyncio.sleep(3600)
        else:
            await asyncio.sleep(seconds)
    finally:
        await scanner.stop()
        if publisher is not None:
            publisher.loop_stop()
    if not seen:
        print("Пакетов Элехант не найдено — проверьте радиус/питание.", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Элехант BLE reader")
    parser.add_argument("--scan", type=float, default=60.0,
                        help="секунды сканирования; 0 = бесконечно")
    parser.add_argument("--mqtt", default="", help="MQTT-хост (например 127.0.0.1)")
    parser.add_argument("--topic-prefix", default="elehant")
    args = parser.parse_args()
    return asyncio.run(scan(args.scan, args.mqtt or None, args.topic_prefix))


if __name__ == "__main__":
    raise SystemExit(main())
