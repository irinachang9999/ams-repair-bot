from flask import Flask, request

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def webhook():

    # GET 驗證
    challenge = request.args.get("seatalk_challenge")
    if challenge:
        return challenge

    if request.method == "GET":
        return "Webhook Ready"

    # POST 驗證
    data = request.get_json(silent=True)

    if data and "seatalk_challenge" in data:
        return data["seatalk_challenge"]

    print(data)

    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
