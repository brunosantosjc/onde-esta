from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Guarda a última posição recebida por pessoa
ultima_posicao = {}

# ==============================
# ETAPA 1 — Reverse Geocoding
# ==============================
def latlon_para_rua(lat, lon):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1
    }
    headers = {
        "User-Agent": "AlexaOndeEsta/1.0"
    }

    r = requests.get(url, params=params, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    address = data.get("address", {})
    rua = address.get("road")
    bairro = address.get("suburb")
    cidade = address.get("city") or address.get("town")

    partes = [p for p in [rua, bairro, cidade] if p]
    return ", ".join(partes) if partes else "localização desconhecida"


# ==============================
# Webhook OwnTracks
# ==============================
@app.route("/", methods=["POST"])
def owntracks_webhook():
    data = request.json or {}

    topic = data.get("topic", "")
    partes = topic.split("/")

    if len(partes) >= 2:
        nome = partes[1].lower()
    else:
        nome = "desconhecido"

    # Aceita apenas pacotes de localização
    if data.get("_type") == "location":
        lat = data.get("lat")
        lon = data.get("lon")

        if lat is not None and lon is not None:
            ultima_posicao[nome] = {
                "lat": lat,
                "lon": lon
            }

    return jsonify({"status": "ok"})


# ==============================
# Endpoint debug
# ==============================
@app.route("/debug")
def debug():
    return jsonify({
        "ultima_posicao": ultima_posicao
    })


# ==============================
# Endpoint: onde está
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    nome = nome.lower()

    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]
    rua = latlon_para_rua(pos["lat"], pos["lon"])

    return jsonify({
        "nome": nome,
        "rua": rua
    })


# ==============================
# Inicialização
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
