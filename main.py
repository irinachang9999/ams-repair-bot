import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify


app = Flask(__name__)

REPAIR_EVENTS = []
REPAIR_EVENTS_LOCK = threading.Lock()

TOKEN_LOCK = threading.Lock()
SEATALK_TOKEN = ""
SEATALK_TOKEN_EXPIRES_AT = 0

SEATALK_APP_ID = os.getenv("SEATALK_APP_ID", "").strip()
SEATALK_APP_SECRET = os.getenv("SEATALK_APP_SECRET", "").strip()
SEATALK_API_BASE = "https://openapi.seatalk.io"

COMPLETION_KEYWORDS = (
    "維修完成",
    "修復完成",
    "已修復",
    "已完成",
    "處理完成",
    "完修",
    "維修方式",
)


def get_seatalk_access_token():
    global SEATALK_TOKEN
    global SEATALK_TOKEN_EXPIRES_AT

    if not SEATALK_APP_ID or not SEATALK_APP_SECRET:
        print("SEATALK_ERROR: App ID or App Secret is missing")
        return ""

    with TOKEN_LOCK:
        now = int(time.time())

        if SEATALK_TOKEN and SEATALK_TOKEN_EXPIRES_AT > now + 60:
            return SEATALK_TOKEN

        try:
            response = requests.post(
                f"{SEATALK_API_BASE}/auth/app_access_token",
                json={
                    "app_id": SEATALK_APP_ID,
                    "app_secret": SEATALK_APP_SECRET,
                },
                timeout=4,
            )

            print("SEATALK_TOKEN_STATUS:", response.status_code)

            if response.status_code != 200:
                print("SEATALK_TOKEN_ERROR:", response.text[:300])
                return ""

            body = response.json()
            token = body.get("app_access_token", "")

            if not token:
                print("SEATALK_TOKEN_ERROR: token not found")
                return ""

            expire = body.get("expire")

            if expire:
                expires_at = int(expire)
            else:
                expires_at = now + int(body.get("expires_in", 3600))

            SEATALK_TOKEN = token
            SEATALK_TOKEN_EXPIRES_AT = expires_at

            return SEATALK_TOKEN

        except Exception as error:
            print("SEATALK_TOKEN_EXCEPTION:", str(error))
            return ""


def get_thread_messages(group_id, thread_id):
    token = get_seatalk_access_token()

    if not token:
        return [], "access_token_not_available"

    try:
        response = requests.get(
            f"{SEATALK_API_BASE}/messaging/v2/group_chat/get_thread_by_thread_id",
            params={
                "group_id": group_id,
                "thread_id": thread_id,
                "page_size": 50,
            },
            headers={
                "Authorization": f"Bearer {token}",
            },
            timeout=4,
        )

        print("SEATALK_THREAD_STATUS:", response.status_code)

        if response.status_code != 200:
            return [], f"http_{response.status_code}"

        body = response.json()

        if body.get("code") not in (None, 0):
            return [], f"seatalk_code_{body.get('code')}"

        messages = body.get("thread_messages", [])

        if not isinstance(messages, list):
            return [], "thread_messages_invalid"

        return messages, ""

    except Exception as error:
        print("SEATALK_THREAD_EXCEPTION:", str(error))
        return [], str(error)


def get_message_text(message):
    if not isinstance(message, dict):
        return ""

    text_obj = message.get("text", {})

    if not isinstance(text_obj, dict):
        return ""

    return (
        text_obj.get("plain_text")
        or text_obj.get("content")
        or ""
    )


def find_root_message(messages):
    if not messages:
        return {}

    # 正常情況：主文的 thread_id 等於自己的 message_id
    for message in messages:
        if (
            message.get("message_id")
            and message.get("message_id") == message.get("thread_id")
        ):
            return message

    # 如果 API 沒有提供明確主文，改取最早的一則
    return sorted(
        messages,
        key=lambda item: int(item.get("message_sent_time", 0) or 0)
    )[0]


def extract_ams_no(*texts):
    patterns = (
        r"RR單號\s*[:：]?\s*(RR\d{6,})",
        r"(?:detail/|/)(RR\d{6,})(?:[/?\s]|$)",
        r"\b(RR\d{6,})\b",
    )

    for text in texts:
        if not text:
            continue

        for pattern in patterns:
            match = re.search(pattern, str(text), re.IGNORECASE)

            if match:
                return match.group(1).upper()

    return ""


