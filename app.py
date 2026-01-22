from flask import Flask, request, jsonify
import requests
import time
import sqlite3
import math

app = Flask(__name__)

DB_PATH = "localizacoes.db"

# ==============================
# DEBUG – ver dados salvos
# ==============================
@app.route("/debug", methods=["GET"])
def debug():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ultima_posicao")
        rows = cur.fetchall()

    return jsonify({
        "total_registros": len(rows),
        "dados": [dict(r) for r in rows]
    })

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
                timestamp INTEGER,
                rua_cache TEXT,
                rua_cache_ts INTEGER
            )
        """)
        conn.commit()

def salvar_posicao(nome, data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO ultima_posicao (
                nome, lat, lon, vel, cog, batt,
                timestamp, rua_cache, rua_cache_ts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                vel=excluded.vel,
                cog=excluded.cog,
                batt=excluded.batt,
                timestamp=excluded.timestamp,
                rua_cache=excluded.rua_cache,
                rua_cache_ts=excluded.rua_cache_ts
        """, (
            nome,
            data["lat"],
            data["lon"],
            data["vel"],
            data["cog"],
            data["batt"],
            data["timestamp"],
            data.get("rua_cache"),
            data.get("rua_cache_ts")
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
# Utilidades
# ==============================
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2 +
        math.cos(phi1) * math.cos(phi2) *
        math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def formatar_tempo(segundos):
    minutos = max(1, int(segundos / 60))

    if minutos < 60:
        return f"{minutos} minuto{'s' if minutos != 1 else ''}"

    horas = minutos // 60
    resto = minutos % 60

    texto = f"{horas} hora{'s' if horas != 1 else ''}"
    if resto:
        texto += f" e {resto} minuto{'s' if resto != 1 else ''}"

    return texto

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
            "addressdetails": 1,
            "zoom": 18
        }
        headers = {
            "User-Agent": "OndeEsta/1.0 (contact: bruno.bolseiro@gmail.com)"
        }

        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        address = data.get("address", {})
        rua = address.get("road")
        bairro = address.get("suburb") or address.get("neighbourhood")
        cidade = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
        )

        partes = [p for p in [rua, bairro, cidade] if p]
        return ", ".join(partes) if partes else None

    except Exception:
        return None

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
# Webhook OwnTracks
# ==============================
@app.route("/", methods=["POST"])
def owntracks_webhook():
    data = request.json or {}

    if data.get("_type") != "location":
        return jsonify({"status": "ok"})

    CACHE_RUA_MAX = 15 * 60  # 15 minutos
    agora = int(time.time())

    topic = data.get("topic", "")
    partes = topic.split("/")

    if len(partes) < 3:
        return jsonify({"erro": "Topic inválido"}), 400

    nome = partes[2].lower()

    lat = data.get("lat")
    lon = data.get("lon")
    vel_ms = data.get("vel", 0) or 0
    cog = data.get("cog", 0)
    batt = data.get("batt")
    timestamp = data.get("tst", agora)

    anterior = buscar_posicao(nome)

    rua_cache = anterior.get("rua_cache") if anterior else None
    rua_cache_ts = anterior.get("rua_cache_ts") if anterior else None

    if anterior:
        dt = timestamp - anterior["timestamp"]

        if dt > 0:
            dist = distancia_metros(
                anterior["lat"], anterior["lon"],
                lat, lon
            )

            vel_calc_kmh = (dist / dt) * 3.6

            # Proteção contra GPS maluco
            if dist < 80 and dt < 5 and vel_calc_kmh > 15:
                vel_ms = 0
                cog = anterior["cog"]

            precisa_atualizar_rua = False

            # Atualiza se mudou de lugar
            if dist > 50:
                precisa_atualizar_rua = True

            # Ou se o cache está velho
            elif not rua_cache_ts or (agora - rua_cache_ts) > CACHE_RUA_MAX:
                precisa_atualizar_rua = True

            if precisa_atualizar_rua:
                novo_local = latlon_para_rua(lat, lon)
                if novo_local:
                    rua_cache = novo_local
                    rua_cache_ts = agora

    # Primeira resolução de endereço
    if not rua_cache:
        rua_cache = latlon_para_rua(lat, lon)
        rua_cache_ts = agora

    vel_kmh = vel_ms * 3.6
    parado = vel_kmh <= 6

    salvar_posicao(nome, {
        "lat": lat,
        "lon": lon,
        "vel": vel_ms,
        "cog": cog,
        "batt": batt,
        "timestamp": timestamp,
        "rua_cache": rua_cache,
        "rua_cache_ts": rua_cache_ts
    })

    # Configuração remota OwnTracks
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

    local = pos.get("rua_cache") or "essa região"

    vel_kmh = pos["vel"] * 3.6
    parado = vel_kmh <= 6

    if parado:
        resposta = f"{nome.capitalize()} está parado próximo de {local}."
    else:
        resposta = f"{nome.capitalize()} está passando próximo de {local}."

    return jsonify({"resposta": resposta})

# ==============================
# Segunda resposta
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    nome = nome.lower()
    pos = buscar_posicao(nome)

    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    segundos = int(time.time()) - pos["timestamp"]
    tempo_formatado = formatar_tempo(segundos)

    vel_kmh = round(pos["vel"] * 3.6)
    parado = vel_kmh <= 6

    if parado:
        texto = (
            f"Essa pessoa está parada há {tempo_formatado}, "
            f"a bateria do celular está com {pos['batt']}% de carga."
        )
    else:
        direcao = grau_para_direcao(pos["cog"])
        texto = (
            f"Essa pessoa está em movimento a {vel_kmh} km por hora, "
            f"indo para o {direcao}, a bateria está com {pos['batt']}% de carga. "
            f"Última atualização há {tempo_formatado}."
        )

    return jsonify({"detalhes": texto})

# ==============================
# Inicialização
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
