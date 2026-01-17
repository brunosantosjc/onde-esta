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

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        address = data.get("address", {})
        rua = address.get("road")
        bairro = address.get("suburb")
        cidade = address.get("city") or address.get("town")

        partes = [p for p in [rua, bairro, cidade] if p]
        return ", ".join(partes) if partes else "localização desconhecida"
    except Exception:
        return "localização desconhecida"


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
        lat = data.get("lat")
        lon = data.get("lon")
        vel = data.get("vel", 0)
        cog = data.get("cog", 0)
        motion = data.get("m", 0)  # 1 = movendo, 0 = parado
        batt = data.get("batt", 0)
        rede = "Wi-Fi" if data.get("conn") == "w" else "Rede móvel"

        if lat is not None and lon is not None:
            ultima_posicao[nome] = {
                "lat": lat,
                "lon": lon,
                "timestamp": int(time.time()),
                "vel": vel,
                "cog": cog,
                "motion": motion,
                "batt": batt,
                "rede": rede
            }

    return jsonify({"status": "ok"})


# ==============================
# FORÇAR POSIÇÃO (MANUAL)
# ==============================
@app.route("/force/<nome>")
def force(nome):
    """
    Exemplo:
    /force/bruno?lat=-23.5055&lon=-46.4914
    """
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except Exception:
        return jsonify({"erro": "lat e lon obrigatórios"}), 400

    ultima_posicao[nome.lower()] = {
        "lat": lat,
        "lon": lon,
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
# Onde está - Primeira resposta
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
# Detalhes adicionais - Segunda resposta
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    nome = nome.lower()

    if nome not in ultima_posicao:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    pos = ultima_posicao[nome]

    # Tempo desde a última atualização
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

    motion_text = "movendo-se" if pos.get("motion", 0) == 1 else "parado"

    detalhes_texto = (
        f"Ele está {motion_text}, velocidade {pos.get('vel',0)} m/s, "
        f"direção {pos.get('c
