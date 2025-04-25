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
    "#0b8043": 10,  # basil
    "#D50000": 11,  # tomato
    "#3F51B5": 9,  # blueberry
    "#FBD75B": 5  # banana
}
# todo - add the entire list of supported event colors
event_color_code_dict = {
    'lib': '#3F51B5',
    'exp': '#D50000',
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


def generate_event(title, start_date, start_time='0000', color_code='#D50000', duration_minutes=1440, description=None,
                   all_day=False):
    from datetime import datetime

    date_start, date_end = None, None

    start_date = start_date[:start_date.index("T")]
    start_date_str = f"{start_date}T{start_time}"
    dt_start = datetime.strptime(start_date_str, "%Y-%m-%dT%H%M")
    logging.log(logging.INFO, dt_start)

    date_start = dt_start.strftime(f"%Y-%m-%dT%H:%M:%S{time_diff}:00")  # change this -04 to -05 when EDT gets over

    dt_end = dt_start + timedelta(minutes=duration_minutes)
    date_end = dt_end.strftime(f"%Y-%m-%dT%H:%M:%S{time_diff}:00")

    color_code = color_code_dict.get(color_code, 11)
    # https://lukeboyle.com/blog/posts/google-calendar-api-color-id
    # https://google-calendar-simple-api.readthedocs.io/en/latest/colors.html

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
    if all_day:
        event['reminders'] = {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 4320},
                {'method': 'popup', 'minutes': 1440},
            ]
        }
    print(event)
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

    event = generate_event(title, start_dt, start_time, duration_minutes=duration, color_code=color_code)
    event = service.events().insert(calendarId='primary', body=event).execute()
    print(f"Event created: {event.get('htmlLink')}")
    return {}, 200


@app.route('/cal/expiry', methods=['POST'])
def create_expiry():
    # create expiry node
    data = request.get_json()
    # print(data)
    title = f"expiry: {data['Data']}".lower()
    start_dt = data['Date']

    event = generate_event(title, start_dt, all_day=True, color_code=event_color_code_dict['exp'])
    event = service.events().insert(calendarId='primary', body=event).execute()
    print(f"Event created: {event.get('htmlLink')}")
    return {}, 200


@app.route('/cal/lib', methods=['POST'])
def create_lib_data():
    # create lib node
    data = request.get_json()
    # print(data)
    book = data['BookName']

    if data['BorrowDate']:
        title = f"lib: borrowed - {book}"
        dt = data['BorrowDate']
        event = generate_event(title, dt, all_day=True, color_code=event_color_code_dict['lib'])
        event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Borrow date event created: {event.get('htmlLink')}")

    if data['ReturnDate']:
        title = f"lib: to return - {book}"
        dt = data['ReturnDate']
        event = generate_event(title, dt, all_day=True, color_code=event_color_code_dict['lib'])
        event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Return date event created: {event.get('htmlLink')}")

    if data['ReturnedDate']:
        title = f"lib: returned - {book}"
        dt = data['ReturnedDate']
        event = generate_event(title, dt, all_day=True, color_code=event_color_code_dict['lib'])
        event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Returned date event created: {event.get('htmlLink')}")

    return {}, 200


if __name__ == '__main__':
    try:
        create_token_if_expired()
    except Exception as e:
        print("Removing the token.json as it seems to have expired. Requesting new login for new token generation now!")
        os.remove("token.json")
        create_token_if_expired()  # retrying to get the new token created

    app.run(port=8089, debug=True)
