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
    params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1}
    headers = {"User-Agent": "AlexaOndeEsta/1.0"}

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
# Tempo desde última atualização
# ==============================
def tempo_desde(timestamp):
    agora = int(time.time())
    diff = agora - timestamp

    if diff < 60:
        return "agora"
    elif diff < 3600:
        minutos = diff // 60
        return f"há {minutos} minuto{'s' if minutos > 1 else ''} atrás"
    else:
        horas = diff // 3600
        return f"há {horas} hora{'s' if horas > 1 else ''} atrás"

# ==============================
# Direção em pontos cardeais
# ==============================
def grau_para_direcao(cog):
    direcoes = [
        "norte", "nordeste", "leste", "sudeste",
        "sul", "sudoeste", "oeste", "noroeste"
    ]
    idx = round(cog / 45) % 8
    return direcoes[idx]

# ==============================
# Webhook OwnTracks + Remote Config
# ==============================
@app.route("/", methods=["POST"])
def owntracks_webhook():
    data = request.json or {}

    if data.get("_type") != "location":
        return jsonify({"status": "ok"})

    topic = data.get("topic", "")
    partes = topic.split("/")
    nome = partes[1].lower() if len(partes) >= 2 else "desconhecido"

    vel_ms = data.get("vel", 0) or 0
    vel_kmh = vel_ms * 3.6
    parado = vel_kmh <= 6

    timestamp = data.get("tst", int(time.time()))

    ultima_posicao[nome] = {
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "vel": vel_ms,
        "cog": data.get("cog", 0),
        "batt": data.get("batt"),
        "timestamp": timestamp
    }

    # ==============================
    # Remote Configuration
    # ==============================
    if parado:
        config = {
            "_type": "configuration",
            "mode": 3,
            "interval": 300,     # 5 minutos parado
            "accuracy": 100,
            "keepalive": 60
        }
    else:
        config = {
            "_type": "configuration",
            "mode": 3,
            "interval": 60,      # 1 minuto em movimento
            "accuracy": 50,
            "keepalive": 30
        }

    return jsonify(config)

# ==============================
# Health check
# ==============================
@app.route("/", methods=["GET"])
def health():
    return "OwnTracks endpoint ativo", 200

# ==============================
# Primeira resposta
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    nome = nome.lower()
    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]
    rua = latlon_para_rua(pos["lat"], pos["lon"])

    vel_kmh = pos["vel"] * 3.6
    parado = vel_kmh <= 6

    if parado:
        resposta = f"{nome.capitalize()} está parado próximo da {rua}."
    else:
        resposta = f"{nome.capitalize()} está passando próximo da {rua}."

    return jsonify({"resposta": resposta})

# ==============================
# Segunda resposta (detalhes)
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    nome = nome.lower()
    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]
    tempo = tempo_desde(pos["timestamp"])

    vel_kmh = round(pos["vel"] * 3.6)
    parado = vel_kmh <= 6

    if parado:
        minutos = max(1, int((time.time() - pos["timestamp"]) / 60))
        detalhes_texto = (
            f"Essa pessoa está parada há {minutos} minuto{'s' if minutos > 1 else ''} "
            f"no mesmo local, a bateria do celular está com {pos['batt']}% de carga."
        )
    else:
        direcao = grau_para_direcao(pos["cog"])
        detalhes_texto = (
            f"Essa pessoa está em movimento a uma velocidade de {vel_kmh} km por hora, "
            f"indo para o {direcao}, a bateria do celular está com {pos['batt']}% de carga. "
            f"Última atualização {tempo}."
        )

    return jsonify({"detalhes": detalhes_texto})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
