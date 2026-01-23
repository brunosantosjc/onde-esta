from flask import Flask, request, jsonify
import requests
import time
import sqlite3
import math

app = Flask(__name__)

DB_PATH = "localizacoes.db"

# ==============================
# DEBUG
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
                rua_cache_ts INTEGER,
                estado_movimento TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regioes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                raio_metros REAL NOT NULL
            )
        """)
        conn.commit()

def salvar_posicao(nome, data):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO ultima_posicao (
                nome, lat, lon, vel, cog, batt,
                timestamp, rua_cache, rua_cache_ts, estado_movimento
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                vel=excluded.vel,
                cog=excluded.cog,
                batt=excluded.batt,
                timestamp=excluded.timestamp,
                rua_cache=excluded.rua_cache,
                rua_cache_ts=excluded.rua_cache_ts,
                estado_movimento=excluded.estado_movimento
        """, (
            nome,
            data["lat"],
            data["lon"],
            data["vel"],
            data["cog"],
            data["batt"],
            data["timestamp"],
            data.get("rua_cache"),
            data.get("rua_cache_ts"),
            data.get("estado_movimento")
        ))
        conn.commit()

def buscar_posicao(nome):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM ultima_posicao WHERE nome = ?", (nome,))
        row = cur.fetchone()
        return dict(row) if row else None

