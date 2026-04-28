#!/usr/bin/env python3
import os
import stat
import time
import subprocess
from pathlib import Path
from gpiozero import MotionSensor

####### KONFIGURACJA #######
PIR_PIN = 24
INACTIVITY_TIME = 60 # Po ilu sekundach bez ruchu zamknąć Chromium i wygasić ekran
REARM_DELAY = 3.0 # Krótka blokada po wygaszeniu ekranu, żeby uniknąć natychmiastowego ponownego wzbudzenia
MIN_MOTION_ACTIVE = 2.0  # Minimalny czas ciągłego wykrywania ruchu, zanim uznamy go za prawdziwy
LOOP_SLEEP = 0.2 # Co ile sekund sprawdzam stan czujnika
STATE_LOG_INTERVAL = 2.0 # Co ile sekund wypisywać log debugowy
LOGS_ENABLED = 0   # 1 = logi włączone, 0 = logi wyłączone

BASE_DIR = Path("/home/smart/Desktop/Smart_Mirror")
START_CHROMIUM = BASE_DIR / "start_chromium.sh"
LOG_FILE = BASE_DIR / "pir_launcher.log" # Plik logu dla startu Chromium
DISPLAY_OUTPUT = "HDMI-A-1" # Nazwa wyjścia monitora w Wayland / wlr-randr

process = None
pir = MotionSensor(PIR_PIN)

##### FUNKCJE POMOCNICZE ######
def log(message: str):
    """
    Czy wyrzucać logi w konsoli (1 = tak, 0 = nie)
    """
    if LOGS_ENABLED == 1:
        print(message, flush=True)

def ensure_executable(path: Path):
    """
    Upewnia się, że wskazany plik istnieje i ma prawa wykonywania.
    """
    if not path.exists():
        raise FileNotFoundError(f"Brak pliku: {path}")

    mode = path.stat().st_mode
    if not (mode & stat.S_IXUSR):
        path.chmod(mode | stat.S_IXUSR)


def detect_wayland_display():
    """
    Próbuje wykryć nazwę socketu Wayland.
    Najpierw bierze WAYLAND_DISPLAY z environment, a jeśli go nie ma,
    szuka plików typu /run/user/<uid>/wayland-*.
    """
    env_value = os.environ.get("WAYLAND_DISPLAY")
    if env_value:
        return env_value

    runtime_dir = f"/run/user/{os.getuid()}"
    runtime_path = Path(runtime_dir)

    if runtime_path.exists():
        candidates = sorted(runtime_path.glob("wayland-*"))
        if candidates:
            return candidates[0].name

    return None


def build_env():
    """
    Buduje environment potrzebne do:
    - uruchomienia Chromium z poziomu usługi
    - sterowania ekranem przez wlr-randr
    """
    env = os.environ.copy()

    # X11 / XWayland
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XAUTHORITY", f"{Path.home()}/.Xauthority")

    # Wayland
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

    detected_wayland = detect_wayland_display()
    if detected_wayland:
        env.setdefault("WAYLAND_DISPLAY", detected_wayland)

    # PATH
    if "/usr/bin" not in env.get("PATH", ""):
        env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")

    return env


