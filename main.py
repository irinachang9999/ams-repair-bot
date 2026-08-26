from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def webhook():
    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("ARGS:", request.args.to_dict())
    print("RAW:", request.get_data(as_text=True))

    # GET 測試
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    data = request.get_json(silent=True)
    print("JSON:", data)

    # SeaTalk 驗證
    if (
        data
        and "event" in data
        and isinstance(data["event"], dict)
        and "seatalk_challenge" in data["event"]
    ):
        challenge = data["event"]["seatalk_challenge"]
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
        return

    event_type = data.get("event_type")
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

    if "維修完成" in plain_text:
        print(">>> DETECTED_REPAIR_COMPLETED <<<")
        print("完成時間:", convert_timestamp_to_taipei(message_sent_time))
        print("group_id:", group_id)
        print("thread_id:", thread_id)
        print("message_id:", message_id)
        print("sender_email:", sender.get("email", ""))
        print("message:", plain_text)


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
