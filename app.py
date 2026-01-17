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
# Função para formatar tempo desde última atualização
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
# Onde está (primeira resposta)
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    nome = nome.lower()
    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]
    rua = latlon_para_rua(pos["lat"], pos["lon"])
    tempo = tempo_desde(pos["timestamp"])

    # Se parado, não mostra direção
    direcao_texto = f", direção {pos['cog']}°" if pos["motion"] != "parado" else ""

    # Ajuste para começar com "agora" se o tempo for "agora"
    prefixo_tempo = "agora " if tempo == "agora" else ""
    primeira_resposta = f"{nome.capitalize()} está {prefixo_tempo}próximo da {rua}{direcao_texto}. Última posição {tempo}."

    return jsonify({"nome": nome, "resposta": primeira_resposta, "pos": pos})

# ==============================
# Detalhes (segunda resposta)
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    nome = nome.lower()
    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]
    tempo = tempo_desde(pos["timestamp"])

    detalhes_texto = (
        f"Ele está {pos['motion']}, velocidade {pos['vel']} m/s"
        + (f", direção {pos['cog']}°" if pos["motion"] != "parado" else "")
        + f", bateria {pos['batt']}%, conectado à {pos['rede']}. Última atualização {tempo}."
    )

    return jsonify({"nome": nome, "detalhes": detalhes_texto})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
