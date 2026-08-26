from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
import requests

app = Flask(__name__)

APPS_SCRIPT_URL = "https://script.google.com/a/macros/shopee.com/s/AKfycbw2DxD1ACp8_UBkXEjf-u6uYn2QuD4jbdbMcavKFd8hqFmX3szeN10Tq80xJO8ROj-i/exec"


@app.route("/", methods=["GET", "POST"])
def webhook():
    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("ARGS:", request.args.to_dict())
    print("RAW:", request.get_data(as_text=True))

    # GET 測試用
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    data = request.get_json(silent=True)
    print("JSON:", data)

    # SeaTalk Event Callback 驗證
    if (
        data
        and "event" in data
        and isinstance(data["event"], dict)
        and "seatalk_challenge" in data["event"]
    ):
        challenge = data["event"]["seatalk_challenge"]
        print("RETURN JSON CHALLENGE:", challenge)

        return jsonify({
            "seatalk_challenge": challenge
        }), 200

    # 處理 SeaTalk 訊息事件
    handle_seatalk_event(data)

    return jsonify({
        "status": "ok"
    }), 200


def handle_seatalk_event(data):
    if not data:
        print("NO DATA")
        return

    event_type = data.get("event_type", "")
    event = data.get("event", {})

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
    plain_text = text_obj.get("plain_text") or text_obj.get("content") or ""

    print("GROUP_ID:", group_id)
    print("MESSAGE_ID:", message_id)
    print("THREAD_ID:", thread_id)
    print("SENDER:", sender)
    print("MESSAGE_SENT_TIME:", message_sent_time)
    print("TEXT:", plain_text)

    # 偵測維修完成
    if "維修完成" in plain_text:
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
    try:
        response = requests.post(
            APPS_SCRIPT_URL,
            json=payload,
            timeout=10
        )

        print("APPS_SCRIPT_STATUS:", response.status_code)
        print("APPS_SCRIPT_RESPONSE:", response.text)

    except Exception as e:
        print("APPS_SCRIPT_ERROR:", str(e))


def convert_timestamp_to_taipei(timestamp):
    try:
        dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        taipei_dt = dt.astimezone(timezone(timedelta(hours=8)))
        return taipei_dt.strftime("%Y/%m/%d %H:%M:%S")
    except Exception:
        return ""


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
