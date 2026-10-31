#!/usr/bin/env python3
"""Элехант: прототип Windows-приложения (BLE-сбор, таблица, график, деньги)."""
from __future__ import annotations

import asyncio
import json
import pathlib
import queue
import threading
import time
import tkinter as tk
import traceback
from dataclasses import asdict, dataclass, field
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from elehant_reader import MANUFACTURER_ID, Reading, decode

DATA_DIR = pathlib.Path.home() / "Elehant"
READINGS = DATA_DIR / "readings.jsonl"
SETTINGS = DATA_DIR / "settings.json"
LOG = DATA_DIR / "app.log"

MAIN_COLUMNS = ("device", "kind", "volume", "temp", "battery", "flow", "last", "delta", "cost")
SERVICE_COLUMNS = ("mac", "device_id", "serial")

KIND_RU = {"water": "Вода", "gas": "Газ", "water_legacy": "Вода", "unknown": "Прибор"}


def kind_label(kind: str, channel: int) -> str:
    """Понятное человеку название, без технического номера канала."""
    if kind == "gas":
        return "Газ"
    if channel == 1:
        return "Холодная вода"
    if channel == 3:
        return "Горячая вода (до +40 °C)"
    if channel == 4:
        return "Горячая вода (выше +40 °C)"
    return "Вода"


def default_label(kind: str, channel: int, serial: int) -> str:
    name = kind_label(kind, channel)
    return f"{name} № {serial:07d}" if serial else name


@dataclass
class Device:
    key: str
    mac: str
    device_id: str
    kind: str
    channel: int
    serial: int
    label: str = ""
    volume: float = 0.0
    temperature: float = 0.0
    battery: int = 0
    flags: int = 0
    rssi: int = 0
    last_ts: float = 0.0
    base_volume: float | None = None
    flow: bool = False
    tariff: float = 0.0
    reference: float | None = None
    history: list[tuple[float, float]] = field(default_factory=list)

    def display_name(self) -> str:
        return self.label or default_label(self.kind, self.channel, self.serial)


