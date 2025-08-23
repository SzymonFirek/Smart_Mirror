from flask import Flask, render_template, jsonify, request, Response, stream_with_context
from google_calendar import get_upcoming_events, get_google_tasks
from apple_calendar import get_apple_events
from google.auth.exceptions import RefreshError
from face_recognition_module import FaceRecognitionModule
from mirror_user import MirrorUser
import os
import datetime
import requests
import json
import numpy as np
import threading
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from rozpoznawanie_mowy import rozpoznaj_mowe
from open_router_chat import zapytaj_openrouter
from odpowiedz_mowa import mow_tekstem
import re
from inode_ht import pomiar_temp, pomiar_wilg

# wrzuć na górze pliku
import time

def _t(): return time.perf_counter()
def _log_step(tag, t0):
    dt = (time.perf_counter() - t0) * 1000
    print(f"[PERF] {tag}: {dt:.1f} ms")


app = Flask(__name__)

asystent_thread = None

hotword_detected = False
hotword_lock = threading.Lock()
last_stt_text = ""

def load_users(json_path="users.json"):
    with open(json_path, 'r') as f:
        user_dicts = json.load(f)

    users = []
    for u in user_dicts:
        encoding = None
        face_encoding_path = os.path.join("known_faces", u["name"], "encoding.npy")
        try:
            encoding = np.load(face_encoding_path)
        except FileNotFoundError:
            print(f"Brak pliku enkodowania twarzy: {face_encoding_path}, ale rejestruję użytkownika.")

        user = MirrorUser(
            user_id=u["user_id"],
            name=u["name"],
            calendar_type=u["calendar_type"],
            email=u.get("email"),
            calendar_data=u.get("calendar_data"),
            face_encoding=encoding
        )
        users.append(user)
    return users

users = load_users()
face_rec_module = FaceRecognitionModule(users)

CURRENT_USER_ID = None  # Tryb normalny: None, wymuszenie user_id: np. 1

weather_API_KEY = "d23796afecfbd9348704a408398583e1"
CITY = "Kraków"

def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={weather_API_KEY}&units=metric&lang=pl"
    try:
        response = requests.get(url)
        data = response.json()
        return {
            "temp": round(data['main']['temp']),
            "desc": data['weather'][0]['description'].capitalize(),
            "icon": data['weather'][0]['icon']
        }
    except Exception as e:
        print("Błąd pobierania pogody:", e)
        return {"temp": "?", "desc": "Brak danych", "icon": "01d"}

def get_weather_forecast():
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={weather_API_KEY}&units=metric&lang=pl"
    try:
        response = requests.get(url)
        data = response.json()
        forecast_list = data['list'][:4]
        forecast_data = []
        for item in forecast_list:
            dt = datetime.datetime.fromtimestamp(item['dt']).strftime('%H:%M')
            temp = round(item['main']['temp'])
            desc = item['weather'][0]['description'].capitalize()
            icon = item['weather'][0]['icon']
            forecast_data.append({"time": dt, "temp": temp, "desc": desc, "icon": icon})
        return forecast_data
    except Exception as e:
        print("Błąd prognozy:", e)
        return []

recognized_user_id = None
recognition_thread = None
recognition_lock = threading.Lock()

# --- Cache i wątek dla iNode (nie blokujemy requestów) ---
_sensor_cache = {"t": None, "h": None, "ts": 0.0}
_sensor_lock = threading.Lock()
_sensor_thread = None

def _sensor_updater_loop():
    """Czyta iNode w pętli i zapisuje wynik do cache.
       Może blokować 10s, ale to *wątek w tle*, nie request."""
    while True:
        try:
            t = pomiar_temp()
            h = pomiar_wilg()
            with _sensor_lock:
                _sensor_cache["t"] = t
                _sensor_cache["h"] = h
                _sensor_cache["ts"] = time.time()
        except Exception as e:
            print("Sensor updater error:", e)
        # jak odczyt długo trwa, krótka przerwa wystarczy
        time.sleep(5)

def _ensure_sensor_thread():
    global _sensor_thread
    if _sensor_thread and _sensor_thread.is_alive():
        return
    _sensor_thread = threading.Thread(target=_sensor_updater_loop, daemon=True)
    _sensor_thread.start()


# === SSE: prosty hub zdarzeń ===
_sse_lock = threading.Lock()
_sse_clients = []  # lista kolejek na eventy

