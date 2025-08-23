#!/usr/bin/env python3
"""
inode_api.py

Prosty interfejs do odczytu temperatury i wilgotności z iNode CS HT przez BLE.
Funkcje:
  - pomiar() -> (temp_c: float, hum_pct: float)
  - pomiar_temp() -> float
  - pomiar_wilg() -> float

Uwaga: domyślnie używa bluepy (Scanner). Jeśli bluepy wymaga uprawnień do hci,
możesz nadać uprawnienia dla bluepy-helper (instrukcja poniżej) lub użyć bleak.
"""

from bluepy.btle import Scanner
import struct
from typing import Tuple, Optional

TARGET_MAC_DEFAULT = "d0:f0:18:44:17:a4"
SCAN_TIME_DEFAULT = 5.0

def _decode_inode_manufacturer(raw_hex: str) -> Optional[Tuple[float, float]]:
    """
    Dekoduje ManufacturerData (hex string) zgodnie z Twoim pierwotnym snippetem:
      - temp_raw = uint16 little-endian z offsetu 8
      - hum_raw  = uint16 little-endian z offsetu 10
      - temperature = temp_raw / 256.0
      - humidity    = hum_raw / 100.0
    Zwraca (temp_c, hum_pct) lub None jeżeli brak/nieprawidłowe dane.
    """
    try:
        data = bytes.fromhex(raw_hex.replace(" ", ""))
    except Exception:
        return None

    if len(data) < 12:
        return None

    temp_raw = struct.unpack_from("<H", data, 8)[0]
    hum_raw  = struct.unpack_from("<H", data, 10)[0]

    temperature = temp_raw / 256.0
    humidity    = hum_raw / 100.0
    return (temperature, humidity)

def _get_manufacturer_data(mac: str, scan_time: float = SCAN_TIME_DEFAULT) -> Tuple[str, int]:
    """
    Skanuje reklamy BLE przez `scan_time` sekund i zwraca pierwsze znalezione ManufacturerData
    oraz RSSI urządzenia o danym MAC. MAC porównywane case-insensitive.
    Rzuca RuntimeError gdy brak urządzenia/pola.
    """
    scanner = Scanner()
    devs = scanner.scan(scan_time)
    for dev in devs:
        if dev.addr.lower() == mac.lower():
            for (adtype, desc, value) in dev.getScanData():
                if desc.lower().startswith("manufacturer"):
                    # value to hex string bez spacji (np. "909b01c0...")
                    return value, dev.rssi
            raise RuntimeError("Znaleziono urządzenie, ale brak pola ManufacturerData.")
    raise RuntimeError("Nie znaleziono urządzenia o MAC: " + mac)

def pomiar(mac: str = TARGET_MAC_DEFAULT, scan_time: float = SCAN_TIME_DEFAULT) -> Tuple[float, float]:
    """
    Wykonuje pojedynczy skan i zwraca (temperature_C, humidity_pct).
    Rzuca wyjątki RuntimeError gdy urządzenie/pole nie jest dostępne, ValueError przy błędach dekodowania.
    """
    raw_hex, rssi = _get_manufacturer_data(mac, scan_time=scan_time)
    decoded = _decode_inode_manufacturer(raw_hex)
    if decoded is None:
        raise ValueError("Nie można zdekodować ManufacturerData: " + raw_hex)
    return decoded

def pomiar_temp(mac: str = TARGET_MAC_DEFAULT, scan_time: float = SCAN_TIME_DEFAULT) -> float:
    t, _ = pomiar(mac=mac, scan_time=scan_time)
    return t

def pomiar_wilg(mac: str = TARGET_MAC_DEFAULT, scan_time: float = SCAN_TIME_DEFAULT) -> float:
    _, h = pomiar(mac=mac, scan_time=scan_time)
    return h

# -- prosty CLI dla testu
if __name__ == "__main__":
    import sys
    mac = TARGET_MAC_DEFAULT
    if len(sys.argv) >= 2:
        mac = sys.argv[1]
    try:
        t, h = pomiar(mac=mac)
        print(f"MAC: {mac}  Temperatura: {t:.2f} °C   Wilgotność: {h:.2f} %")
    except Exception as e:
        print("Błąd:", e)
        sys.exit(2)