def convert_timestamp_to_taipei(timestamp):
    try:
        utc_datetime = datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc,
        )

        taipei_datetime = utc_datetime.astimezone(
            timezone(timedelta(hours=8))
        )

        return taipei_datetime.strftime("%Y/%m/%d %H:%M:%S")

    except Exception as error:
        print("TIMESTAMP_ERROR:", str(error))
        return ""


def append_repair_event(payload):
    event_id = payload.get("event_id", "")
    message_id = payload.get("message_id", "")

    with REPAIR_EVENTS_LOCK:
        for old_event in REPAIR_EVENTS:
            if event_id and old_event.get("event_id") == event_id:
                return

            if message_id and old_event.get("message_id") == message_id:
                return

        REPAIR_EVENTS.append(payload)

        print("EVENT_QUEUED:", payload.get("event_id"))
        print("AMS_NO:", payload.get("ams_no"))
        print("QUEUE_COUNT:", len(REPAIR_EVENTS))


def handle_seatalk_event(data):
    event_type = data.get("event_type", "")
    event = data.get("event", {})

    if not isinstance(event, dict):
        print("INVALID_EVENT")
        return

    message = event.get("message", {})

    if not isinstance(message, dict):
        print("NO_MESSAGE")
        return

    text = get_message_text(message)

    if not any(keyword in text for keyword in COMPLETION_KEYWORDS):
        print("NOT_REPAIR_EVENT")
        return

    group_id = event.get("group_id", "")
    thread_id = (
        message.get("thread_id")
        or event.get("thread_id", "")
    )

    message_id = message.get("message_id", "")
    message_sent_time = message.get("message_sent_time", "")

    sender = message.get("sender", {})

    if not isinstance(sender, dict):
        sender = {}

    main_message_text = ""
    main_message_id = ""
    thread_lookup_status = "not_requested"

    if group_id and thread_id:
        thread_messages, thread_error = get_thread_messages(
            group_id,
            thread_id,
        )

        if thread_messages:
            root_message = find_root_message(thread_messages)
            main_message_text = get_message_text(root_message)
            main_message_id = root_message.get("message_id", "")
            thread_lookup_status = "success"
        else:
            thread_lookup_status = thread_error or "no_thread_messages"

    ams_no = extract_ams_no(
        main_message_text,
        text,
    )

    event_id = (
        data.get("event_id")
        or message_id
        or f"{group_id}:{thread_id}:{message_sent_time}"
    )

    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "repair_event_type": "repair_completed",
        "group_id": group_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "main_message_id": main_message_id,
        "sender_email": sender.get("email", ""),
        "sender_employee_code": sender.get("employee_code", ""),
        "message": text,
        "plain_text": text,
        "main_message": main_message_text,
        "ams_no": ams_no,
        "message_sent_time": message_sent_time,
        "completed_time": convert_timestamp_to_taipei(
            message_sent_time
        ),
        "thread_lookup_status": thread_lookup_status,
        "raw": data,
    }

    print("DETECTED_REPAIR_EVENT")
    print("AMS_NO:", ams_no)
    print("MAIN_MESSAGE:", main_message_text[:300])
    print("THREAD_LOOKUP_STATUS:", thread_lookup_status)

    append_repair_event(payload)


@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")

        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"status": "ok"}), 200

    event = data.get("event", {})

    if (
        isinstance(event, dict)
        and "seatalk_challenge" in event
    ):
        return jsonify({
            "seatalk_challenge": event["seatalk_challenge"]
        }), 200

    handle_seatalk_event(data)

    return jsonify({
        "status": "ok"
    }), 200


@app.route("/events/peek", methods=["GET"])
def peek_events():
    with REPAIR_EVENTS_LOCK:
        events = list(REPAIR_EVENTS)

    return jsonify({
        "count": len(events),
        "events": events,
    }), 200


@app.route("/events", methods=["GET"])
def fetch_events():
    with REPAIR_EVENTS_LOCK:
        events = list(REPAIR_EVENTS)
        REPAIR_EVENTS.clear()

    return jsonify({
        "count": len(events),
        "events": events,
    }), 200


@app.route("/events/clear", methods=["GET", "POST"])
def clear_events():
    with REPAIR_EVENTS_LOCK:
        REPAIR_EVENTS.clear()

    return jsonify({
        "status": "cleared"
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port,
    )
