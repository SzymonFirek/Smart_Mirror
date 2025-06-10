from flask import Flask, render_template
import datetime
import requests
import json
import numpy as np
from mirror_user import MirrorUser

app = Flask(__name__)


def load_users(json_path="users.json"):
    with open(json_path, 'r') as f:
        user_dicts = json.load(f)

    users = []
    for u in user_dicts:
        encoding = np.load(u["face_encoding_path"])
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


API_KEY = "d23796afecfbd9348704a408398583e1"
LAT = 50.0647
LON = 19.9450


API_KEY = "d23796afecfbd9348704a408398583e1"
CITY = "Kraków"

def get_weather():
    url = f"http://api.openweathermap.org/data/2.5/weather?q={CITY}&appid={API_KEY}&units=metric&lang=pl"
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
    url = f"http://api.openweathermap.org/data/2.5/forecast?q={CITY}&appid={API_KEY}&units=metric&lang=pl"
    try:
        response = requests.get(url)
        data = response.json()
        forecast_list = data['list'][:4]  # najbliższe 4 prognozy (czyli 12 godzin)

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

    events = [
        {"time": "09:00", "title": "Spotkanie z zespołem"},
        {"time": "12:30", "title": "Lunch"},
        {"time": "15:00", "title": "Zakupy"}
    ]

    return render_template("index.html", time=time, date=date, weather=weather, forecast=forecast, events=events)


if __name__ == "__main__":
    app.run(debug=True)