class Store:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.devices: dict[str, Device] = {}
        self.lock = threading.Lock()
        self.load_settings()

    def load_settings(self) -> None:
        if not SETTINGS.exists():
            return
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            return
        for key, item in data.items():
            dev = Device(key=key, mac="", device_id="", kind="", channel=0, serial=0)
            dev.label = str(item.get("label", "") or "")
            dev.tariff = float(item.get("tariff", 0.0) or 0.0)
            ref = item.get("reference")
            dev.reference = float(ref) if ref is not None else None
            self.devices[key] = dev

    def save_settings(self) -> None:
        payload = {k: {"label": d.label, "tariff": d.tariff, "reference": d.reference}
                   for k, d in self.devices.items()}
        SETTINGS.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    def apply(self, reading: Reading) -> Device:
        key = f"{reading.mac}|{reading.channel}"
        with self.lock:
            dev = self.devices.get(key)
            if dev is None:
                dev = Device(key=key, mac=reading.mac, device_id=reading.device_id,
                             kind=reading.kind, channel=reading.channel, serial=reading.serial)
                self.devices[key] = dev
            dev.mac = reading.mac
            dev.device_id = reading.device_id
            dev.kind = reading.kind
            dev.channel = reading.channel
            dev.serial = reading.serial
            if not dev.label:
                dev.label = default_label(reading.kind, reading.channel, reading.serial)
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
        self.geometry("1220x760")
        self.store = Store()
        self.events: queue.Queue[Reading] = queue.Queue()
        self.scan_stats = {"packets": 0, "last": 0.0, "restarts": 0, "error": ""}
        self.stats_lock = threading.Lock()
        self.selected: str | None = None
        self.scan_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.show_service = tk.BooleanVar(value=False)
        self._build_ui()
        self.log("app start")
        self.after(250, self.drain)
        self.after(1000, self.start_scan)

    def log(self, message: str) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
        except Exception:
            pass

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
        right = ttk.Frame(body, width=370)
        right.pack(side="right", fill="y", padx=(8, 0))

        columns = MAIN_COLUMNS + SERVICE_COLUMNS
        self.tree = ttk.Treeview(left, columns=columns, show="headings", height=12)
        headers = {
            "device": "Счётчик", "kind": "Что измеряет", "volume": "Показание, м³", "temp": "Температура, °C",
            "battery": "Батарея", "flow": "Вода идёт?", "last": "Последний сигнал", "delta": "Расхождение с табло",
            "cost": "Стоимость, ₽", "mac": "MAC", "device_id": "ID", "serial": "Серийный номер",
        }
        widths = {"device": 230, "kind": 210, "volume": 100, "temp": 100, "battery": 70,
                  "flow": 80, "last": 90, "delta": 130, "cost": 90,
                  "mac": 135, "device_id": 150, "serial": 90}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], anchor="center")
        self.tree.configure(displaycolumns=MAIN_COLUMNS)
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
        ttk.Label(right, text="Название счётчика (как в приложении)").pack(anchor="w", pady=(8, 0))
        self.label_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.label_var, width=34).pack(anchor="w")

        ttk.Label(right, text="Тариф, ₽/м³ (можно пусто)").pack(anchor="w", pady=(6, 0))
        self.tariff_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.tariff_var, width=18).pack(anchor="w")

        ttk.Label(right, text="Показание с табло, м³").pack(anchor="w", pady=(6, 0))
        self.ref_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.ref_var, width=18).pack(anchor="w")

        ttk.Button(right, text="Сохранить", command=self.save_selected).pack(anchor="w", pady=8)
        ttk.Checkbutton(right, text="Показывать служебные поля (MAC/ID/серийный)",
                        variable=self.show_service, command=self.toggle_service).pack(anchor="w", pady=(4, 0))
        self.service = ttk.Label(right, text="", foreground="#555", wraplength=340, justify="left")
        self.service.pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="Что означает «Что измеряет»:\n"
                              "• Холодная вода — счётчик ХВС;\n"
                              "• Горячая вода — один счётчик ГВС с двумя регистрами:\n"
                              "  до +40 °C и выше +40 °C (так считает сам прибор);\n"
                              "• Газ — газовый счётчик.\n"
                              "Технические номера каналов (01/03/04) —\n"
                              "в служебных полях, обычному человеку не нужны.",
                  foreground="#555", wraplength=340, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="Данные пишутся в:\n" + str(READINGS) + "\n\n"
                              "Тариф не задан — деньги не считаются.\n"
                              "Расход — только при росте объёма;\n"
                              "температура без воды расходом не считается.",
                  foreground="#555", wraplength=340, justify="left").pack(anchor="w", pady=(16, 0))

    def toggle_service(self) -> None:
        columns = MAIN_COLUMNS + SERVICE_COLUMNS if self.show_service.get() else MAIN_COLUMNS
        self.tree.configure(displaycolumns=columns)

    def on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        self.selected = sel[0]
        with self.store.lock:
            dev = self.store.devices.get(self.selected)
        if dev is None:
            return
        self.label_var.set(dev.label or default_label(dev.kind, dev.channel, dev.serial))
        self.tariff_var.set(f"{dev.tariff:.2f}" if dev.tariff else "")
        self.ref_var.set("" if dev.reference is None else f"{dev.reference:.4f}")
        self.update_service(dev)
        self.redraw(dev)

    def update_service(self, dev: Device) -> None:
        self.service.configure(text=(
            f"MAC: {dev.mac or '—'}\n"
            f"ID: {dev.device_id or '—'}\n"
            f"Серийный: {dev.serial:07d}\n"
            f"Канал: {dev.channel:02d}\n"
            f"Флаги: 0x{dev.flags:02X}   RSSI: {dev.rssi} dBm"
        ))

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
            dev.label = self.label_var.get().strip() or default_label(dev.kind, dev.channel, dev.serial)
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
            if reading is None:
                return
            with self.stats_lock:
                self.scan_stats["packets"] += 1
                self.scan_stats["last"] = time.time()
            self.events.put(reading)

        async def run_once() -> None:
            from bleak import BleakScanner

            scanner = BleakScanner(detection_callback=callback)
            await scanner.start()
            started = time.time()
            # Пересоздаём сканер каждую минуту: на Windows BleakScanner иногда замолкает.
            while not self.stop_event.is_set() and time.time() - started < 60:
                await asyncio.sleep(0.5)
            await scanner.stop()

        try:
            while not self.stop_event.is_set():
                try:
                    loop.run_until_complete(run_once())
                    with self.stats_lock:
                        self.scan_stats["restarts"] += 1
                        self.scan_stats["error"] = ""
                except Exception as error:  # noqa: BLE001
                    with self.stats_lock:
                        self.scan_stats["error"] = type(error).__name__
                    self.log("scan error: " + repr(error))
                    loop.run_until_complete(asyncio.sleep(5))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    def drain(self) -> None:
        updated = False
        try:
            while True:
                try:
                    reading = self.events.get_nowait()
                except queue.Empty:
                    break
                self.store.apply(reading)
                updated = True
            if updated:
                self.refresh()
            self.update_status()
        except Exception:
            self.log("drain error:\n" + traceback.format_exc())
        self.after(400, self.drain)

    def update_status(self) -> None:
        with self.stats_lock:
            stats = dict(self.scan_stats)
        if stats["error"]:
            text = f"BLE ошибка: {stats['error']} (перезапуск)"
            color = "#a33"
        elif stats["last"]:
            text = f"сканирую BLE… пакетов: {stats['packets']}, последний: {time.strftime('%H:%M:%S', time.localtime(stats['last']))}"
            color = "#2a7"
        else:
            text = "сканирую BLE… пакетов пока нет"
            color = "#666"
        self.status.configure(text=text, foreground=color)

    def refresh(self) -> None:
        with self.store.lock:
            rows = list(self.store.devices.values())
        existing = set(self.tree.get_children())
        for dev in rows:
            iid = dev.key
            delta = f"{dev.volume - dev.reference:+.4f}" if dev.reference is not None else ""
            cost = ""
            if dev.tariff:
                start = dev.reference if dev.reference is not None else (dev.base_volume or dev.volume)
                cost = f"{max(dev.volume - start, 0.0) * dev.tariff:.2f}"
            last = time.strftime("%H:%M:%S", time.localtime(dev.last_ts)) if dev.last_ts else "—"
            values = (
                dev.display_name(),
                kind_label(dev.kind, dev.channel),
                f"{dev.volume:.4f}", f"{dev.temperature:.2f}", str(dev.battery),
                "идёт" if dev.flow else "нет", last, delta, cost,
                dev.mac, dev.device_id, f"{dev.serial:07d}",
            )
            if iid in existing:
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)
        if self.selected:
            with self.store.lock:
                dev = self.store.devices.get(self.selected)
            if dev:
                self.update_service(dev)
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
        self.ax.set_title(dev.display_name(), fontsize=10)
        self.canvas.draw_idle()


if __name__ == "__main__":
    App().mainloop()

