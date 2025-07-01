from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import os.path
from datetime import datetime, timedelta
import pytz

SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/tasks.readonly'
]

def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds


def get_upcoming_events():
    creds = get_credentials()
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.utcnow().isoformat() + 'Z'
    tz = pytz.timezone('Europe/Warsaw')
    today_date = datetime.now(tz).date()

    events_result = service.events().list(
        calendarId='primary', timeMin=now,
        maxResults=50, singleEvents=True,
        orderBy='startTime'
    ).execute()
    events = events_result.get('items', [])

    today_events = []
    future_events = []

    for event in events:
        title = event.get('summary', 'Bez tytułu')
        start_raw = event['start']
        end_raw = event['end']

        # Całodniowe
        if 'date' in start_raw:
            start_date = datetime.fromisoformat(start_raw['date']).date()
            end_date = datetime.fromisoformat(end_raw['date']).date() - timedelta(days=1)
            duration = (end_date - start_date).days + 1

            if duration > 1:
                date_str = f"{start_date.strftime('%d.%m')}–{end_date.strftime('%d.%m')}"
            else:
                date_str = start_date.strftime('%d.%m')

            event_data = {
                "title": title,
                "date_str": date_str,
                "sort_date": start_date,
                "is_today": start_date == today_date,
                "time": None
            }

        # Z konkretną godziną
        else:
            start_dt = datetime.fromisoformat(start_raw['dateTime']).astimezone(tz)
            show_time = start_dt.strftime("%H:%M")
            show_time = None if show_time == "00:00" else show_time

            event_data = {
                "title": title,
                "date_str": start_dt.strftime('%d.%m'),
                "sort_date": start_dt.date(),
                "is_today": start_dt.date() == today_date,
                "time": show_time
            }

        if event_data["is_today"]:
            today_events.append(event_data)
        else:
            future_events.append(event_data)

    future_events = sorted(future_events, key=lambda x: x["sort_date"])[:3]

    return today_events, future_events


def get_google_tasks():
    creds = get_credentials()
    service = build('tasks', 'v1', credentials=creds)

    tasklists = service.tasklists().list().execute().get('items', [])
    all_tasks = []

    tz = pytz.timezone('Europe/Warsaw')
    today = datetime.now(tz).date()

    for tasklist in tasklists:
        tasks = service.tasks().list(tasklist=tasklist['id']).execute().get('items', [])
        for task in tasks:
            if task.get('status') == 'completed':
                continue

            title = task.get('title', 'Bez tytułu')
            due_raw = task.get('due')

            if due_raw:
                due_date = datetime.fromisoformat(due_raw.replace('Z', '+00:00')).astimezone(tz).date()
                due_str = due_date.strftime('%d.%m')

                if due_date < today:
                    title += ' (oczekujące)'
            else:
                due_str = "Brak terminu"

            all_tasks.append({
                "title": title,
                "due": due_str
            })

    return all_tasks