def chromium_running() -> bool:
    """
    Sprawdza, czy Chromium już działa.
    Obsługuje obie nazwy binarki: chromium-browser i chromium.
    """
    result1 = subprocess.run(
        ["pgrep", "-x", "chromium-browser"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result1.returncode == 0:
        return True

    result2 = subprocess.run(
        ["pgrep", "-x", "chromium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result2.returncode == 0


def sensor_state() -> bool:
    """
    Zwraca aktualny stan czujnika PIR.
    True -> wykryto ruch
    False -> brak ruchu
    """
    return bool(pir.motion_detected)


def set_screen_power(on: bool):
    """
    Włącza lub wyłącza ekran monitora przez wlr-randr.
    Działa w środowisku Wayland / wlroots.
    """
    env = build_env()
    state_flag = "--on" if on else "--off"

    result = subprocess.run(
        ["wlr-randr", "--output", DISPLAY_OUTPUT, state_flag],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    if result.returncode == 0:
        print(f"[PIR] Ekran -> {'ON' if on else 'OFF'}")
    else:
        print(f"[PIR] Nie udało się ustawić ekranu na {'ON' if on else 'OFF'}")


# ============================================================
# AKCJE GŁÓWNE
# ============================================================

def run_wake_up_action():
    """
    Akcja wykonywana po potwierdzonym ruchu:
    - włącza ekran
    - uruchamia Chromium, jeśli jeszcze nie działa
    """
    global process

    # Jeśli proces już się zakończył, czyścimy uchwyt
    if process is not None and process.poll() is not None:
        process = None

    # Jeśli start Chromium już trwa, nie uruchamiaj kolejnego
    if process is not None:
        print("[PIR] Start Chromium już trwa - pomijam.")
        return

    # Jeśli Chromium już działa, tylko upewnij się, że ekran jest włączony
    if chromium_running():
        print("[PIR] Chromium już działa.")
        set_screen_power(True)
        return

    print("[PIR] Potwierdzony ruch -> włączam ekran i uruchamiam Chromium.")

    # Najpierw włącz ekran
    set_screen_power(True)

    # Krótka pauza, żeby monitor zdążył się obudzić
    time.sleep(0.5)

    # Upewnij się, że skrypt startujący Chromium jest wykonywalny
    ensure_executable(START_CHROMIUM)

    env = build_env()

    # Logi startu Chromium zapisujemy do osobnego pliku
    log = open(LOG_FILE, "ab", buffering=0)
    try:
        process = subprocess.Popen(
            ["/bin/bash", str(START_CHROMIUM)],
            cwd=str(BASE_DIR),
            env=env,
            stdout=log,
            stderr=log,
        )
    finally:
        log.close()


def run_sleep_action():
    """
    Akcja wykonywana po dłuższym braku ruchu:
    - zamyka Chromium
    - wygasza ekran
    """
    global process

    print(f"[PIR] Brak ruchu przez {INACTIVITY_TIME}s -> zamykam Chromium i wygaszam ekran.")

    # Zamknij Chromium niezależnie od nazwy binarki
    subprocess.run(
        ["pkill", "-x", "chromium-browser"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        ["pkill", "-x", "chromium"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    # Jeśli mamy uchwyt do procesu startowego, wyczyść go
    if process is not None:
        try:
            process.wait(timeout=2)
        except Exception:
            pass
        process = None

    # Krótka pauza i wygaszenie ekranu
    time.sleep(0.5)
    set_screen_power(False)


############ PĘTLA GŁÓWNA ##########

def main():
    # Czy ekran / interfejs jest aktualnie aktywny
    screen_active = False

    # Czas ostatniego wykrytego ruchu
    last_motion_time = 0.0

    # Do kiedy obowiązuje blokada ponownego wzbudzenia
    suppress_until = 0.0

    # Poprzedni stan czujnika (do logowania zmian)
    prev_motion = None

    # Czas ostatniego logu debugowego
    last_state_log_time = 0.0

    # Kiedy zaczął się aktualny ciągły ruch
    motion_started_at = None

    print("[PIR] Watcher startuje...")
    print(f"[PIR] PIN={PIR_PIN}, INACTIVITY_TIME={INACTIVITY_TIME}s")
    log(f"[PIR] REARM_DELAY={REARM_DELAY}s")
    print(f"[PIR] MIN_MOTION_ACTIVE={MIN_MOTION_ACTIVE}s")
    log(f"[PIR] START_CHROMIUM={START_CHROMIUM}")
    log(f"[PIR] DISPLAY_OUTPUT={DISPLAY_OUTPUT}")

    try:
        while True:
            now = time.time()
            motion = sensor_state()

            # Loguj tylko realną zmianę stanu czujnika
            if prev_motion is None or motion != prev_motion:
                print(f"[PIR] Stan czujnika zmienił się: {'RUCH' if motion else 'BRAK_RUCHU'}")
                prev_motion = motion

            # Co jakiś czas wypisz pełniejszy stan debugowy
            if now - last_state_log_time >= STATE_LOG_INTERVAL:
                process_alive = process is not None and process.poll() is None
                log(
                    f"[PIR] DEBUG motion={motion} "
                    f"screen_active={screen_active} "
                    f"chromium_running={chromium_running()} "
                    f"process_alive={process_alive}"
                )
                last_state_log_time = now

            # ====================================================
            # Gdy czujnik widzi ruch
            if motion:
                # Aktualizuj znacznik ostatniego ruchu
                last_motion_time = now

                # Jeśli to początek ruchu, zapamiętaj czas startu
                if motion_started_at is None:
                    motion_started_at = now

                # Ruch uznajemy za prawdziwy dopiero po utrzymaniu go
                # przez MIN_MOTION_ACTIVE sekund
                stable_motion = (now - motion_started_at) >= MIN_MOTION_ACTIVE

                # Ekran wybudzamy tylko jeśli:
                # - jest nieaktywny
                # - minęła blokada po wygaszeniu
                # - ruch został potwierdzony
                if not screen_active and now >= suppress_until and stable_motion:
                    run_wake_up_action()
                    screen_active = True

            # ====================================================
            # Gdy czujnik nie widzi ruchu
            else:
                # Resetuj licznik ciągłego ruchu
                motion_started_at = None

                # Jeśli ekran jest aktywny i przez INACTIVITY_TIME nie było ruchu,
                # to zamknij Chromium i wygasz ekran
                if screen_active and (now - last_motion_time > INACTIVITY_TIME):
                    run_sleep_action()
                    screen_active = False

                    # Krótka blokada, żeby uniknąć natychmiastowego wzbudzenia
                    suppress_until = now + REARM_DELAY
                    log(f"[PIR] Blokada ponownego wzbudzenia do {REARM_DELAY}s po wygaszeniu.")

            time.sleep(LOOP_SLEEP)

    except KeyboardInterrupt:
        print("[PIR] Zatrzymano Ctrl+C.")
    finally:
        try:
            run_sleep_action()
        finally:
            pir.close()


if __name__ == "__main__":
    main()