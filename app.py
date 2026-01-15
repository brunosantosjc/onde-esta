from flask import Flask, request, jsonify

app = Flask(__name__)

ultima_posicao = {}

@app.route("/location", methods=["POST"])
def receive_location():
    data = request.json or {}
    device = data.get("device", "esposa")
    lat = data.get("lat")
    lon = data.get("lon")

    if lat and lon:
        ultima_posicao[device.lower()] = {
            "lat": lat,
            "lon": lon
        }

    return jsonify({"status": "ok"})

@app.route("/where/<device>")
def where(device):
    return jsonify(ultima_posicao.get(device.lower(), {}))
