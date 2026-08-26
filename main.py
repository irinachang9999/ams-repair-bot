from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():

    print("METHOD:", request.method)
    print("ARGS:", request.args)
    print("HEADERS:", dict(request.headers))
    print("RAW:", request.get_data(as_text=True))

    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            return challenge, 200
        return "Webhook Ready", 200

    data = request.get_json(silent=True)
    print("JSON:", data)

    if (
        data
        and "event" in data
        and "seatalk_challenge" in data["event"]
    ):
        return data["event"]["seatalk_challenge"], 200

    return "OK", 200
