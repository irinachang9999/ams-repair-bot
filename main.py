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
SEEN_EVENT_IDS = set()

TOKEN_LOCK = threading.Lock()
SEATALK_TOKEN = ""
SEATALK_TOKEN_EXPIRES_AT = 0

SEATALK_APP_ID = os.getenv("SEATALK_APP_ID", "").strip()
SEATALK_APP_SECRET = os.getenv("SEATALK_APP_SECRET", "").strip()
SEATALK_GROUP_IDS = os.getenv("SEATALK_GROUP_IDS", "").strip()
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
                timeout=10,
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


def get_message_text(message):
    if not isinstance(message, dict):
        return ""

    parts = []

    def collect(node):
        if isinstance(node, str):
            value = node.strip()
            if value:
                parts.append(value)
            return

        if isinstance(node, list):
            for item in node:
                collect(item)
            return

        if not isinstance(node, dict):
            return

        for key, value in node.items():
            if key in (
                "plain_text",
                "content",
                "text",
                "interactive_message",
                "service_notice",
                "default",
                "elements",
                "element",
                "title",
                "description",
                "button",
                "button_group",
                "redirect",
                "mobile_link",
                "desktop_link",
                "path",
                "url",
                "href",
            ):
                collect(value)

    collect(message.get("text", {}))
    collect(message.get("interactive_message", {}))
    collect(message.get("service_notice", {}))

    result = []
    seen = set()

    for item in parts:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return "\n".join(result)


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


def extract_order_no(*texts):
    patterns = (
        r"(?:事件影響訂單編號|訂單編號|訂單號碼)"
        r"\s*[:：]?\s*(TW\d{6,})",
        r"\b(TW\d{6,})\b",
    )

    for text in texts:
        if not text:
            continue

        for pattern in patterns:
            match = re.search(pattern, str(text), re.IGNORECASE)
            if match:
                return match.group(1).upper()

    return ""


def extract_single_line(text, labels):
    if not text:
        return ""

    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*[:：]?\s*([^\r\n]+)",
        str(text),
        re.IGNORECASE,
    )

    return match.group(1).strip() if match else ""


def extract_multiline_field(text, labels):
    if not text:
        return ""

    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_labels = (
        "已解決",
        "是否解決",
        "已解決?",
        "RR單號",
        "訂單編號",
        "訂單號碼",
        "事件影響訂單編號",
        "回報時間",
        "報修時間",
        "成立時間",
        "執行人員",
        "異常情形描述",
        "問題描述",
        "故障說明",
        "影響區域",
        "櫃位號碼",
        "LockerID",
        "Locker ID",
        "備註",
        "查看詳情",
        "上傳證明",
    )
    stop_pattern = "|".join(re.escape(label) for label in stop_labels)

    match = re.search(
        rf"(?:{label_pattern})\s*[:：]?\s*"
        rf"([\s\S]*?)"
        rf"(?=\n\s*(?:{stop_pattern})\s*[:：]?|\Z)",
        str(text),
        re.IGNORECASE,
    )

    if not match:
        return ""

    value = match.group(1).strip()
    return re.sub(r"\s+", " ", value)


def extract_repair_method(text):
    value = extract_multiline_field(
        text,
        (
            "維修方式",
            "修復方式",
            "現場處理事項",
        ),
    )

    if value:
        return value

    return extract_single_line(
        text,
        (
            "維修方式",
            "修復方式",
            "現場處理事項",
        ),
    )


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
        if event_id and event_id in SEEN_EVENT_IDS:
            return False

        for old_event in REPAIR_EVENTS:
            if event_id and old_event.get("event_id") == event_id:
                return False
            if message_id and old_event.get("message_id") == message_id:
                return False

        REPAIR_EVENTS.append(payload)

        if event_id:
            SEEN_EVENT_IDS.add(event_id)

        print("EVENT_QUEUED:", event_id)
        print("AMS_NO:", payload.get("ams_no"))
        print("ORDER_NO:", payload.get("order_no"))
        print("QUEUE_COUNT:", len(REPAIR_EVENTS))
        return True


