import sounddevice as sd
import queue
import json
import threading
import time
from vosk import Model, KaldiRecognizer

MODEL_PATH = "vosk-model-small-pl-0.22"
SAMPLE_RATE = 16000
BLOCK_SIZE = 4000
VOSK_MODEL = None
MODEL_LOCK = threading.Lock()

def get_vosk_model():
    global VOSK_MODEL
    if VOSK_MODEL is None:
        with MODEL_LOCK:
            if VOSK_MODEL is None:
                print("Ładuję model Vosk do pamięci...")
                VOSK_MODEL = Model(MODEL_PATH)
                print("✅ Model Vosk załadowany.")
    return VOSK_MODEL

def rozpoznaj_mowe() -> str:
    q = queue.Queue()
    stop_flag = threading.Event()
    bufor = []

    def callback(indata, frames, time_, status):
        if status:
            print(f"⚠️ Błąd audio: {status}")
        q.put(bytes(indata))

    print("🎤 Mów teraz (rozpoznawanie zakończy się po 5 sekundach ciszy)...")

    recognizer = KaldiRecognizer(get_vosk_model(), SAMPLE_RATE)

    cisza_start = None
    start_time = time.time()
    MAX_CISZA = 2  # sekundy ciszy kończące rozpoznawanie
    MAX_CALKOWITY = 5  # max sekund całkowitego czasu rozpoznawania

    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                               dtype='int16', channels=1, callback=callback):
            while not stop_flag.is_set():
                if time.time() - start_time > MAX_CALKOWITY:
                    print("⌛ Maksymalny czas rozpoznawania osiągnięty.")
                    break
                try:
                    data = q.get(timeout=0.1)
                except queue.Empty:
                    continue

                if recognizer.AcceptWaveform(data):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "").strip().lower()
                    if text:
                        print(f"➡️ Rozpoznano: {text}")
                        bufor.append(text)
                        cisza_start = None  # resetujemy licznik ciszy, bo jest nowy tekst
                else:
                    # Interim (częściowy) wynik - można ignorować
                    pass

                # Sprawdź ciszę (brak nowego tekstu)
                if cisza_start is None and bufor:
                    cisza_start = time.time()
                if cisza_start and (time.time() - cisza_start > MAX_CISZA):
                    print("🛑 Cisza > 3 sekundy - kończę nagrywanie.")
                    break

    except KeyboardInterrupt:
        print("🧼 Przerwano przez Ctrl+C.")
    finally:
        print("👋 Koniec nagrania.")

    # Zwróć cały rozpoznany tekst jako połączony string
    return " ".join(bufor)

if __name__ == "__main__":
    print("🎙️ Test rozpoznawania mowy – mów teraz...")
    tekst = rozpoznaj_mowe()
    print(f"✅ Rozpoznano: {tekst}")