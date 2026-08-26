from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():

    print("=" * 50)
    print("METHOD:", request.method)
    print("PATH:", request.path)
    print("ARGS:", request.args.to_dict())
    print("HEADERS:", dict(request.headers))
    print("RAW:", request.get_data(as_text=True))

    data = request.get_json(silent=True)
    print("JSON:", data)

    # GET challenge
    challenge = request.args.get("seatalk_challenge")
    if challenge:
        return challenge, 200

    # POST challenge
    if data:
        if "seatalk_challenge" in data:
            return data["seatalk_challenge"], 200

        if (
            "event" in data
            and isinstance(data["event"], dict)
            and "seatalk_challenge" in data["event"]
        ):
            return data["event"]["seatalk_challenge"], 200

    return "OK", 200


@app.route("/health")
def health():
    return "OK", 200
