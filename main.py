from flask import Flask, request, jsonify

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

    # POST 驗證
    data = request.get_json(silent=True)
    print("JSON:", data)

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

    return jsonify({
        "status": "ok"
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