def _sse_broadcast(payload: dict):
    with _sse_lock:
        for q in list(_sse_clients):
            try:
                q.put(json.dumps(payload), block=False)
            except Exception:
                pass  # klient mógł już się rozłączyć

@app.route('/events')
def sse_events():
    """
    Stabilny stream SSE:
    - wysyła pierwsze dane natychmiast (unikamy ERR_EMPTY_RESPONSE),
    - 'keep-alive' i 'no-cache',
    - brak buforowania po stronie proxy (X-Accel-Buffering: no).
    """
    q = queue.Queue()
    with _sse_lock:
        _sse_clients.append(q)

    def gen():
        try:
            # Pierwsze linie od razu:
            yield "retry: 1500\n\n"
            yield ": connected\n\n"
            yield 'event: hello\ndata: {"ok": true}\n\n'
            # Główna pętla:
            while True:
                data = q.get()
                yield f"data: {data}\n\n"
        finally:
            with _sse_lock:
                try:
                    _sse_clients.remove(q)
                except ValueError:
                    pass

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(stream_with_context(gen()), headers=headers)

def face_recognition_callback(user_id):
    global recognized_user_id
    with recognition_lock:
        recognized_user_id = user_id
    print(f"[APP] Callback: rozpoznano user_id = {user_id}")
    # wyślij event do przeglądarki (natychmiastowe przejście na /user)
    _sse_broadcast({"type": "recognized", "user_id": user_id})

def start_face_recognition():
    global recognition_thread
    if recognition_thread and recognition_thread.is_alive():
        return
    recognition_thread = threading.Thread(
        target=face_rec_module.start_recognition_thread,
        args=(face_recognition_callback,)
    )
    recognition_thread.start()

def oczysc_tekst(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9ąćęłńóśźżĄĆĘŁŃÓŚŹŻ.,!? \n]", "", text)

MODEL_PATH = "vosk-model-small-pl-0.22"
SAMPLE_RATE = 16000
BLOCK_SIZE = 4000

def hotword_listener():
    global hotword_detected
    q = queue.Queue()
    print("🔥 Startuję nasłuchiwanie hotwordu...")
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE)

    def callback(indata, frames, time, status):
        if status:
            print(f"Błąd audio: {status}")
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE,
                           dtype='int16', channels=1, callback=callback):
        while True:
            try:
                data = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                text = result.get("text", "").lower()
                if "lustro" in text:
                    print("🪞 Wykryto 'lustro'!")
                    with hotword_lock:
                        hotword_detected = True
                    break

def asystent_glosowy():
    global last_stt_text
    print("🎤 Rozpoczynam rozpoznawanie mowy (hotword wykryty)...")

    tekst = rozpoznaj_mowe()
    if not tekst.strip():
        print("❌ Nie rozpoznano żadnego tekstu.")
        last_stt_text = ""
        return "[Brak rozpoznanego tekstu]", "..."

    print(f"✅ Rozpoznano pełne zdanie: {tekst}")
    last_stt_text = tekst

    odpowiedz = zapytaj_openrouter(tekst)
    print(f"🧠 Odpowiedź AI: {odpowiedz}")

    mow_tekstem(odpowiedz)
    return tekst, odpowiedz

@app.route('/')
def index():
    t0 = _t()
    global recognized_user_id
    with recognition_lock:
        if CURRENT_USER_ID is not None:
            recognized_user_id = CURRENT_USER_ID
            # w trybie wymuszonym nie startujemy kamery
        else:
            # Tryb normalny: start rozpoznawania (NIE czyścimy recognized_user_id)
            start_face_recognition()
    _log_step("index: start_face_recognition + globals", t0)

    t1 = _t()
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%A, %d %B %Y")
    weather = get_weather()
    forecast = get_weather_forecast()
    _log_step("index: weather+forecast", t1)

    t2 = _t()
    # Czujnik iNode_ht przez cache (nie blokuje):
    _ensure_sensor_thread()
    with _sensor_lock:
        temperatura = _sensor_cache["t"]
        wilgotnosc = _sensor_cache["h"]
    _log_step("index: sensors iNode", t2)

    _log_step("index: TOTAL do render_template", t0)
    return render_template("index.html",
                           time=time_str, date=date_str,
                           weather=weather, forecast=forecast,
                           temperatura=temperatura, wilgotnosc=wilgotnosc)

