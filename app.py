from flask import Flask, request, jsonify
import requests
import time
import psycopg2
import psycopg2.extras
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
def latlon_para_rua(lat, lon):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 18
            },
            headers={"User-Agent": "OndeEsta/1.0"},
            timeout=10
        )
        return r.json().get("display_name")
    except Exception as e:
        app.logger.warning("Reverse geocode falhou: %s", e)
        return None

# ==============================
# Persistência
# ==============================
def salvar_posicao(data):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ultima_posicao (
                    nome, lat, lon, vel, cog, batt, timestamp,
                    rua_cache, rua_cache_ts, estado_movimento
                )
                VALUES (
                    %(nome)s, %(lat)s, %(lon)s, %(vel)s, %(cog)s, %(batt)s,
                    %(timestamp)s, %(rua_cache)s, %(rua_cache_ts)s,
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
                    estado_movimento=EXCLUDED.estado_movimento
            """, data)
        conn.commit()

def buscar_posicao(nome):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(
                "SELECT * FROM ultima_posicao WHERE nome=%s",
                (nome,)
            )
            r = cur.fetchone()
            return dict(r) if r else None

# ==============================
# ROTAS
# ==============================

@app.route("/")
def home():
    return "API OndeEstá ONLINE"

@app.route("/health")
def health():
    try:
        with get_conn():
            return jsonify({"status": "ok"})
    except:
        return jsonify({"status": "db_error"}), 500

@app.route("/update", methods=["POST"])
def update():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"erro": "JSON inválido"}), 400

    # 🔑 DEVICE ID OBRIGATÓRIO
    nome = data.get("nome")
    if not nome:
        return jsonify({"erro": "Device ID ausente (campo nome)"}), 400

    nome = nome.lower()

    if "lat" not in data or "lon" not in data:
        return jsonify({"erro": "lat e lon são obrigatórios"}), 400

    vel = float(data.get("vel", 0))
    cog = float(data.get("cog", 0))
    batt = int(data.get("batt", 0))

    agora = int(time.time())

    estado = "andando" if vel > 0.5 else "parado"

    rua = latlon_para_rua(data["lat"], data["lon"])

    data_final = {
        "nome": nome,
        "lat": data["lat"],
        "lon": data["lon"],
        "vel": vel,
        "cog": cog,
        "batt": batt,
        "timestamp": agora,
        "estado_movimento": estado,
        "rua_cache": rua,
        "rua_cache_ts": agora
    }

    app.logger.info("UPDATE %s: %s", nome, data_final)

    salvar_posicao(data_final)
    return jsonify({"status": "ok", "device": nome})

@app.route("/where/<nome>")
def onde_esta(nome):
    pos = buscar_posicao(nome.lower())
    if not pos:
        return jsonify({"erro": "Dispositivo não encontrado"}), 404

    verbo = "está parado" if pos["estado_movimento"] == "parado" else "está passando"
    local = pos["rua_cache"] or "esse local"

    return jsonify({
        "resposta": f"{nome.capitalize()} {verbo} próximo a {local}."
    })

@app.route("/debug")
def debug():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT * FROM ultima_posicao")
            rows = cur.fetchall()
            return jsonify({
                "total": len(rows),
                "dados": [dict(r) for r in rows]
            })

# ==============================
# INIT
# ==============================
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
