from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        challenge = request.args.get("seatalk_challenge")
        if challenge:
            return challenge
        return "Webhook Ready"

    if request.method == "POST":
        data = request.get_json(silent=True)

        if data and "seatalk_challenge" in data:
            return data["seatalk_challenge"]

        print(data)
        return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