def salvar_regiao(nome, lat, lon, raio_metros=50):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO regioes (nome, lat, lon, raio_metros)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(nome) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                raio_metros=excluded.raio_metros
        """, (nome, lat, lon, raio_metros))
        conn.commit()

def verificar_regioes(lat, lon):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM regioes")
        regioes = cur.fetchall()
    resultado = []
    for r in regioes:
        if distancia_metros(lat, lon, r["lat"], r["lon"]) <= r["raio_metros"]:
            resultado.append(r["nome"])
    return resultado

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
        params = {"lat": lat, "lon": lon, "format": "json", "addressdetails": 1, "zoom": 18}
        headers = {"User-Agent": "OndeEsta/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        address = data.get("address", {})
        rua = address.get("road")
        bairro = address.get("suburb") or address.get("neighbourhood")
        cidade = address.get("city") or address.get("town")
        partes = [p for p in [rua, bairro, cidade] if p]
        return ", ".join(partes) if partes else None
    except:
        return None

# ==============================
# Direção
# ==============================
def grau_para_direcao(cog):
    direcoes = ["norte", "nordeste", "leste", "sudeste",
                "sul", "sudoeste", "oeste", "noroeste"]
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

    agora = int(time.time())
    CACHE_RUA_MAX = 15 * 60

    topic = data.get("topic", "")
    partes = topic.split("/")
    if len(partes) < 3:
        return jsonify({"erro": "Topic inválido"}), 400

    nome = partes[2].lower()
    lat = data.get("lat")
    lon = data.get("lon")
    vel_ot_ms = data.get("vel", 0) or 0
    cog = data.get("cog", 0)
    batt = data.get("batt")
    timestamp = data.get("tst", agora)

    anterior = buscar_posicao(nome)
    rua_cache = anterior.get("rua_cache") if anterior else None
    rua_cache_ts = anterior.get("rua_cache_ts") if anterior else None
    estado_anterior = anterior.get("estado_movimento") if anterior else "parado"

    vel_final_ms = vel_ot_ms
    estado_movimento = estado_anterior

    if anterior:
        dt = timestamp - anterior["timestamp"]
        if dt > 0:
            dist = distancia_metros(anterior["lat"], anterior["lon"], lat, lon)
            vel_calc_ms = dist / dt if dt >= 5 else 0
            vel_calc_kmh = vel_calc_ms * 3.6
            vel_ot_kmh = vel_ot_ms * 3.6

            if 5 < vel_ot_kmh < 160:
                vel_final_ms = vel_ot_ms
            elif vel_calc_kmh < 160:
                vel_final_ms = vel_calc_ms
            else:
                vel_final_ms = 0

            if estado_anterior == "parado":
                if dist >= 50 and dt >= 10:
                    estado_movimento = "movimento"
                elif vel_ot_kmh >= 8:
                    estado_movimento = "movimento"
                else:
                    estado_movimento = "parado"
            elif estado_anterior == "movimento":
                if dist < 20 and dt >= 90:
                    estado_movimento = "parado"
                elif vel_ot_kmh <= 3:
                    estado_movimento = "parado"
                else:
                    estado_movimento = "movimento"

            precisa_atualizar_rua = False
            if dist > 50 or not rua_cache_ts or (agora - rua_cache_ts) > CACHE_RUA_MAX:
                precisa_atualizar_rua = True
            if precisa_atualizar_rua:
                novo_local = latlon_para_rua(lat, lon)
                if novo_local:
                    rua_cache = novo_local
                    rua_cache_ts = agora

    if not rua_cache:
        rua_cache = latlon_para_rua(lat, lon)
        rua_cache_ts = agora

    salvar_posicao(nome, {
        "lat": lat,
        "lon": lon,
        "vel": vel_final_ms,
        "cog": cog,
        "batt": batt,
        "timestamp": timestamp,
        "rua_cache": rua_cache,
        "rua_cache_ts": rua_cache_ts,
        "estado_movimento": estado_movimento
    })

    config = {
        "_type": "configuration",
        "mode": 3,
        "interval": 60 if estado_movimento == "movimento" else 300,
        "accuracy": 50 if estado_movimento == "movimento" else 100,
        "keepalive": 30 if estado_movimento == "movimento" else 60
    }

    return jsonify(config)

# ==============================
# Health
# ==============================
@app.route("/", methods=["GET"])
def health():
    return "OwnTracks endpoint ativo", 200

# ==============================
# /where/<nome>
# ==============================
@app.route("/where/<nome>")
def onde_esta(nome):
    pos = buscar_posicao(nome.lower())
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    local = pos.get("rua_cache") or "essa região"
    estado = pos.get("estado_movimento")
    if estado == "parado":
        texto = f"{nome.capitalize()} está parado próximo de {local}."
    else:
        texto = f"{nome.capitalize()} está passando próximo de {local}."
    return jsonify({"resposta": texto})

# ==============================
# /details/<nome> - interativo para salvar região (apenas se parado)
# ==============================
@app.route("/details/<nome>")
def detalhes(nome):
    pos = buscar_posicao(nome.lower())
    if not pos:
        return jsonify({"erro": "Pessoa não encontrada"}), 404

    tempo = formatar_tempo(int(time.time()) - pos["timestamp"])
    estado = pos.get("estado_movimento")
    lat = pos["lat"]
    lon = pos["lon"]

    regioes_atuais = verificar_regioes(lat, lon)
    # Só pergunta para salvar se estiver parado
    precisa_salvar = len(regioes_atuais) == 0 and estado == "parado"
    local = ", ".join(regioes_atuais) if regioes_atuais else pos.get("rua_cache") or "essa região"

    if estado == "parado":
        texto = f"Essa pessoa está parada nesse local há {tempo}, bateria {pos['batt']}%."
    else:
        vel_kmh = round(pos["vel"] * 3.6)
        direcao = grau_para_direcao(pos["cog"])
        texto = f"Essa pessoa está em movimento a {vel_kmh} km/h, indo para {direcao}, por {local}. Última atualização há {tempo}, bateria {pos['batt']}%."

    return jsonify({
        "detalhes": texto,
        "precisa_salvar_regiao": precisa_salvar,
        "lat": lat,
        "lon": lon
    })

# ==============================
# Endpoint para salvar região manualmente
# ==============================
@app.route("/salvar_regiao_manual", methods=["POST"])
def salvar_regiao_manual():
    data = request.json or {}
    nome_regiao = data.get("nome")
    lat = data.get("lat")
    lon = data.get("lon")

    if not nome_regiao or not lat or not lon:
        return jsonify({"erro": "Dados insuficientes"}), 400

    salvar_regiao(nome_regiao, lat, lon, 50)
    return jsonify({"status": "ok", "mensagem": f"Região '{nome_regiao}' salva com sucesso."})

# ==============================
# Listar todas as regiões
# ==============================
@app.route("/regioes", methods=["GET"])
def listar_regioes():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM regioes")
            regioes = cur.fetchall()
        return jsonify({
            "total": len(regioes),
            "regioes": [dict(r) for r in regioes]
        })
    except Exception as e:
        print("Erro ao listar regiões:", e)
        return jsonify({"erro": "Falha ao buscar regiões", "detalhes": str(e)}), 500

# ==============================
# Init
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
