from flask import Flask, request
from flask_cors import CORS
import logging
from datetime import timedelta, datetime
import os.path
import os

# pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)
CORS(app)
SCOPES = ["https://www.googleapis.com/auth/calendar"]

color_code_dict = {
    "#33b679": 2,  # sage
    "#0b8043": 10  # basil
}
edt_est_time_diff = {
    "EDT": "-04",
    "EST": "-05"
}
timezone = "EDT"  # CHANGE ONCE DAYLIGHT GOES ON / OFF
time_diff = edt_est_time_diff[timezone]
service = None


def create_token_if_expired():
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    global service
    service = build('calendar', 'v3', credentials=creds)


def generate_event(title, color_code, start_date, start_time, duration_minutes, description=None):
    from datetime import datetime
    start_date = start_date[:start_date.index("T")]
    start_date_str = f"{start_date}T{start_time}"
    dt_start = datetime.strptime(start_date_str, "%Y-%m-%dT%H%M")
    logging.log(logging.INFO, dt_start)
    date_start = dt_start.strftime(f"%Y-%m-%dT%H:%M:%S{time_diff}:00")  # change this -04 to -05 when EDT gets over

    dt_end = dt_start + timedelta(minutes=duration_minutes)
    date_end = dt_end.strftime(f"%Y-%m-%dT%H:%M:%S{time_diff}:00")  # change this -04 to -05 when EDT gets over

    color_code = color_code_dict[color_code]
    # https://lukeboyle.com/blog/posts/google-calendar-api-color-id

    event = {
        'summary': title,
        'colorId': color_code,
        # matches the yellow-orange color being used manually =>   '5': {'background': '#fbd75b', 'foreground': '#1d1d1d'},
        'start': {
            'dateTime': date_start,
            'timeZone': 'Canada/Eastern',
        },
        'end': {
            'dateTime': date_end,
            'timeZone': 'Canada/Eastern',
            # 'timeZone': 'Etc/GMT-4',
            # 'timeZone': 'EST5EDT',
        },
    }
    if description:
        event['description'] = description
    return event


@app.route('/cal/session', methods=['POST'])
def create_session():
    # create session node
    data = request.get_json()
    title = f"{data['Mode']['SessionMode'].lower()} {data['Student'].lower()} {data['Subject']['SessionSubject'].lower()}"
    color_code = f"{data['Mode']['Color']}"
    start_dt = data['SessionDate']
    start_time = data['SessionStartTime']
    duration = data['SessionLengthInMinutes']

    event = generate_event(title, color_code, start_dt, start_time, duration)
    event = service.events().insert(calendarId='primary', body=event).execute()
    print(f"Event created: {event.get('htmlLink')}")
    return {}, 200


if __name__ == '__main__':
    try:
        create_token_if_expired()
    except Exception as e:
        print("Removing the token.json as it seems to have expired. Requesting new login for new token generation now!")
        os.remove("token.json")
        create_token_if_expired()  # retrying to get the new token created

    app.run(port=8089, debug=True)
