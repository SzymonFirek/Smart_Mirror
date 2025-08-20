from flask import Flask, render_template, jsonify, request
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

CURRENT_USER_ID = 1

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
        return {
            "temp": "?", "desc": "Brak danych", "icon": "01d"
        }

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
            forecast_data.append({
                "time": dt,
                "temp": temp,
                "desc": desc,
                "icon": icon
            })
        return forecast_data
    except Exception as e:
        print("Błąd prognozy:", e)
        return []

recognized_user_id = None
recognition_thread = None
recognition_lock = threading.Lock()

def face_recognition_callback(user_id):
    global recognized_user_id
    with recognition_lock:
        recognized_user_id = user_id
    print(f"[APP] Callback: rozpoznano user_id = {user_id}")

def start_face_recognition():
    global recognition_thread
    if recognition_thread and recognition_thread.is_alive():
        return
    recognition_thread = threading.Thread(target=face_rec_module.start_recognition_thread, args=(face_recognition_callback,))
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

    # Rozpoznaj mowę
    tekst = rozpoznaj_mowe()
    if not tekst.strip():
        print("❌ Nie rozpoznano żadnego tekstu.")
        last_stt_text = ""
        return "[Brak rozpoznanego tekstu]", "..."

    print(f"✅ Rozpoznano pełne zdanie: {tekst}")
    last_stt_text = tekst

    # Zapytaj OpenRouter (moduł 2)
    odpowiedz = zapytaj_openrouter(tekst)
    print(f"🧠 Odpowiedź AI: {odpowiedz}")

    # Odczytaj odpowiedź na głos (moduł 3)
    mow_tekstem(odpowiedz)

    return tekst, odpowiedz

@app.route('/')
def index():
    global recognized_user_id
    with recognition_lock:
        recognized_user_id = None
    start_face_recognition()

    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%A, %d %B %Y")

    weather = get_weather()
    forecast = get_weather_forecast()
    return render_template("index.html",
                           time=time_str, date=date_str,
                           weather=weather, forecast=forecast)


@app.route('/check_user')
def check_user():
    global recognized_user_id
    if recognized_user_id is None:
        recognized_user_id = face_rec_module.recognize_user()
    if recognized_user_id is not None:
        return jsonify({"recognized": True, "user_id": recognized_user_id})
    else:
        return jsonify({"recognized": False})


@app.route('/user')
def index_user():
    global recognized_user_id, asystent_thread
    with recognition_lock:
        user_id = recognized_user_id if recognized_user_id is not None else CURRENT_USER_ID

    face_rec_module.stop_recognition()

    if not (asystent_thread and asystent_thread.is_alive()):
        asystent_thread = threading.Thread(target=hotword_listener, daemon=True)
        asystent_thread.start()
        print("🔊 Wątek nasłuchiwania hotworda uruchomiony.")

    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%A, %d %B %Y")

    weather = get_weather()
    forecast = get_weather_forecast()

    current_user = next((u for u in users if u.user_id == user_id), None)
    if not current_user:
        return "Użytkownik nie znaleziony", 404

    today_events, future_events, tasks = [], [], []
    if current_user.calendar_type == "google":
        try:
            # ZMIANA: Użycie nowych endpointów do pobrania wydarzeń i zadań Google
            today_events, future_events = get_upcoming_events(current_user.user_id)
            tasks = get_google_tasks(current_user.user_id)
        except (RefreshError, MemoryError):
            print(f"[Google] Nie można odświeżyć tokenu dla user_id = {current_user.user_id}, usuwam token.")
            token_path = f"token_{current_user.user_id}.pickle"
            if os.path.exists(token_path):
                os.remove(token_path)
            today_events, future_events, tasks = [], [], []
    elif current_user.calendar_type == "apple":
        # ZMIANA: Użycie nowego endpointa do pobrania wydarzeń Apple
        today_events, future_events = get_apple_events(current_user.calendar_data)
        tasks = []
    else:
        today_events, future_events, tasks = [], [], []

    return render_template("index_user.html",
                           time=time_str, date=date_str,
                           weather=weather, forecast=forecast,
                           today_events=today_events, future_events=future_events,
                           tasks=tasks,
                           user=current_user)

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
    return jsonify({
        "user_input": tekst,
        "ai_response": odpowiedz
    })

@app.route("/user/asystent_chat")
def asystent_chat():
    return render_template("asystent_chat.html")  # JS sam dociąga dane przez AJAX

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, use_reloader=False)
