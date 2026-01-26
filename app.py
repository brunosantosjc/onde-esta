from flask import Flask, request, jsonify
import requests
import time
import psycopg2
import psycopg2.extras
import math
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ==============================
# Banco de Dados
# ==============================
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL não configurada")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ultima_posicao (
                        nome TEXT PRIMARY KEY,
                        lat DOUBLE PRECISION,
                        lon DOUBLE PRECISION,
                        vel DOUBLE PRECISION,
                        cog DOUBLE PRECISION,
                        batt INTEGER,
                        timestamp INTEGER,
                        rua_cache TEXT,
                        rua_cache_ts INTEGER,
                        poi_cache TEXT,
                        poi_cache_ts INTEGER,
                        poi_cache_cog DOUBLE PRECISION,
                        estado_movimento TEXT
                    );
                """)
            conn.commit()
        app.logger.info("Banco inicializado")
    except Exception as e:
        app.logger.error("Erro no banco: %s", e)

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

def calcular_bearing(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def angulo_diferenca(a, b):
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)

# ==============================
# Reverse Geocoding
# ==============================
def latlon_para_rua(lat, lon):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18},
            headers={"User-Agent": "OndeEsta/1.0"},
            timeout=10
        )
        return r.json().get("display_name")
    except:
        return None

# ==============================
# Persistência
# ==============================
def salvar_posicao(nome, data):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ultima_posicao (
                    nome, lat, lon, vel, cog, batt, timestamp,
                    rua_cache, rua_cache_ts,
                    poi_cache, poi_cache_ts, poi_cache_cog,
                    estado_movimento
                )
                VALUES (
                    %(nome)s, %(lat)s, %(lon)s, %(vel)s, %(cog)s, %(batt)s, %(timestamp)s,
                    %(rua_cache)s, %(rua_cache_ts)s,
                    %(poi_cache)s, %(poi_cache_ts)s, %(poi_cache_cog)s,
                    %(estado_movimento)s
                )
                ON CONFLICT (nome) DO UPDATE SET
                    lat=EXCLUDED.lat,
                    lon=EXCLUDED.lon,
                    vel=EXCLUDED.vel,
                    cog=EXCLUDED.cog,
                    batt=EXCLUDED.batt,
                    timestamp=EXCLUDED.timestamp,
                    rua_cache=EXCLUDED.rua_cache,
                    rua_cache_ts=EXCLUDED.rua_cache_ts,
                    poi_cache=EXCLUDED.poi_cache,
                    poi_cache_ts=EXCLUDED.poi_cache_ts,
                    poi_cache_cog=EXCLUDED.poi_cache_cog,
                    estado_movimento=EXCLUDED.estado_movimento
            """, data)
        conn.commit()

def buscar_posicao(nome):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM ultima_posicao WHERE nome=%s", (nome,))
            r = cur.fetchone()
            return dict(r) if r else None

# ==============================
# UPDATE (CORRIGIDO)
# ==============================
@app.route("/update", methods=["POST"])
def update():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"erro": "JSON inválido"}), 400

    if "nome" not in data:
        return jsonify({"erro": "Campo obrigatório: nome (device_id)"}), 400

    if "lat" not in data or "lon" not in data:
        return jsonify({"erro": "lat e lon são obrigatórios"}), 400

    nome = data["nome"].lower()

    data.setdefault("vel", 0)
    data.setdefault("cog", 0)
    data.setdefault("batt", 0)

    agora = int(time.time())
    data["timestamp"] = agora
    data["estado_movimento"] = "andando" if data["vel"] > 0.5 else "parado"

    pos_ant = buscar_posicao(nome)

    if not pos_ant or agora - (pos_ant.get("rua_cache_ts") or 0) > 600:
        data["rua_cache"] = latlon_para_rua(data["lat"], data["lon"])
        data["rua_cache_ts"] = agora
    else:
        data["rua_cache"] = pos_ant["rua_cache"]
        data["rua_cache_ts"] = pos_ant["rua_cache_ts"]

    data["poi_cache"] = None
    data["poi_cache_ts"] = None
    data["poi_cache_cog"] = None

    data["nome"] = nome

    salvar_posicao(nome, data)

    return jsonify({"status": "ok"})

# ==============================
# INIT
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
