import os
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify


app = Flask(__name__)

# 從 Render Environment Variable 讀取
APPS_SCRIPT_URL = (
    os.getenv("APPS_SCRIPT_URL", "")
    .strip()
    .strip('"')
    .strip("'")
)


@app.route("/", methods=["GET", "POST"])
def webhook():
    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("ARGS:", request.args.to_dict())
    print("RAW:", request.get_data(as_text=True))

    # Render / 瀏覽器健康檢查
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")

        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    data = request.get_json(silent=True)
    print("JSON:", data)

    if not data:
        print("NO DATA")
        return jsonify({"status": "ok"}), 200

    # SeaTalk Event Callback 驗證
    event = data.get("event", {})

    if (
        isinstance(event, dict)
        and "seatalk_challenge" in event
    ):
        challenge = event["seatalk_challenge"]

        print("RETURN JSON CHALLENGE:", challenge)

        return jsonify({
            "seatalk_challenge": challenge
        }), 200

    # 處理 SeaTalk 事件
    handle_seatalk_event(data)

    return jsonify({
        "status": "ok"
    }), 200


def handle_seatalk_event(data):
    event_type = data.get("event_type", "")
    event = data.get("event", {})

    if not isinstance(event, dict):
        print("INVALID EVENT")
        return

    print("EVENT_TYPE:", event_type)

    message = event.get("message")

    if not message:
        print("NO MESSAGE EVENT")
        return

    group_id = event.get("group_id", "")
    message_id = message.get("message_id", "")
    thread_id = message.get("thread_id", "")
    sender = message.get("sender", {})
    message_sent_time = message.get("message_sent_time", "")

    text_obj = message.get("text", {})

    if not isinstance(text_obj, dict):
        text_obj = {}

    plain_text = (
        text_obj.get("plain_text")
        or text_obj.get("content")
        or ""
    )

    print("GROUP_ID:", group_id)
    print("MESSAGE_ID:", message_id)
    print("THREAD_ID:", thread_id)
    print("SENDER:", sender)
    print("MESSAGE_SENT_TIME:", message_sent_time)
    print("TEXT:", plain_text)

    # 偵測維修完成訊息
    if "維修完成" not in plain_text:
        print("NOT REPAIR COMPLETED")
        return

    completed_time = convert_timestamp_to_taipei(message_sent_time)

    payload = {
        "event_type": "repair_completed",
        "group_id": group_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "sender_email": sender.get("email", ""),
        "sender_employee_code": sender.get("employee_code", ""),
        "message": plain_text,
        "completed_time": completed_time,
        "raw": data
    }

    print(">>> DETECTED_REPAIR_COMPLETED <<<")
    print("PAYLOAD:", payload)

    send_to_apps_script(payload)


def send_to_apps_script(payload):
    if not APPS_SCRIPT_URL:
        print("APPS_SCRIPT_ERROR: APPS_SCRIPT_URL is not configured")
        return

    print(
        "APPS_SCRIPT_URL_CONFIGURED:",
        bool(APPS_SCRIPT_URL)
    )

    print(
        "APPS_SCRIPT_URL_IS_EXEC:",
        APPS_SCRIPT_URL.endswith("/exec")
    )

    try:
        response = requests.post(
            APPS_SCRIPT_URL,
            json=payload,
            timeout=15
        )

        print("APPS_SCRIPT_STATUS:", response.status_code)

        # 避免把整段 Google HTML 錯誤頁寫進 Log
        response_text = response.text[:500]

        print("APPS_SCRIPT_RESPONSE:", response_text)

    except requests.exceptions.Timeout:
        print("APPS_SCRIPT_ERROR: request timeout")

    except requests.exceptions.RequestException as error:
        print("APPS_SCRIPT_ERROR:", str(error))

    except Exception as error:
        print("APPS_SCRIPT_UNEXPECTED_ERROR:", str(error))


def convert_timestamp_to_taipei(timestamp):
    try:
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
        print("TIMESTAMP_ERROR:", str(error))
        return ""


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))

    app.run(
        host="0.0.0.0",
        port=port
    )