def get_thread_messages(group_id, thread_id):
    token = get_seatalk_access_token()

    if not token:
        return [], "access_token_not_available"

    try:
        response = requests.get(
            f"{SEATALK_API_BASE}/messaging/v2/"
            "group_chat/get_thread_by_thread_id",
            params={
                "group_id": group_id,
                "thread_id": thread_id,
                "page_size": 100,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

        print("SEATALK_THREAD_STATUS:", response.status_code)

        if response.status_code != 200:
            return [], f"http_{response.status_code}"

        body = response.json()
        code = body.get("code")

        if code not in (None, 0, "0"):
            return [], f"seatalk_code_{code}"

        messages = body.get("thread_messages", [])

        if not isinstance(messages, list):
            return [], "thread_messages_invalid"

        return messages, ""

    except Exception as error:
        print("SEATALK_THREAD_EXCEPTION:", str(error))
        return [], str(error)


def find_root_message(messages):
    if not messages:
        return {}

    for message in messages:
        if (
            isinstance(message, dict)
            and message.get("message_id")
            and message.get("message_id") == message.get("thread_id")
        ):
            return message

    valid_messages = [item for item in messages if isinstance(item, dict)]

    if not valid_messages:
        return {}

    return min(
        valid_messages,
        key=lambda item: int(item.get("message_sent_time", 0) or 0),
    )


def parse_manual_group_ids():
    return [
        group_id.strip()
        for group_id in re.split(r"[,;\s]+", SEATALK_GROUP_IDS)
        if group_id.strip()
    ]


def get_group_ids():
    """Return (group_ids, error). The configured four IDs are preferred."""
    manual_ids = list(dict.fromkeys(parse_manual_group_ids()))

    if manual_ids:
        print("SEATALK_CONFIGURED_GROUP_COUNT:", len(manual_ids))
        return manual_ids, ""

    token = get_seatalk_access_token()

    if not token:
        return [], "access_token_not_available"

    group_ids = []
    cursor = ""
    last_error = ""

    try:
        for _ in range(5):
            params = {"page_size": 100}

            if cursor:
                params["cursor"] = cursor

            response = requests.get(
                f"{SEATALK_API_BASE}/messaging/v2/group_chat/joined",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )

            print("SEATALK_GROUP_LIST_STATUS:", response.status_code)

            if response.status_code != 200:
                last_error = f"http_{response.status_code}"
                break

            body = response.json()
            code = body.get("code")

            if code not in (None, 0, "0"):
                last_error = f"seatalk_code_{code}"
                break

            joined = body.get("joined_group_chats", {})

            if isinstance(joined, dict):
                current_ids = joined.get("group_id", [])
                if isinstance(current_ids, list):
                    group_ids.extend(
                        str(group_id).strip()
                        for group_id in current_ids
                        if str(group_id).strip()
                    )

            cursor = body.get("next_cursor", "") or ""

            if not cursor:
                break

        group_ids = list(dict.fromkeys(group_ids))

        if group_ids:
            return group_ids, ""

        return [], last_error or "no_joined_groups"

    except Exception as error:
        print("SEATALK_GROUP_LIST_EXCEPTION:", str(error))
        return [], str(error)


def get_group_chat_history(group_id):
    token = get_seatalk_access_token()

    if not token:
        return [], "access_token_not_available"

    all_messages = []
    cursor = ""

    try:
        for _ in range(5):
            params = {
                "group_id": group_id,
                "page_size": 100,
            }

            if cursor:
                params["cursor"] = cursor

            response = requests.get(
                f"{SEATALK_API_BASE}/messaging/v2/group_chat/history",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=12,
            )

            print(
                "SEATALK_HISTORY_STATUS:",
                group_id,
                response.status_code,
            )

            if response.status_code != 200:
                return [], f"http_{response.status_code}"

            body = response.json()
            code = body.get("code")

            if code not in (None, 0, "0"):
                return [], f"seatalk_code_{code}"

            messages = body.get("chat_history", [])

            if isinstance(messages, list):
                all_messages.extend(messages)

            cursor = body.get("next_cursor", "") or ""

            if not cursor:
                break

        return all_messages, ""

    except Exception as error:
        print("SEATALK_HISTORY_EXCEPTION:", str(error))
        return [], str(error)


def is_repair_report(text):
    if not text:
        return False

    text = str(text)

    if any(label in text for label in (
        "RR單號",
        "事件影響訂單編號",
        "訂單編號",
        "現場處理事項",
    )):
        return True

    if "LockerID" in text and any(
        word in text for word in ("異常", "回報", "報修")
    ):
        return True

    if "維修" in text and any(
        word in text for word in ("回報", "報修", "異常")
    ):
        return True

    return False


def build_history_record(group_id, message):
    if not isinstance(message, dict):
        return None

    message_id = message.get("message_id", "")

    if not message_id:
        return None

    text = get_message_text(message)

    if not is_repair_report(text):
        return None

    sender = message.get("sender", {})
    if not isinstance(sender, dict):
        sender = {}

    return {
        "event_id": f"history:{group_id}:{message_id}",
        "source_type": "group_history",
        "event_type": "group_history",
        "repair_event_type": "repair_report",
        "group_id": group_id,
        "thread_id": message.get("thread_id") or message_id,
        "message_id": message_id,
        "main_message_id": message_id,
        "sender_email": sender.get("email", ""),
        "sender_employee_code": sender.get("employee_code", ""),
        "message": text,
        "plain_text": text,
        "main_message": text,
        "ams_no": extract_ams_no(text),
        "order_no": extract_order_no(text),
        "locker_id": extract_single_line(text, ("LockerID", "Locker ID")),
        "report_time": extract_single_line(
            text,
            ("回報時間", "報修時間"),
        ),
        "issue_description": extract_single_line(
            text,
            ("異常情形描述", "問題描述", "故障說明"),
        ),
        "affected_area": extract_single_line(
            text,
            ("影響區域", "櫃位號碼"),
        ),
        "field_handling": extract_repair_method(text),
        "repair_method": extract_repair_method(text),
        "message_sent_time": message.get("message_sent_time", ""),
        "completed_time": "",
        "thread_lookup_status": "history",
        "raw": message,
    }


def sync_group_history():
    group_ids, group_error = get_group_ids()

    if group_error:
        return {
            "groups": group_ids,
            "queued": 0,
            "errors": [group_error],
        }

    queued = 0
    errors = []

    for group_id in group_ids:
        messages, history_error = get_group_chat_history(group_id)

        if history_error:
            errors.append(f"{group_id}: {history_error}")
            continue

        for message in messages:
            try:
                record = build_history_record(group_id, message)
                if record and append_repair_event(record):
                    queued += 1
            except Exception as error:
                print("HISTORY_RECORD_EXCEPTION:", group_id, str(error))
                errors.append(f"{group_id}: record_error")

    return {
        "groups": group_ids,
        "queued": queued,
        "errors": errors,
    }


def handle_seatalk_event(data):
    event_type = data.get("event_type", "")
    event = data.get("event", {})

    if not isinstance(event, dict):
        return

    message = event.get("message", {})

    if not isinstance(message, dict):
        return

    reply_text = get_message_text(message)

    if not any(keyword in reply_text for keyword in COMPLETION_KEYWORDS):
        return

    group_id = event.get("group_id", "")
    thread_id = message.get("thread_id") or event.get("thread_id", "")
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

    combined_text = f"{main_message_text}\n{reply_text}"
    ams_no = extract_ams_no(main_message_text, reply_text)

    event_id = (
        data.get("event_id")
        or message_id
        or f"{group_id}:{thread_id}:{message_sent_time}"
    )

    payload = {
        "event_id": event_id,
        "source_type": "webhook",
        "event_type": event_type,
        "repair_event_type": "repair_completed",
        "group_id": group_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "main_message_id": main_message_id,
        "sender_email": sender.get("email", ""),
        "sender_employee_code": sender.get("employee_code", ""),
        "message": reply_text,
        "plain_text": reply_text,
        "main_message": main_message_text,
        "ams_no": ams_no,
        "order_no": extract_order_no(combined_text),
        "locker_id": extract_single_line(
            combined_text,
            ("LockerID", "Locker ID"),
        ),
        "report_time": extract_single_line(
            combined_text,
            ("回報時間", "報修時間"),
        ),
        "issue_description": extract_single_line(
            combined_text,
            ("異常情形描述", "問題描述", "故障說明"),
        ),
        "affected_area": extract_single_line(
            combined_text,
            ("影響區域", "櫃位號碼"),
        ),
        "field_handling": extract_repair_method(combined_text),
        "repair_method": extract_repair_method(combined_text),
        "message_sent_time": message_sent_time,
        "completed_time": convert_timestamp_to_taipei(message_sent_time),
        "thread_lookup_status": thread_lookup_status,
        "raw": data,
    }

    print("DETECTED_REPAIR_EVENT")
    print("AMS_NO:", ams_no)
    print("ORDER_NO:", payload["order_no"])
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

    if "seatalk_challenge" in data:
        return jsonify({
            "seatalk_challenge": data["seatalk_challenge"]
        }), 200

    event = data.get("event", {})

    if isinstance(event, dict) and "seatalk_challenge" in event:
        return jsonify({
            "seatalk_challenge": event["seatalk_challenge"]
        }), 200

    handle_seatalk_event(data)
    return jsonify({"status": "ok"}), 200


@app.route("/sync-history", methods=["GET"])
def sync_history():
    try:
        result = sync_group_history()
        return jsonify({
            "status": "ok",
            **result,
        }), 200
    except Exception as error:
        print("SYNC_HISTORY_EXCEPTION:", str(error))
        return jsonify({
            "status": "error",
            "groups": [],
            "queued": 0,
            "errors": [str(error)],
        }), 500


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

    return jsonify({"status": "cleared"}), 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
