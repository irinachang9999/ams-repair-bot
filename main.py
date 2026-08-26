from flask import Flask, request

app = Flask(__name__)


@app.route("/", methods=["GET", "POST"])
def webhook():

    # ===== GET =====
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            return challenge, 200

        return "Webhook Ready", 200

    # ===== POST =====
    data = request.get_json(silent=True)

    print("===== REQUEST =====")
    print(data)

    # SeaTalk Event Verification
    if (
        data
        and "event" in data
        and "seatalk_challenge" in data["event"]
    ):
        return data["event"]["seatalk_challenge"], 200

    # 一般事件
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
