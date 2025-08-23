#!/usr/bin/env python3
"""
inode_ht.py
Prosty odczyt temperatury i wilgotności z iNode CS HT przez BLE.
Zawsze używa domyślnego MAC: d0:f0:18:44:17:a4
"""

from bluepy.btle import Scanner
import struct
from typing import Tuple

import time
def _t(): return time.perf_counter()
def _log_step(tag, t0):
    dt = (time.perf_counter() - t0) * 1000
    print(f"[PERF] {tag}: {dt:.1f} ms")


TARGET_MAC = "d0:f0:18:44:17:a4"
SCAN_TIME = 5.0

def _decode(raw_hex: str) -> Tuple[float, float]:
    data = bytes.fromhex(raw_hex.replace(" ", ""))
    temp_raw = struct.unpack_from("<H", data, 8)[0]
    hum_raw  = struct.unpack_from("<H", data, 10)[0]
    temperature = temp_raw / 256.0
    humidity    = hum_raw / 100.0
    return temperature, humidity

def _get_data() -> str:
    scanner = Scanner()
    for dev in scanner.scan(SCAN_TIME):
        if dev.addr.lower() == TARGET_MAC:
            for (_, desc, value) in dev.getScanData():
                if desc.lower().startswith("manufacturer"):
                    return value
    raise RuntimeError("Nie znaleziono urządzenia lub pola ManufacturerData.")

def pomiar() -> Tuple[float, float]:
    raw_hex = _get_data()
    return _decode(raw_hex)

def pomiar_temp() -> float:
    t, _ = pomiar()
    return t

def pomiar_wilg() -> float:
    _, h = pomiar()
    return h

if __name__ == "__main__":
    t0 = _t()
    t, h = pomiar()
    print(f"Temperatura: {t:.2f} °C   Wilgotność: {h:.2f} %")
    _log_step("czas pomiaru: ", t0)
