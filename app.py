from flask import Flask, request, jsonify
import requests
import time
import sqlite3
import os

app = Flask(__name__)

DB_PATH = "localizacoes.db"

# ==============================
# Banco de Dados
# ==============================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ultima_posicao (
                nome TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                vel REAL,
                cog REAL,
                batt INTEGER,
                timestamp INTEGER
            )
        """)
        conn.commit()

def salvar_posicao(nome, data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO ultima_posicao (nome, lat, lon, vel, cog, batt, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                vel=excluded.vel,
                cog=excluded.cog,
                batt=excluded.batt,
                timestamp=excluded.timestamp
        """, (
            nome,
            data["lat"],
            data["lon"],
            data["vel"],
            data["cog"],
            data["batt"],
            data["timestamp"]
        ))
        conn.commit()

def buscar_posicao(nome):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM ultima_posicao WHERE nome = ?",
            (nome,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

# ==============================
# Reverse Geocoding
# ==============================
def latlon_para_rua(lat, lon):
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {
            "lat": lat,
            "lon": lon,
            "format": "json",
            "addressdetails": 1
        }
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
    except Exception:
        return "localização desconhecida"

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
# Direção
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

    salvar_posicao(nome, {
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "vel": vel_ms,
        "cog": data.get("cog", 0),
        "batt": data.get("batt"),
        "timestamp": timestamp
    })

    # Remote Configuration
    if parado:
        config = {
            "_type": "configuration",
            "mode": 3,
            "interval": 300,
            "accuracy": 100,
            "keepalive": 60
        }
    else:
        config = {
            "_type": "configuration",
            "mode": 3,
            "interval": 60,
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
    pos = buscar_posicao(nome)

    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

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
    pos = buscar_posicao(nome)

    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    tempo = tempo_desde(pos["timestamp"])
    vel_kmh = round(pos["vel"] * 3.6)
    parado = vel_kmh <= 6

    if parado:
        minutos = max(1, int((time.time() - pos["timestamp"]) / 60))
        texto = (
            f"Essa pessoa está parada há {minutos} minuto{'s' if minutos > 1 else ''}, "
            f"a bateria do celular está com {pos['batt']}% de carga."
        )
    else:
        direcao = grau_para_direcao(pos["cog"])
        texto = (
            f"Essa pessoa está em movimento a {vel_kmh} km por hora, "
            f"indo para o {direcao}, a bateria está com {pos['batt']}% de carga. "
            f"Última atualização {tempo}."
        )

    return jsonify({"detalhes": texto})

# ==============================
# Inicialização
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
