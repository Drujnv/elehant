#!/usr/bin/env python3
"""Прототип Windows-приложения «Элехант»: BLE-сбор, таблица, график, деньги.

Запуск из исходников:
    py -m pip install -r requirements.txt
    py elehant_app.py

Сборка exe:
    .\build_exe.ps1
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import queue
import threading
import time
import tkinter as tk
from dataclasses import asdict, dataclass, field
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from elehant_reader import MANUFACTURER_ID, Reading, decode

DATA_DIR = pathlib.Path.home() / "Elehant"
READINGS = DATA_DIR / "readings.jsonl"
SETTINGS = DATA_DIR / "settings.json"


@dataclass
class Device:
    key: str
    mac: str
    kind: str
    channel: int
    serial: int
    volume: float = 0.0
    temperature: float = 0.0
    battery: int = 0
    flags: int = 0
    rssi: int = 0
    last_ts: float = 0.0
    last_volume: float = 0.0
    base_volume: float | None = None
    flow: bool = False
    tariff: float = 0.0
    reference: float | None = None
    history: list[tuple[float, float]] = field(default_factory=list)


class Store:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.devices: dict[str, Device] = {}
        self.lock = threading.Lock()
        self.load_settings()

    def load_settings(self) -> None:
        if SETTINGS.exists():
            try:
                data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for key, item in data.items():
                dev = Device(key=key, mac="", kind="", channel=0, serial=0)
                dev.tariff = float(item.get("tariff", 0.0) or 0.0)
                ref = item.get("reference")
                dev.reference = float(ref) if ref is not None else None
                self.devices[key] = dev

    def save_settings(self) -> None:
        payload = {k: {"tariff": d.tariff, "reference": d.reference} for k, d in self.devices.items()}
        SETTINGS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def apply(self, reading: Reading) -> Device:
        key = f"{reading.mac}|{reading.channel}"
        with self.lock:
            dev = self.devices.get(key)
            if dev is None:
                dev = Device(key=key, mac=reading.mac, kind=reading.kind,
                             channel=reading.channel, serial=reading.serial)
                self.devices[key] = dev
            previous = dev.volume if dev.last_ts else None
            dev.volume = reading.volume_m3
            if dev.base_volume is None:
                dev.base_volume = reading.volume_m3
            dev.temperature = reading.temperature_c
            dev.battery = reading.battery_raw
            dev.flags = reading.flags
            dev.rssi = reading.rssi
            dev.last_ts = reading.ts
            if previous is not None:
                dev.flow = reading.volume_m3 > previous
            dev.history.append((reading.ts, reading.volume_m3))
            if len(dev.history) > 2000:
                del dev.history[:500]
            with READINGS.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(reading), ensure_ascii=False) + "\n")
            return dev


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Элехант — сбор показаний")
        self.geometry("1180x720")
        self.store = Store()
        self.events: queue.Queue[Reading] = queue.Queue()
        self.selected: str | None = None
        self.scan_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._build_ui()
        self.after(300, self.drain)
        self.after(1000, self.start_scan)

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Элехант: BLE-сбор", font=("Segoe UI", 14, "bold")).pack(side="left")
        self.status = ttk.Label(top, text="запуск…", foreground="#666")
        self.status.pack(side="left", padx=16)
        ttk.Button(top, text="Стоп", command=self.stop_scan).pack(side="right")
        ttk.Button(top, text="Старт", command=self.start_scan).pack(side="right", padx=6)

        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(body, width=360)
        right.pack(side="right", fill="y", padx=(8, 0))

        columns = ("device", "kind", "volume", "temp", "battery", "flow", "last", "delta", "cost")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=12)
        headers = {
            "device": "Прибор", "kind": "Тип/канал", "volume": "м³",
            "temp": "°C", "battery": "батар.", "flow": "вода",
            "last": "пакет", "delta": "Δ к табло", "cost": "₽",
        }
        widths = {"device": 190, "kind": 90, "volume": 100, "temp": 60,
                  "battery": 60, "flow": 60, "last": 90, "delta": 100, "cost": 80}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="center")
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.figure = Figure(figsize=(6, 3.2), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("время")
        self.ax.set_ylabel("м³")
        self.ax.grid(alpha=0.3)
        self.canvas = FigureCanvasTkAgg(self.figure, master=left)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, pady=(8, 0))

        ttk.Label(right, text="Настройки выбранного прибора").pack(anchor="w")
        ttk.Label(right, text="Тариф, ₽/м³ (можно пусто)").pack(anchor="w", pady=(8, 0))
        self.tariff_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.tariff_var, width=18).pack(anchor="w")
        ttk.Label(right, text="Показание с табло, м³").pack(anchor="w", pady=(8, 0))
        self.ref_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.ref_var, width=18).pack(anchor="w")
        ttk.Button(right, text="Сохранить тариф/эталон", command=self.save_selected).pack(anchor="w", pady=8)
        ttk.Label(right, text="Данные пишутся в:\n" + str(READINGS), foreground="#666").pack(anchor="w", pady=(16, 0))
        ttk.Label(right, text="Тариф не задан — деньги не считаются.\n"
                              "Расход — только при росте объёма;\n"
                              "температура без воды расходом не считается.",
                  foreground="#555", wraplength=320, justify="left").pack(anchor="w", pady=(16, 0))

    def on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        self.selected = sel[0]
        with self.store.lock:
            dev = self.store.devices.get(self.selected)
        if dev is None:
            return
        self.tariff_var.set(f"{dev.tariff:.2f}" if dev.tariff else "")
        self.ref_var.set("" if dev.reference is None else f"{dev.reference:.4f}")
        self.redraw(dev)

    def save_selected(self) -> None:
        if not self.selected:
            return
        with self.store.lock:
            dev = self.store.devices.get(self.selected)
            if dev is None:
                return
            try:
                dev.tariff = float(self.tariff_var.get().replace(",", ".")) if self.tariff_var.get().strip() else 0.0
            except ValueError:
                messagebox.showerror("Ошибка", "Тариф должен быть числом или пустым.")
                return
            raw = self.ref_var.get().replace(",", ".").strip()
            dev.reference = float(raw) if raw else None
        self.store.save_settings()
        self.refresh()

    def start_scan(self) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            return
        self.stop_event.clear()
        self.scan_thread = threading.Thread(target=self.scan_worker, daemon=True)
        self.scan_thread.start()
        self.status.configure(text="сканирую BLE…", foreground="#2a7")

    def stop_scan(self) -> None:
        self.stop_event.set()
        self.status.configure(text="остановлено", foreground="#a33")

    def scan_worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        def callback(device, adv) -> None:
            payload = (adv.manufacturer_data or {}).get(MANUFACTURER_ID)
            if payload is None:
                return
            reading = decode(device.address, bytes(payload), adv.rssi)
            if reading is not None:
                self.events.put(reading)

        async def run() -> None:
            from bleak import BleakScanner

            scanner = BleakScanner(detection_callback=callback)
            await scanner.start()
            try:
                while not self.stop_event.is_set():
                    await asyncio.sleep(0.3)
            finally:
                await scanner.stop()

        try:
            loop.run_until_complete(run())
        except Exception as error:  # noqa: BLE001
            self.status.configure(text=f"BLE ошибка: {type(error).__name__}", foreground="#a33")

    def drain(self) -> None:
        updated = False
        while True:
            try:
                reading = self.events.get_nowait()
            except queue.Empty:
                break
            if reading.mac:
                self.store.apply(reading)
                updated = True
        if updated:
            self.refresh()
        self.after(400, self.drain)

    def refresh(self) -> None:
        with self.store.lock:
            rows = list(self.store.devices.values())
        existing = set(self.tree.get_children())
        for dev in rows:
            delta = ""
            if dev.reference is not None:
                delta = f"{dev.volume - dev.reference:+.4f}"
            cost = ""
            if dev.tariff:
                start = dev.reference if dev.reference is not None else (dev.base_volume or dev.volume)
                cost = f"{max(dev.volume - start, 0.0) * dev.tariff:.2f}"
            last = time.strftime("%H:%M:%S", time.localtime(dev.last_ts)) if dev.last_ts else "—"
            kind = f"{dev.kind}/{dev.channel:02d}"
            values = (f"{dev.mac}  {dev.serial:06X}", kind, f"{dev.volume:.4f}",
                      f"{dev.temperature:.2f}", str(dev.battery), "идёт" if dev.flow else "нет",
                      last, delta, cost)
            if dev.key in existing:
                self.tree.item(dev.key, values=values)
            else:
                self.tree.insert("", "end", iid=dev.key, values=values)
        if self.selected:
            with self.store.lock:
                dev = self.store.devices.get(self.selected)
            if dev:
                self.redraw(dev)

    def redraw(self, dev: Device) -> None:
        self.ax.clear()
        self.ax.set_xlabel("время")
        self.ax.set_ylabel("м³")
        self.ax.grid(alpha=0.3)
        if dev.history:
            ts = [time.strftime("%H:%M", time.localtime(t)) for t, _ in dev.history[-240:]]
            vol = [v for _, v in dev.history[-240:]]
            step = max(1, len(ts) // 6)
            self.ax.plot(ts, vol, marker="o", markersize=3, linewidth=1)
            self.ax.set_xticks(ts[::step])
            self.ax.tick_params(axis="x", rotation=30, labelsize=8)
        self.ax.set_title(dev.mac or dev.key, fontsize=10)
        self.canvas.draw_idle()


if __name__ == "__main__":
    App().mainloop()

