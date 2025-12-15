from googleapiclient.discovery import build
from google_calendar import get_credentials

def get_gmail_service(user_id=None):
    creds = get_credentials(user_id)
    return build('gmail', 'v1', credentials=creds)


def get_unread_email_count(user_id=None):
    service = get_gmail_service(user_id)
    label = service.users().labels().get(userId='me', id='INBOX').execute()
    return label.get('messagesUnread', 0)


def get_recent_emails(user_id=None, max_results=5):
    service = get_gmail_service(user_id)
    result = service.users().messages().list(
        userId='me',
        labelIds=['INBOX'],
        maxResults=max_results,
        q=''   # tu kiedyś możesz dodać np. 'is:unread'
    ).execute()

    messages = []
    for meta in result.get('messages', []):
        msg = service.users().messages().get(
            userId='me',
            id=meta['id'],
            format='metadata',
            metadataHeaders=['Subject', 'From', 'Date']
        ).execute()

        headers = {
            h['name']: h['value']
            for h in msg.get('payload', {}).get('headers', [])
        }

        messages.append({
            "id": msg["id"],
            "subject": headers.get("Subject", "(brak tematu)"),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", "")
        })

    return messages
