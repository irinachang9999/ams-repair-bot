from flask import Flask, request, Response

app = Flask(__name__)


def text_response(value, status=200):
    return Response(
        response=str(value),
        status=status,
        mimetype="text/plain"
    )


@app.route("/", methods=["GET", "POST"])
def webhook():
    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("ARGS:", request.args.to_dict())
    print("HEADERS:", dict(request.headers))
    print("RAW:", request.get_data(as_text=True))

    # GET 驗證
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            print("RETURN GET CHALLENGE:", challenge)
            return text_response(challenge)

        return text_response("Webhook Ready")

    # POST 驗證
    data = request.get_json(silent=True)
    print("JSON:", data)

    if data:
        # 格式 1：seatalk_challenge 在最外層
        if "seatalk_challenge" in data:
            challenge = data["seatalk_challenge"]
            print("RETURN POST CHALLENGE ROOT:", challenge)
            return text_response(challenge)

        # 格式 2：seatalk_challenge 在 event 裡
        if (
            "event" in data
            and isinstance(data["event"], dict)
            and "seatalk_challenge" in data["event"]
        ):
            challenge = data["event"]["seatalk_challenge"]
            print("RETURN POST CHALLENGE EVENT:", challenge)
            return text_response(challenge)

    return text_response("OK")


@app.route("/health", methods=["GET"])
def health():
    return text_response("OK")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
