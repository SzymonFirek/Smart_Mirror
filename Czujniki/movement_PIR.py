#!/usr/bin/env python3
import os
import stat
import time
import subprocess
import RPi.GPIO as GPIO
from pathlib import Path

# --- KONFIG ---
PIR_PIN = 17
INACTIVITY_TIME = 60
WAKE_UP_ACTION = Path("/home/smart/Desktop/Smart_Mirror/start_desktop.sh")
LOG_FILE = "/home/smart/Desktop/Smart_Mirror/pir_launcher.log"

# --- GPIO ---
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIR_PIN, GPIO.IN)

process = None  # Popen obiektu bash uruchamiającego start_desktop.sh

def ensure_executable(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Brak pliku: {path}")
    mode = path.stat().st_mode
    if not (mode & stat.S_IXUSR):
        # ustaw +x dla właściciela
        path.chmod(mode | stat.S_IXUSR)

def build_env():
    env = os.environ.copy()
    # Gdyby uruchomienie było z kontekstu bez GUI/XDG:
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    # dopilnuj PATH, aby był /usr/bin (chromium-browser zwykle tu jest)
    if "/usr/bin" not in env.get("PATH", ""):
        env["PATH"] = "/usr/bin:" + env.get("PATH", "")
    return env

def run_wake_up_action():
    global process
    # jeśli mamy uchwyt, ale proces już zakończony — wyczyść
    if process is not None and process.poll() is not None:
        process = None

    if process is None:
        print("Ruch wykryty! Uruchamiam aplikację...")
        ensure_executable(WAKE_UP_ACTION)
        env = build_env()

        # loguj, co się dzieje (debug basha z set -x)
        log = open(LOG_FILE, "ab", buffering=0)
        cmd = ["/bin/bash", str(WAKE_UP_ACTION)]
        # cwd nie jest konieczne (skrypt sam robi cd), ale nie zaszkodzi:
        process = subprocess.Popen(
            cmd,
            cwd=str(WAKE_UP_ACTION.parent),
            env=env,
            stdout=log,
            stderr=log
        )
    else:
        print("Aplikacja już działa (pomijam ponowne uruchomienie).")

def run_sleep_action():
    global process
    # zabijamy aplikacje uruchomione przez start_desktop.sh
    print("Brak ruchu 60s. Zamykam aplikację...")
    # Flask
    subprocess.Popen(["pkill", "-f", "python app.py"])
    # Chromium (różne nazwy w zależności od dystrybucji)
    subprocess.Popen(["pkill", "-x", "chromium-browser"])
    subprocess.Popen(["pkill", "-x", "chromium"])
    # zakończ sam proces basha, jeśli jeszcze działa
    if process is not None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        process = None

def main():
    last_motion_time = 0
    action_triggered = False
    try:
        print("PIR watcher startuje...")
        while True:
            if GPIO.input(PIR_PIN):
                last_motion_time = time.time()
                if not action_triggered:
                    run_wake_up_action()
                    action_triggered = True
            else:
                if action_triggered and (time.time() - last_motion_time > INACTIVITY_TIME):
                    run_sleep_action()
                    action_triggered = False
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("Koniec programu (Ctrl+C).")
    finally:
        # porządek przy wyjściu
        run_sleep_action()
        GPIO.cleanup()

if __name__ == "__main__":
    main()
