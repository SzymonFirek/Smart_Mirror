import requests
from ics import Calendar
from datetime import datetime, timezone

def get_apple_events(calendar_url):
    try:
        r = requests.get(calendar_url)
        r.raise_for_status()
        calendar = Calendar(r.text)
        now = datetime.now(timezone.utc)
        today_events = []
        future_events = []

        for event in calendar.events:
            start = event.begin.datetime
            if start.date() == now.date():
                today_events.append({
                    "title": event.name,
                    "date_str": start.strftime("%d.%m"),
                    "sort_date": start.date(),
                    "is_today": True,
                    "time": start.strftime("%H:%M") if start.time() != datetime.min.time() else None
                })
            elif start > now:
                future_events.append({
                    "title": event.name,
                    "date_str": start.strftime("%d.%m"),
                    "sort_date": start.date(),
                    "is_today": False,
                    "time": start.strftime("%H:%M") if start.time() != datetime.min.time() else None
                })

        future_events = sorted(future_events, key=lambda x: x["sort_date"])[:3]
        return today_events, future_events
    except Exception as e:
        print("Błąd pobierania kalendarza Apple:", e)
        return [], []
