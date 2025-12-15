#!/usr/bin/env python3

"""
UPDATE 15.12.2025: gesty wykrywane są przez kamerę, a nie przez APDS!!!
"""

import time
import board
import busio
import threading
from adafruit_apds9960.apds9960 import APDS9960

# Inicjalizacja I2C i czujnika
i2c = busio.I2C(board.SCL, board.SDA)
apds = APDS9960(i2c)

# Anty-zamrożenie
# Minimalna moc diody IR (3 = 12.5%)
apds.led_drive = 3

# Minimalny gain fotodiody
apds.proximity_gain = 0  # 0 = 1x

# Najkrótszy impuls IR
apds.prox_pulse_length = 0  # 0 = 4µs

# Minimalna liczba impulsów
apds.prox_pulse_count = 4

#
apds.enable_proximity = True
apds.enable_gesture = True

# Ustawienia
PROX_THRESHOLD = 2
FREEZE_DETECTION_INTERVAL = 1.0  # sekundy bez danych = zamrożenie
CHECK_INTERVAL = 0.5

# Zmienne globalne
last_update_time = time.time()
last_prox = 0
frozen = False
freeze_lock = threading.Lock()


def freeze_monitor():
    global last_update_time, frozen, last_prox
    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.time()
        with freeze_lock:
            elapsed = now - last_update_time
            if elapsed > FREEZE_DETECTION_INTERVAL and not frozen:
                print(f"⚠️ CZUJNIK ZAMROŻONY (brak reakcji przez {elapsed:.2f}s)")
                if last_prox > 1:
                    print("🟡 GEST: ZBLIŻENIE (zamrożone)")
                frozen = True
            elif elapsed <= FREEZE_DETECTION_INTERVAL and frozen:
                print(f"✅ CZUJNIK ODMROŻONY")
                frozen = False
                last_prox = 0  # resetujemy, by uniknąć fałszywych porównań po odwieszeniu



# Wątek do monitorowania czujnika
threading.Thread(target=freeze_monitor, daemon=True).start()

print("Start... Wykrywanie gestów, zbliżenia i zamrożenia.")

while True:
    try:
        gesture = apds.gesture()
        if gesture == 0x01:
            print("Gest: PRAWO")
        elif gesture == 0x02:
            print("Gest: LEWO")
        elif gesture == 0x03:
            print("Gest: GÓRA")
        elif gesture == 0x04:
            print("Gest: DÓŁ")

        prox = apds.proximity
        print(f"Proximity: {prox}")

        # Zwykłe zbliżenie / oddalenie
        with freeze_lock:
            is_frozen = frozen

        if not is_frozen:
            if abs(prox - last_prox) > PROX_THRESHOLD:
                if prox > last_prox:
                    print("ZBLIŻENIE")
                else:
                    print("ODDALENIE")
            last_prox = prox
        else:
            # ignoruj zmiany w czasie zamrożenia
            pass

        last_prox = prox

        # Odnotuj ostatni działający czas
        with freeze_lock:
            last_update_time = time.time()

        time.sleep(0.3)

    except Exception as e:
        print(f"❌ Błąd: {e}")
        break
