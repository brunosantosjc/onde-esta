from flask import Flask, request, jsonify
import requests
import time
import math

app = Flask(__name__)

ultima_posicao = {}

# ==============================
# Função de reverse geocoding
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
    except Exception:
        return "localização desconhecida"

    address = data.get("address", {})
    rua = address.get("road")
    bairro = address.get("suburb")
    cidade = address.get("city") or address.get("town")

    partes = [p for p in [rua, bairro, cidade] if p]
    return ", ".join(partes) if partes else "localização desconhecida"

# ==============================
# Função Haversine
# ==============================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # metros
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c

# ==============================
# Direção cardinal
# ==============================
def calcular_direcao_cardinal(cog):
    if cog is None:
        return "desconhecida"
    if (cog >= 0 and cog <= 22) or (cog > 338 and cog <= 360):
        return "Norte"
    elif cog <= 67:
        return "Nordeste"
    elif cog <= 112:
        return "Leste"
    elif cog <= 157:
        return "Sudeste"
    elif cog <= 202:
        return "Sul"
    elif cog <= 247:
        return "Sudoeste"
    elif cog <= 292:
        return "Oeste"
    else:
        return "Noroeste"

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
            "cog": data.get("cog", None),
            "motion": "em movimento" if data.get("m", 0) else "parado",
            "batt": data.get("batt", None),
            "rede": "Wi-Fi" if data.get("conn") == "w" else "rede celular",
            "timestamp": data.get("tst", int(time.time())),
            "lat_anterior": data.get("lat"),
            "lon_anterior": data.get("lon")
        }

    return jsonify({"status": "ok"})

# ==============================
# Forçar posição manual
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
        "timestamp": int(time.time()),
        "lat_anterior": lat,
        "lon_anterior": lon
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
    agora = int(time.time())
    diff = agora - pos["timestamp"]

    # Tempo desde última atualização
    if diff < 60:
        tempo = "agora"
    elif diff < 3600:
        minutos = diff // 60
        tempo = f"há {minutos} minuto{'s' if minutos > 1 else ''}"
    else:
        horas = diff // 3600
        tempo = f"há {horas} hora{'s' if horas > 1 else ''}"

    # Distância da posição anterior
    distancia = haversine(pos["lat_anterior"], pos["lon_anterior"], pos["lat"], pos["lon"])
    parado = distancia <= 10  # Raio de 10 metros
    motion_status = "parado" if parado else "em movimento"

    # Direção cardinal
    direcao = calcular_direcao_cardinal(pos.get("cog"))

    # Velocidade km/h
    vel_kmh = pos.get("vel", 0) * 3.6

    detalhes_texto = (
        f"Ele está {motion_status}, "
        f"indo na direção {direcao}, "
        f"velocidade {vel_kmh:.1f} km/h, "
        f"bateria {pos.get('batt', 'desconhecida')}%, "
        f"conectado à {pos.get('rede', 'desconhecida')}. "
        f"Última atualização {tempo}."
    )

    # Atualiza lat/lon anterior
    pos["lat_anterior"] = pos["lat"]
    pos["lon_anterior"] = pos["lon"]

    return jsonify({
        "nome": nome,
        "detalhes": detalhes_texto
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
