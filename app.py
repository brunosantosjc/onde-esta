from flask import Flask, request, jsonify
import requests
import time

app = Flask(__name__)

ultima_posicao = {}

# ==============================
# Reverse Geocoding
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

    nome = partes[1].lower() if len(partes) >= 2 else "desconhecido"

    if data.get("_type") == "location":
        ultima_posicao[nome] = {
            "lat": data.get("lat"),
            "lon": data.get("lon"),
            "vel": data.get("vel", 0),
            "cog": data.get("cog", 0),
            "motion": "em movimento" if data.get("m", 0) else "parado",
            "batt": data.get("batt", None),
            "rede": "Wi-Fi" if data.get("conn") == "w" else "rede celular",
            "timestamp": data.get("tst", int(time.time()))
        }

    return jsonify({"status": "ok"})


# ==============================
# FORÇAR POSIÇÃO (MANUAL)
# ==============================
@app.route("/force/<nome>")
def force(nome):
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except Exception:
        return jsonify({"erro": "lat e lon obrigatórios"}), 400

    ultima_posicao[nome.lower()] = {
        "lat": lat,
        "lon": lon,
        "vel": 0,
        "cog": 0,
        "motion": "parado",
        "batt": None,
        "rede": None,
        "timestamp": int(time.time())
    }

    return jsonify({
        "status": "forçado com sucesso",
        "nome": nome,
        "lat": lat,
        "lon": lon
    })


# ==============================
# Debug
# ==============================
@app.route("/debug")
def debug():
    return jsonify({
        "ultima_posicao": ultima_posicao
    })


# ==============================
# Onde está (primeira resposta)
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
# Detalhes (segunda resposta)
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    nome = nome.lower()
    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]

    # Calcula tempo desde última atualização
    agora = int(time.time())
    diff = agora - pos["timestamp"]
    if diff < 60:
        tempo = "agora"
    elif diff < 3600:
        minutos = diff // 60
        tempo = f"há {minutos} minuto{'s' if minutos > 1 else ''}"
    else:
        horas = diff // 3600
        tempo = f"há {horas} hora{'s' if horas > 1 else ''}"

    detalhes_texto = (
        f"Ele está {pos['motion']}, velocidade {pos['vel']} m/s, "
        f"direção {pos['cog']}°, bateria {pos['batt']}%, "
        f"conectado à {pos['rede']}. Última atualização {tempo}."
    )

    return jsonify({
        "nome": nome,
        "detalhes": detalhes_texto
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
