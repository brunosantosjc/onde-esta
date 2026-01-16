from flask import Flask, request, jsonify

app = Flask(__name__)

ultima_posicao = {}
ultimo_payload = {}

@app.route("/", defaults={"path": ""}, methods=["POST"])
@app.route("/<path:path>", methods=["POST"])
def receive_location(path):
    global ultimo_payload

    data = request.get_json(force=True, silent=True)
    ultimo_payload = data

    if not data:
        return jsonify({"status": "no json"}), 400

    device = data.get("device") or data.get("tid") or "bruno"
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is not None and lon is not None:
        ultima_posicao[device.lower()] = {
            "lat": lat,
            "lon": lon
        }

    return jsonify({"status": "ok"})

@app.route("/where/<device>")
def where(device):
    return jsonify(ultima_posicao.get(device.lower(), {}))

@app.route("/debug")
def debug():
    return jsonify({
        "ultima_posicao": ultima_posicao,
        "ultimo_payload": ultimo_payload
    })