@app.route('/check_user')
def check_user():
    global recognized_user_id
    if CURRENT_USER_ID is not None:
        return jsonify({"recognized": True, "user_id": CURRENT_USER_ID})
    with recognition_lock:
        uid = recognized_user_id
    return jsonify({"recognized": uid is not None, "user_id": uid})

@app.route('/user')
def index_user():
    t0 = _t()
    global recognized_user_id, asystent_thread
    with recognition_lock:
        user_id = recognized_user_id

    face_rec_module.stop_recognition()

    if not (asystent_thread and asystent_thread.is_alive()):
        asystent_thread = threading.Thread(target=hotword_listener, daemon=True)
        asystent_thread.start()
        print("🔊 Wątek nasłuchiwania hotworda uruchomiony.")
    _log_step("user: stop_recognition + hotword_thread", t0)

    t1 = _t()
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%A, %d %B %Y")

    weather = get_weather()
    forecast = get_weather_forecast()
    _log_step("user: weather+forecast", t1)

    t2 = _t()
    # Czujnik iNode_ht z cache (nie blokuje requestu)
    _ensure_sensor_thread()
    with _sensor_lock:
        temperatura = _sensor_cache["t"]
        wilgotnosc = _sensor_cache["h"]
    _log_step("user: sensors iNode", t2)

    current_user = next((u for u in users if u.user_id == user_id), None)
    if not current_user:
        return "Użytkownik nie znaleziony", 404

    t3 = _t()
    today_events, future_events, tasks = [], [], []
    if current_user.calendar_type == "google":
        try:
            today_events, future_events = get_upcoming_events(current_user.user_id)
            tasks = get_google_tasks(current_user.user_id)
        except (RefreshError, MemoryError):
            print(f"[Google] Nie można odświeżyć tokenu dla user_id = {current_user.user_id}, usuwam token.")
            token_path = f"token_{current_user.user_id}.pickle"
            if os.path.exists(token_path):
                os.remove(token_path)
            today_events, future_events, tasks = [], [], []
    elif current_user.calendar_type == "apple":
        today_events, future_events = get_apple_events(current_user.calendar_data)
        tasks = []
    else:
        today_events, future_events, tasks = [], [], []
    _log_step("user: calendars+tasks", t3)

    _log_step("user: TOTAL do render_template", t0)
    return render_template("index_user.html",
                           time=time_str, date=date_str,
                           weather=weather, forecast=forecast,
                           temperatura=temperatura, wilgotnosc=wilgotnosc,
                           today_events=today_events, future_events=future_events,
                           tasks=tasks, user=current_user)

@app.route('/check_hotword')
def check_hotword():
    global hotword_detected
    with hotword_lock:
        if hotword_detected:
            hotword_detected = False
            return jsonify({"detected": True})
    return jsonify({"detected": False})

@app.route("/api/asystent_start")
def api_asystent_start():
    tekst, odpowiedz = asystent_glosowy()
    return jsonify({"user_input": tekst, "ai_response": odpowiedz})

@app.route("/user/asystent_chat")
def asystent_chat():
    return render_template("asystent_chat.html")

@app.post("/api/asystent_prompt")
def api_asystent_prompt():
    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty"}), 400

    odp = zapytaj_openrouter(text)
    try:
        mow_tekstem(odp)
    except Exception as e:
        print("TTS error:", e)

    return jsonify({"ok": True, "assistant": odp})

@app.post("/api/debug_key")
def api_debug_key():
    data = request.get_json(force=True, silent=True) or {}
    print(f"[KEYDBG] {data}")
    return jsonify(ok=True)

@app.get("/api/sensors")
def api_sensors():
    # upewnij się, że wątek jest uruchomiony
    _ensure_sensor_thread()
    with _sensor_lock:
        return jsonify({
            "t": _sensor_cache.get("t"),
            "h": _sensor_cache.get("h"),
            "ts": _sensor_cache.get("ts")
        })

@app.post("/api/ensure_recognition")
def api_ensure_recognition():
    # jeśli wątek działa, nic się nie stanie; jeśli nie, zostanie uruchomiony
    start_face_recognition()
    return jsonify(ok=True)


if __name__ == "__main__":
    # SSE potrzebuje wielowątkowości na dev-serwerze
    app.run(host="0.0.0.0", debug=False, use_reloader=False, threaded=True)
