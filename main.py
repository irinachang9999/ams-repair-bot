import os
import threading
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify


app = Flask(__name__)

REPAIR_EVENTS = []
REPAIR_EVENTS_LOCK = threading.Lock()

COMPLETION_KEYWORDS = (
    "維修完成",
    "修復完成",
    "已修復",
    "已完成",
    "處理完成",
    "完修",
)


@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")

        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    data = request.get_json(silent=True)

    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("JSON:", data)

    if not isinstance(data, dict):
        return jsonify({"status": "ok"}), 200

    # SeaTalk callback 驗證
    event_data = data.get("event", {})

    if (
        isinstance(event_data, dict)
        and "seatalk_challenge" in event_data
    ):
        return jsonify({
            "seatalk_challenge": event_data["seatalk_challenge"]
        }), 200

    # 接收並暫存維修完成事件
    handle_seatalk_event(data)

    return jsonify({"status": "ok"}), 200


def handle_seatalk_event(data):
    event_type = data.get("event_type", "")
    event_data = data.get("event", {})

    if not isinstance(event_data, dict):
        return

    message = event_data.get("message", {})

    if not isinstance(message, dict):
        return

    group_id = event_data.get("group_id", "")
    message_id = message.get("message_id", "")
    thread_id = message.get("thread_id", "")
    message_sent_time = message.get("message_sent_time", "")

    sender = message.get("sender", {})

    if not isinstance(sender, dict):
        sender = {}

    text_data = message.get("text", {})

    if not isinstance(text_data, dict):
        text_data = {}

    plain_text = (
        text_data.get("plain_text")
        or text_data.get("content")
        or ""
    )

    if not isinstance(plain_text, str):
        plain_text = str(plain_text)

    print("EVENT_TYPE:", event_type)
    print("GROUP_ID:", group_id)
    print("MESSAGE_ID:", message_id)
    print("THREAD_ID:", thread_id)
    print("TEXT:", plain_text)

    # 只處理維修完成類訊息
    if not any(
        keyword in plain_text
        for keyword in COMPLETION_KEYWORDS
    ):
        print("NOT REPAIR COMPLETED")
        return

    completed_time = convert_timestamp_to_taipei(
        message_sent_time
    )

    repair_event = {
        "event_id": data.get("event_id", ""),
        "event_type": event_type,
        "repair_event_type": "repair_completed",
        "group_id": group_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "sender_email": sender.get("email", ""),
        "sender_employee_code": sender.get(
            "employee_code", ""
        ),
        "message": plain_text,
        "plain_text": plain_text,
        "message_sent_time": message_sent_time,
        "completed_time": completed_time,
        "raw": data,
    }

    event_key = (
        repair_event["event_id"]
        or repair_event["message_id"]
    )

    with REPAIR_EVENTS_LOCK:
        # 避免 SeaTalk 重送造成重複資料
        if event_key:
            for old_event in REPAIR_EVENTS:
                old_key = (
                    old_event.get("event_id")
                    or old_event.get("message_id")
                )

                if old_key == event_key:
                    print("DUPLICATE EVENT")
                    return

        REPAIR_EVENTS.append(repair_event)

    print(">>> DETECTED_REPAIR_COMPLETED <<<")
    print("QUEUE_COUNT:", len(REPAIR_EVENTS))


@app.route("/events/peek", methods=["GET"])
def peek_events():
    with REPAIR_EVENTS_LOCK:
        events = list(REPAIR_EVENTS)

    return jsonify({
        "count": len(events),
        "events": events,
    }), 200


@app.route("/events", methods=["GET"])
def get_events():
    # Apps Script 使用這個網址取資料，取出後清空佇列
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
        count = len(REPAIR_EVENTS)
        REPAIR_EVENTS.clear()

    return jsonify({
        "cleared": count,
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


def convert_timestamp_to_taipei(timestamp):
    try:
        if not timestamp:
            return ""

        utc_datetime = datetime.fromtimestamp(
            int(timestamp),
            tz=timezone.utc
        )

        taipei_datetime = utc_datetime.astimezone(
            timezone(timedelta(hours=8))
        )

        return taipei_datetime.strftime(
            "%Y/%m/%d %H:%M:%S"
        )

    except Exception as error:
        print("TIMESTAMP_ERROR:", error)
        return ""


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port
    )
