from flask import Flask, render_template, jsonify
from google_calendar import get_upcoming_events, get_google_tasks
from apple_calendar import get_apple_events
from face_recognition_module import FaceRecognitionModule
from mirror_user import MirrorUser
import os
import datetime
import requests
import json
import numpy as np
from mirror_user import MirrorUser

app = Flask(__name__)

# Ładowanie użytkowników z pliku JSON
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

# Inicjalizacja modułu rozpoznawania twarzy na starcie aplikacji
face_rec_module = FaceRecognitionModule(users)

# Na razie ręcznie ustawiamy user_id (docelowo będzie z rozpoznawania twarzy)
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

from datetime import datetime

def get_weather_forecast():
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={weather_API_KEY}&units=metric&lang=pl"
    try:
        response = requests.get(url)
        data = response.json()
        forecast_list = data['list'][:4]  # najbliższe 4 prognozy (12 godzin)

        forecast_data = []
        for item in forecast_list:
            dt = datetime.fromtimestamp(item['dt']).strftime('%H:%M')
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

@app.route('/')
def index():
    now = datetime.now()
    time = now.strftime("%H:%M")
    date = now.strftime("%A, %d %B %Y")

    weather = get_weather()
    forecast = get_weather_forecast()
    return render_template("index.html",
                           time=time, date=date,
                           weather=weather, forecast=forecast,
                           )

@app.route('/user')
def index_user():
    now = datetime.now()
    time = now.strftime("%H:%M")
    date = now.strftime("%A, %d %B %Y")

    weather = get_weather()
    forecast = get_weather_forecast()

    # Próba rozpoznania użytkownika na wejściu
    recognized_user_id = face_rec_module.recognize_user()
    if recognized_user_id is not None:
        user_id = recognized_user_id
    else:
        user_id = CURRENT_USER_ID
        print("Nie rozpoznano użytkownika.")

    # Znajdujemy użytkownika o user_id (rozpoznanym lub domyślnym)
    current_user = next((u for u in users if u.user_id == user_id), None)
    print("Załadowani użytkownicy:", users)
    if not current_user:
        return "Użytkownik nie znaleziony", 404

    # Pobierz kalendarz w zależności od typu
    if current_user.calendar_type == "google":
        today_events, future_events = get_upcoming_events(current_user.user_id)
        tasks = get_google_tasks(current_user.user_id)
    elif current_user.calendar_type == "apple":
        today_events, future_events = get_apple_events(current_user.calendar_data)
        tasks = []
    else:
        today_events, future_events, tasks = [], [], []

    return render_template("index_user.html",
                           time=time, date=date,
                           weather=weather, forecast=forecast,
                           today_events=today_events, future_events=future_events,
                           tasks=tasks,
                           user=current_user)


if __name__ == "__main__":
    app.run(debug=True)
